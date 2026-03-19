from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Literal

import pandas as pd
from mxm_refdata.api.ref_data_api import RefDataAPI  # type: ignore
from mxm_refdata.models.contracts.futures_contract import (
    FuturesContract,  # type: ignore
)

from mxm.v1.marketdata.datasets.daily_stats.selection import build_daily_stats_surface
from mxm.v1.marketdata.datasets.daily_stats.store import DailyStatsStore
from mxm.v1.marketdata.datasets.ohlcv_1d.api import contract_window_utc_half_open
from mxm.v1.marketdata.datasets.statistics_1d.coverage import DayRange
from mxm.v1.marketdata.datasets.statistics_1d.store import Statistics1DStore
from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    DatabentoInstrumentIdentity,
    contract_year_month,
    resolve_databento_instrument,
)
from mxm.v1.utils.time_utils import (
    ceil_to_utc_day,
    fmt_day_ts,
    fmt_run_ts,
    parse_ts,
    to_utc_day,
    to_utc_ts,
    utc_now_run_ts,
)

Mode = Literal["bootstrap", "update"]


@dataclass(frozen=True)
class GateResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ContractRun:
    contract_id: str
    contract_key: str

    dataset: str | None
    publisher_id: int | None
    instrument_id: int | None
    raw_symbol: str | None

    upstream_exists: bool
    upstream_rows: int
    upstream_min: str | None
    upstream_max: str | None
    upstream_content_sha256: str | None

    downstream_exists: bool
    downstream_rows: int
    downstream_min: str | None
    downstream_max: str | None
    downstream_content_sha256: str | None
    downstream_source_content_sha256: str | None

    status: str  # built | skipped_unchanged | skipped_no_upstream | unmapped | dry_run | error
    status_detail: str | None = None

    wrote: bool | None = None
    daily_stats_rows_after: int | None = None
    daily_stats_content_sha256_after: str | None = None
    daily_stats_artifact_sha256_after: str | None = None
    daily_stats_path: str | None = None


@dataclass
class DailyStatsOrchestratorReport:
    product_id: str
    mode: Mode
    ts_utc: str

    gates: list[GateResult] = field(default_factory=list)

    contracts_total: int = 0
    contracts_mapped: int = 0
    built: int = 0
    skipped_unchanged: int = 0
    skipped_no_upstream: int = 0
    unmapped: int = 0
    errors: int = 0

    runs: list[ContractRun] = field(default_factory=list)

    # Meta-orchestrator contract (compute-only stage)
    cost_used_usd: float = 0.0
    stage_status: str = ""
    stop_reason: str = ""
    counts: dict[str, Any] = field(default_factory=dict)


def _contract_key(c: FuturesContract) -> str:
    y, m = contract_year_month(c)
    return f"{c.product_id}:{y:04d}-{m:02d}"


def _as_date(x: Any) -> date:
    if isinstance(x, date):
        return x
    if isinstance(x, str):
        return date.fromisoformat(x)
    raise TypeError(f"expected date or ISO date string, got {type(x).__name__}: {x!r}")


def _filter_contracts_by_id(
    *,
    contracts: list[FuturesContract],
    product_id: str,
    contract_ids: set[str] | None,
) -> list[FuturesContract]:
    if contract_ids is None:
        return contracts

    wanted = {str(x) for x in contract_ids}
    present = {str(c.contract_id) for c in contracts}

    missing = sorted(wanted - present)
    if missing:
        raise ValueError(
            "Requested contract_id(s) not available for product_id="
            f"{product_id!r}: {missing}"
        )

    out = [c for c in contracts if str(c.contract_id) in wanted]
    out.sort(key=lambda c: (*contract_year_month(c), str(c.contract_id)))
    return out


def _enumerate_contracts(product_id: str, *, mode: Mode) -> list[FuturesContract]:
    api = RefDataAPI()
    contracts = list(api.get_contracts_for_product(product_id))
    contracts.sort(key=lambda c: (*contract_year_month(c), str(c.contract_id)))

    if mode == "bootstrap":
        return contracts

    # update-mode: last year of contracts (same heuristic as other orchestrators)
    today = date.today()
    cutoff = today.replace(year=today.year - 1)

    eligible: list[FuturesContract] = []
    for c in contracts:
        ltd = _as_date(getattr(c, "last_trading_day", None))
        if ltd >= cutoff:
            eligible.append(c)
    return eligible


def _subset_eligible_contracts(
    *,
    contracts_all: list[FuturesContract],
    dataset_start: pd.Timestamp,
    dataset_end: pd.Timestamp,  # end-exclusive
) -> tuple[list[FuturesContract], int]:
    eligible: list[FuturesContract] = []
    excluded = 0

    for c in contracts_all:
        w = contract_window_utc_half_open(
            start_date=c.first_day_of_interest,
            end_date_inclusive=c.last_trading_day,
        )
        w_range = DayRange(start=to_utc_ts(w.start), end=to_utc_ts(w.end))
        ds_range = DayRange(start=dataset_start, end=dataset_end)

        if not w_range.intersects(ds_range):
            excluded += 1
            continue
        eligible.append(c)

    return eligible, excluded


def _default_session_date_of(ts_event: pd.Series) -> pd.Series:
    """
    Session-date label for event-time anchored stats.
    Current convention: UTC day (midnight-aligned tz-aware).
    """
    dt = pd.to_datetime(ts_event, errors="coerce", utc=True)
    return dt.dt.normalize()


def derive_daily_stats_for_product(
    *,
    backend: Any,  # SQLiteBackend
    product_id: str,
    mode: Mode,
    stats_store: Statistics1DStore,
    daily_store: DailyStatsStore,
    dataset_range_start: str | None = None,
    dataset_range_end: str | None = None,
    session_date_of: Callable[[pd.Series], pd.Series] = _default_session_date_of,
    max_contracts: int | None = None,
    contract_ids: set[str] | None = None,
    dry_run: bool = False,
    force_reset: bool = False,
    require_source_meta: bool = True,
) -> DailyStatsOrchestratorReport:
    """
    Build daily_stats for a product by contract.

    Upstream gating:
      - statistics_1d meta provides content_sha256
      - daily_stats meta stores source_content_sha256
      - if equal and daily_stats exists, skip compute + write
    """
    report = DailyStatsOrchestratorReport(
        product_id=product_id,
        mode=mode,
        ts_utc=utc_now_run_ts(),
    )

    # Optional product-level dataset-range filtering (if you want parity with other stages).
    # If not provided, we do not filter contracts here.
    avail_start_ts: pd.Timestamp | None = None
    avail_end_ts: pd.Timestamp | None = None
    if dataset_range_start is not None and dataset_range_end is not None:
        avail_start_ts = to_utc_day(parse_ts(dataset_range_start))
        avail_end_ts = ceil_to_utc_day(parse_ts(dataset_range_end))
        report.gates.append(
            GateResult(
                name="daily_stats_dataset_range_hint",
                ok=True,
                detail=(
                    f"raw=[{dataset_range_start}, {dataset_range_end}) "
                    f"aligned=[{fmt_day_ts(to_utc_ts(avail_start_ts).normalize())}, "
                    f"{fmt_day_ts(to_utc_ts(avail_end_ts).normalize())})"
                ),
            )
        )

    contracts_all = _enumerate_contracts(product_id, mode=mode)
    if avail_start_ts is not None and avail_end_ts is not None:
        eligible, _excluded = _subset_eligible_contracts(
            contracts_all=contracts_all,
            dataset_start=avail_start_ts,
            dataset_end=avail_end_ts,
        )
        contracts_all = eligible
    contracts_all = _filter_contracts_by_id(
        contracts=contracts_all,
        product_id=product_id,
        contract_ids=contract_ids,
    )
    if max_contracts is not None:
        if max_contracts <= 0:
            raise ValueError("max_contracts must be > 0")
        contracts_all = contracts_all[: int(max_contracts)]

    report.contracts_total = len(contracts_all)

    for c in contracts_all:
        ident: DatabentoInstrumentIdentity | None = None
        try:
            try:
                ident = resolve_databento_instrument(backend, c)
                report.contracts_mapped += 1
            except Exception as e:
                report.unmapped += 1
                report.runs.append(
                    ContractRun(
                        contract_id=str(c.contract_id),
                        contract_key=_contract_key(c),
                        dataset=None,
                        publisher_id=None,
                        instrument_id=None,
                        raw_symbol=None,
                        upstream_exists=False,
                        upstream_rows=0,
                        upstream_min=None,
                        upstream_max=None,
                        upstream_content_sha256=None,
                        downstream_exists=False,
                        downstream_rows=0,
                        downstream_min=None,
                        downstream_max=None,
                        downstream_content_sha256=None,
                        downstream_source_content_sha256=None,
                        status="unmapped",
                        status_detail=f"mapping_failed:{type(e).__name__}",
                    )
                )
                continue

            assert ident is not None
            dataset = ident.dataset
            publisher_id = int(ident.publisher_id)
            instrument_id = int(ident.instrument_id)
            raw_symbol = ident.raw_symbol

            # Optional reset (daily_stats only)
            if force_reset and not dry_run:
                daily_store.delete(
                    dataset=dataset,
                    publisher_id=publisher_id,
                    instrument_id=instrument_id,
                )

            # ---- upstream snapshot (meta-first) ----
            up = stats_store.scan_coverage(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
            )

            # ---- downstream snapshot (meta-first) ----
            down = daily_store.scan_coverage(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
            )
            # Strict provenance (default):
            # Require upstream meta artifact; do not accept fallback-derived coverage as provenance.
            if require_source_meta:
                # If upstream parquet missing or empty, normal "no upstream" logic applies later;
                # here we only handle the provenance-specific failure mode.
                if up.exists and up.row_count > 0 and not up.meta_exists:
                    report.skipped_no_upstream += 1
                    report.runs.append(
                        ContractRun(
                            contract_id=str(c.contract_id),
                            contract_key=_contract_key(c),
                            dataset=dataset,
                            publisher_id=publisher_id,
                            instrument_id=instrument_id,
                            raw_symbol=raw_symbol,
                            upstream_exists=True,
                            upstream_rows=int(up.row_count),
                            upstream_min=(
                                fmt_run_ts(up.min_ts) if up.min_ts is not None else None
                            ),
                            upstream_max=(
                                fmt_run_ts(up.max_ts) if up.max_ts is not None else None
                            ),
                            upstream_content_sha256=None,
                            downstream_exists=bool(down.exists),
                            downstream_rows=int(down.row_count),
                            downstream_min=(
                                fmt_run_ts(down.min_ts)
                                if down.min_ts is not None
                                else None
                            ),
                            downstream_max=(
                                fmt_run_ts(down.max_ts)
                                if down.max_ts is not None
                                else None
                            ),
                            downstream_content_sha256=down.content_sha256,
                            downstream_source_content_sha256=None,
                            status="skipped_no_upstream",
                            status_detail="statistics_meta_missing",
                        )
                    )
                    continue
            if require_source_meta and up.exists and up.row_count > 0:
                # Strict mode invariant: if we did not skip for missing meta,
                # we must have upstream content hash available from meta.
                if up.content_sha256 is None:
                    raise RuntimeError(
                        "strict provenance violated: up.meta_exists=True but content_sha256 is None"
                    )

            # If no upstream, skip (nothing to build)
            if (not up.exists) or up.row_count == 0:
                report.skipped_no_upstream += 1
                report.runs.append(
                    ContractRun(
                        contract_id=str(c.contract_id),
                        contract_key=_contract_key(c),
                        dataset=dataset,
                        publisher_id=publisher_id,
                        instrument_id=instrument_id,
                        raw_symbol=raw_symbol,
                        upstream_exists=bool(up.exists),
                        upstream_rows=int(up.row_count),
                        upstream_min=(
                            fmt_run_ts(up.min_ts) if up.min_ts is not None else None
                        ),
                        upstream_max=(
                            fmt_run_ts(up.max_ts) if up.max_ts is not None else None
                        ),
                        upstream_content_sha256=up.content_sha256,
                        downstream_exists=bool(down.exists),
                        downstream_rows=int(down.row_count),
                        downstream_min=(
                            fmt_day_ts(down.min_ts) if down.min_ts is not None else None
                        ),
                        downstream_max=(
                            fmt_day_ts(down.max_ts) if down.max_ts is not None else None
                        ),
                        downstream_content_sha256=down.content_sha256,
                        downstream_source_content_sha256=down.source_content_sha256,
                        status="skipped_no_upstream",
                        status_detail="statistics_1d_missing_or_empty",
                        daily_stats_path=(
                            str(down.stats_path)
                            if down.stats_path is not None
                            else None
                        ),
                    )
                )
                continue

            # Unchanged gate (cheap): downstream source hash matches upstream content hash
            if (
                down.exists
                and down.source_content_sha256 is not None
                and up.content_sha256 is not None
                and down.source_content_sha256 == up.content_sha256
            ):
                report.skipped_unchanged += 1
                report.runs.append(
                    ContractRun(
                        contract_id=str(c.contract_id),
                        contract_key=_contract_key(c),
                        dataset=dataset,
                        publisher_id=publisher_id,
                        instrument_id=instrument_id,
                        raw_symbol=raw_symbol,
                        upstream_exists=True,
                        upstream_rows=int(up.row_count),
                        upstream_min=(
                            fmt_run_ts(up.min_ts) if up.min_ts is not None else None
                        ),
                        upstream_max=(
                            fmt_run_ts(up.max_ts) if up.max_ts is not None else None
                        ),
                        upstream_content_sha256=up.content_sha256,
                        downstream_exists=True,
                        downstream_rows=int(down.row_count),
                        downstream_min=(
                            fmt_day_ts(down.min_ts) if down.min_ts is not None else None
                        ),
                        downstream_max=(
                            fmt_day_ts(down.max_ts) if down.max_ts is not None else None
                        ),
                        downstream_content_sha256=down.content_sha256,
                        downstream_source_content_sha256=down.source_content_sha256,
                        status="skipped_unchanged",
                        status_detail="source_content_sha256_match",
                        wrote=False,
                        daily_stats_path=str(down.stats_path),
                        daily_stats_rows_after=int(down.row_count),
                        daily_stats_content_sha256_after=down.content_sha256,
                        daily_stats_artifact_sha256_after=down.artifact_sha256,
                    )
                )
                continue

            if dry_run:
                report.runs.append(
                    ContractRun(
                        contract_id=str(c.contract_id),
                        contract_key=_contract_key(c),
                        dataset=dataset,
                        publisher_id=publisher_id,
                        instrument_id=instrument_id,
                        raw_symbol=raw_symbol,
                        upstream_exists=True,
                        upstream_rows=int(up.row_count),
                        upstream_min=(
                            fmt_run_ts(up.min_ts) if up.min_ts is not None else None
                        ),
                        upstream_max=(
                            fmt_run_ts(up.max_ts) if up.max_ts is not None else None
                        ),
                        upstream_content_sha256=up.content_sha256,
                        downstream_exists=bool(down.exists),
                        downstream_rows=int(down.row_count),
                        downstream_min=(
                            fmt_day_ts(down.min_ts) if down.min_ts is not None else None
                        ),
                        downstream_max=(
                            fmt_day_ts(down.max_ts) if down.max_ts is not None else None
                        ),
                        downstream_content_sha256=down.content_sha256,
                        downstream_source_content_sha256=down.source_content_sha256,
                        status="dry_run",
                        status_detail="would_build_and_write",
                        wrote=None,
                        daily_stats_path=(
                            str(down.stats_path)
                            if down.stats_path is not None
                            else None
                        ),
                    )
                )
                continue

            # ---- compute path (expensive) ----
            df_stats = stats_store.read(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
            )

            df_daily, _diag = build_daily_stats_surface(
                df_stats,
                session_date_of=session_date_of,
            )
            wmeta = daily_store.write(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
                df_new=df_daily,
                source_content_sha256=up.content_sha256,
                skip_if_unchanged=True,
            )

            # Prefer write-return coverage fields (already UTC-midnight for daily_stats)
            ds_min = wmeta.get("session_start")
            ds_max = wmeta.get("session_end")
            ds_min_s = fmt_day_ts(ds_min) if isinstance(ds_min, pd.Timestamp) else None
            ds_max_s = fmt_day_ts(ds_max) if isinstance(ds_max, pd.Timestamp) else None

            content_sha = wmeta.get("content_sha256")
            artifact_sha = wmeta.get("artifact_sha256")
            report.built += 1
            report.runs.append(
                ContractRun(
                    contract_id=str(c.contract_id),
                    contract_key=_contract_key(c),
                    dataset=dataset,
                    publisher_id=publisher_id,
                    instrument_id=instrument_id,
                    raw_symbol=raw_symbol,
                    upstream_exists=True,
                    upstream_rows=int(up.row_count),
                    upstream_min=(
                        fmt_run_ts(up.min_ts) if up.min_ts is not None else None
                    ),
                    upstream_max=(
                        fmt_run_ts(up.max_ts) if up.max_ts is not None else None
                    ),
                    upstream_content_sha256=up.content_sha256,
                    downstream_exists=True,
                    downstream_rows=int(wmeta.get("rows", 0)),
                    downstream_min=ds_min_s,
                    downstream_max=ds_max_s,
                    downstream_content_sha256=(
                        str(content_sha) if content_sha is not None else None
                    ),
                    downstream_source_content_sha256=up.content_sha256,
                    status="built",
                    status_detail="derived_and_persisted",
                    wrote=bool(wmeta.get("wrote", True)),
                    daily_stats_rows_after=int(wmeta.get("rows", 0)),
                    daily_stats_content_sha256_after=(
                        str(content_sha) if content_sha is not None else None
                    ),
                    daily_stats_artifact_sha256_after=(
                        str(artifact_sha) if artifact_sha is not None else None
                    ),
                    daily_stats_path=(
                        str(wmeta.get("path"))
                        if wmeta.get("path") is not None
                        else None
                    ),
                )
            )
        except Exception as e:  # noqa: BLE001
            report.errors += 1
            report.runs.append(
                ContractRun(
                    contract_id=str(getattr(c, "contract_id", "unknown")),
                    contract_key=(
                        _contract_key(c) if hasattr(c, "contract_id") else "unknown"
                    ),
                    dataset=str(getattr(ident, "dataset", None)) if ident else None,
                    publisher_id=(
                        int(getattr(ident, "publisher_id"))
                        if ident and getattr(ident, "publisher_id", None) is not None
                        else None
                    ),
                    instrument_id=(
                        int(getattr(ident, "instrument_id"))
                        if ident and getattr(ident, "instrument_id", None) is not None
                        else None
                    ),
                    raw_symbol=(
                        str(getattr(ident, "raw_symbol", None)) if ident else None
                    ),
                    upstream_exists=False,
                    upstream_rows=0,
                    upstream_min=None,
                    upstream_max=None,
                    upstream_content_sha256=None,
                    downstream_exists=False,
                    downstream_rows=0,
                    downstream_min=None,
                    downstream_max=None,
                    downstream_content_sha256=None,
                    downstream_source_content_sha256=None,
                    status="error",
                    status_detail=f"{type(e).__name__}:{str(e)[:300]}",
                )
            )

    # finalize meta surface
    report.cost_used_usd = 0.0
    report.stop_reason = "ok"
    report.stage_status = "ok" if report.errors == 0 else "halted"
    report.counts = {
        "contracts_total": int(report.contracts_total),
        "contracts_mapped": int(report.contracts_mapped),
        "built": int(report.built),
        "skipped_unchanged": int(report.skipped_unchanged),
        "skipped_no_upstream": int(report.skipped_no_upstream),
        "unmapped": int(report.unmapped),
        "errors": int(report.errors),
        "runs": int(len(report.runs)),
    }
    return report
