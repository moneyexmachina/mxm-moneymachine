# TODO(mxm-v1): daily_mark.py and daily_stats.py currently implement
# parallel "derived surface" orchestration patterns:
#
#   upstream dataset snapshot
#   downstream coverage snapshot
#   provenance/content-hash unchanged gate
#   optional reset semantics
#   dry-run handling
#   compute/build step
#   persistence + report emission
#
# The structural similarity is now substantial enough that these stages
# likely want a shared "derived dataset orchestrator" abstraction with:
#
#   - typed upstream/downstream coverage protocols
#   - shared provenance + unchanged gating
#   - reusable contract-run lifecycle helpers
#   - standardized report/run emission
#   - dataset-specific builder + store adapters
#
# Candidate future extraction:
#
#   marketdata/orchestration/derived_surface/
#
# where dataset-specific modules provide only:
#
#   - upstream reader/meta adapters
#   - build function
#   - downstream persistence adapter
#   - dataset-specific diagnostics mapping
#
# Deferred until after MVP publication and CI stabilization to avoid
# introducing a second-order abstraction during active schema iteration.
#
# Important:
# daily_mark and daily_stats are intentionally still separate for now
# because:
#
#   - provenance semantics are still evolving
#   - coverage models differ slightly
#   - store/meta contracts are not yet fully normalized
#   - operational behavior is still being validated in production
#
# Revisit once orchestrator semantics stabilize across datasets.

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import pandas as pd

from mxm.moneymachine.marketdata.datasets.daily_stats.selection import (
    build_daily_stats_surface,
)
from mxm.moneymachine.marketdata.datasets.daily_stats.store import DailyStatsStore
from mxm.moneymachine.marketdata.datasets.ohlcv_1d.api import (
    contract_window_utc_half_open,
)
from mxm.moneymachine.marketdata.datasets.statistics_1d.coverage import DayRange
from mxm.moneymachine.marketdata.datasets.statistics_1d.store import Statistics1DStore
from mxm.moneymachine.marketdata.mapping.vendors.databento.instrument_resolver import (
    DatabentoInstrumentIdentity,
    contract_year_month,
    resolve_databento_instrument,
)
from mxm.moneymachine.utils.time_utils import (
    ceil_to_utc_day,
    fmt_day_ts,
    fmt_run_ts,
    parse_ts,
    to_utc_day,
    to_utc_ts,
    utc_now_run_ts,
)
from mxm.refdata.api.ref_data_api import RefDataAPI  # type: ignore
from mxm.refdata.models.contracts.futures_contract import (
    FuturesContract,  # type: ignore
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


def _empty_gate_results() -> list[GateResult]:
    return []


def _empty_contract_runs() -> list[ContractRun]:
    return []


def _empty_counts() -> dict[str, Any]:
    return {}


@dataclass
class DailyStatsOrchestratorReport:
    product_id: str
    mode: Mode
    ts_utc: str

    gates: list[GateResult] = field(default_factory=_empty_gate_results)

    contracts_total: int = 0
    contracts_mapped: int = 0
    built: int = 0
    skipped_unchanged: int = 0
    skipped_no_upstream: int = 0
    unmapped: int = 0
    errors: int = 0

    runs: list[ContractRun] = field(default_factory=_empty_contract_runs)

    # Meta-orchestrator contract (compute-only stage)
    cost_used_usd: float = 0.0
    stage_status: str = ""
    stop_reason: str = ""
    counts: dict[str, Any] = field(default_factory=_empty_counts)


@dataclass(frozen=True)
class DailyStatsRunContext:
    backend: Any
    stats_store: Statistics1DStore
    daily_store: DailyStatsStore
    session_date_of: Callable[[pd.Series], pd.Series]
    dry_run: bool
    force_reset: bool
    require_source_meta: bool


@dataclass
class DailyStatsContractContext:
    contract: FuturesContract
    ident: DatabentoInstrumentIdentity | None = None
    dataset: str | None = None
    publisher_id: int | None = None
    instrument_id: int | None = None
    raw_symbol: str | None = None


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
    """
    report = _init_daily_stats_report(product_id=product_id, mode=mode)

    context = DailyStatsRunContext(
        backend=backend,
        stats_store=stats_store,
        daily_store=daily_store,
        session_date_of=session_date_of,
        dry_run=dry_run,
        force_reset=force_reset,
        require_source_meta=require_source_meta,
    )

    contracts = _prepare_daily_stats_contracts(
        product_id=product_id,
        mode=mode,
        dataset_range_start=dataset_range_start,
        dataset_range_end=dataset_range_end,
        max_contracts=max_contracts,
        contract_ids=contract_ids,
        report=report,
    )

    for contract in contracts:
        _process_daily_stats_contract(
            product_id=product_id,
            context=context,
            report=report,
            contract_context=DailyStatsContractContext(contract=contract),
        )

    _finalize_daily_stats_report(report)
    return report


def _init_daily_stats_report(
    *,
    product_id: str,
    mode: Mode,
) -> DailyStatsOrchestratorReport:
    return DailyStatsOrchestratorReport(
        product_id=product_id,
        mode=mode,
        ts_utc=utc_now_run_ts(),
    )


def _prepare_daily_stats_contracts(
    *,
    product_id: str,
    mode: Mode,
    dataset_range_start: str | None,
    dataset_range_end: str | None,
    max_contracts: int | None,
    contract_ids: set[str] | None,
    report: DailyStatsOrchestratorReport,
) -> list[FuturesContract]:
    contracts = _enumerate_contracts(product_id, mode=mode)

    contracts = _filter_daily_stats_contracts_by_dataset_range(
        contracts=contracts,
        dataset_range_start=dataset_range_start,
        dataset_range_end=dataset_range_end,
        report=report,
    )
    contracts = _filter_contracts_by_id(
        contracts=contracts,
        product_id=product_id,
        contract_ids=contract_ids,
    )
    contracts = _limit_daily_stats_contracts(
        contracts=contracts,
        max_contracts=max_contracts,
    )

    report.contracts_total = len(contracts)
    return contracts


def _filter_daily_stats_contracts_by_dataset_range(
    *,
    contracts: list[FuturesContract],
    dataset_range_start: str | None,
    dataset_range_end: str | None,
    report: DailyStatsOrchestratorReport,
) -> list[FuturesContract]:
    if dataset_range_start is None or dataset_range_end is None:
        return contracts

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

    eligible, _excluded = _subset_eligible_contracts(
        contracts_all=contracts,
        dataset_start=avail_start_ts,
        dataset_end=avail_end_ts,
    )
    return eligible


def _limit_daily_stats_contracts(
    *,
    contracts: list[FuturesContract],
    max_contracts: int | None,
) -> list[FuturesContract]:
    if max_contracts is None:
        return contracts

    if max_contracts <= 0:
        raise ValueError("max_contracts must be > 0")

    return contracts[: int(max_contracts)]


def _process_daily_stats_contract(
    *,
    product_id: str,
    context: DailyStatsRunContext,
    report: DailyStatsOrchestratorReport,
    contract_context: DailyStatsContractContext,
) -> None:
    try:
        _resolve_daily_stats_identity(
            context=context,
            report=report,
            contract_context=contract_context,
        )

        if contract_context.ident is None:
            return

        _apply_daily_stats_reset_if_requested(context, contract_context)

        up = context.stats_store.scan_coverage(
            dataset=_require_daily_stats_dataset(contract_context),
            publisher_id=_require_daily_stats_publisher_id(contract_context),
            instrument_id=_require_daily_stats_instrument_id(contract_context),
        )
        down = context.daily_store.scan_coverage(
            dataset=_require_daily_stats_dataset(contract_context),
            publisher_id=_require_daily_stats_publisher_id(contract_context),
            instrument_id=_require_daily_stats_instrument_id(contract_context),
        )

        if _append_if_daily_stats_missing_required_source_meta(
            up=up,
            down=down,
            context=context,
            report=report,
            contract_context=contract_context,
        ):
            return

        _validate_daily_stats_strict_source_meta(up=up, context=context)

        if _append_if_daily_stats_no_upstream(
            up=up,
            down=down,
            report=report,
            contract_context=contract_context,
        ):
            return

        if _append_if_daily_stats_unchanged(
            up=up,
            down=down,
            report=report,
            contract_context=contract_context,
        ):
            return

        if _append_if_daily_stats_dry_run(
            up=up,
            down=down,
            context=context,
            report=report,
            contract_context=contract_context,
        ):
            return

        _build_write_and_append_daily_stats(
            up=up,
            context=context,
            report=report,
            contract_context=contract_context,
        )

    except Exception as e:
        report.errors += 1
        report.runs.append(_daily_stats_error_run(contract_context, e))


def _resolve_daily_stats_identity(
    *,
    context: DailyStatsRunContext,
    report: DailyStatsOrchestratorReport,
    contract_context: DailyStatsContractContext,
) -> None:
    contract = contract_context.contract

    try:
        ident = resolve_databento_instrument(context.backend, contract)
    except Exception as e:
        report.unmapped += 1
        report.runs.append(_daily_stats_unmapped_run(contract, e))
        return

    contract_context.ident = ident
    contract_context.dataset = ident.dataset
    contract_context.publisher_id = int(ident.publisher_id)
    contract_context.instrument_id = int(ident.instrument_id)
    contract_context.raw_symbol = ident.raw_symbol
    report.contracts_mapped += 1


def _require_daily_stats_dataset(
    contract_context: DailyStatsContractContext,
) -> str:
    if contract_context.dataset is None:
        raise RuntimeError("daily_stats dataset has not been resolved")
    return contract_context.dataset


def _require_daily_stats_publisher_id(
    contract_context: DailyStatsContractContext,
) -> int:
    if contract_context.publisher_id is None:
        raise RuntimeError("daily_stats publisher_id has not been resolved")
    return contract_context.publisher_id


def _require_daily_stats_instrument_id(
    contract_context: DailyStatsContractContext,
) -> int:
    if contract_context.instrument_id is None:
        raise RuntimeError("daily_stats instrument_id has not been resolved")
    return contract_context.instrument_id


def _require_daily_stats_raw_symbol(
    contract_context: DailyStatsContractContext,
) -> str:
    if contract_context.raw_symbol is None:
        raise RuntimeError("daily_stats raw_symbol has not been resolved")
    return contract_context.raw_symbol


def _apply_daily_stats_reset_if_requested(
    context: DailyStatsRunContext,
    contract_context: DailyStatsContractContext,
) -> None:
    if not context.force_reset or context.dry_run:
        return

    context.daily_store.delete(
        dataset=_require_daily_stats_dataset(contract_context),
        publisher_id=_require_daily_stats_publisher_id(contract_context),
        instrument_id=_require_daily_stats_instrument_id(contract_context),
    )


def _append_if_daily_stats_missing_required_source_meta(
    *,
    up: Any,
    down: Any,
    context: DailyStatsRunContext,
    report: DailyStatsOrchestratorReport,
    contract_context: DailyStatsContractContext,
) -> bool:
    if not context.require_source_meta:
        return False

    if not (up.exists and up.row_count > 0 and not up.meta_exists):
        return False

    report.skipped_no_upstream += 1
    report.runs.append(
        _daily_stats_skipped_no_upstream_run(
            contract_context=contract_context,
            up=up,
            down=down,
            upstream_content_sha256=None,
            status_detail="statistics_meta_missing",
        )
    )
    return True


def _validate_daily_stats_strict_source_meta(
    *,
    up: Any,
    context: DailyStatsRunContext,
) -> None:
    if not context.require_source_meta:
        return

    if up.exists and up.row_count > 0 and up.content_sha256 is None:
        raise RuntimeError(
            "strict provenance violated: up.meta_exists=True but content_sha256 is None"
        )


def _append_if_daily_stats_no_upstream(
    *,
    up: Any,
    down: Any,
    report: DailyStatsOrchestratorReport,
    contract_context: DailyStatsContractContext,
) -> bool:
    if up.exists and up.row_count > 0:
        return False

    report.skipped_no_upstream += 1
    report.runs.append(
        _daily_stats_skipped_no_upstream_run(
            contract_context=contract_context,
            up=up,
            down=down,
            upstream_content_sha256=up.content_sha256,
            status_detail="statistics_1d_missing_or_empty",
        )
    )
    return True


def _append_if_daily_stats_unchanged(
    *,
    up: Any,
    down: Any,
    report: DailyStatsOrchestratorReport,
    contract_context: DailyStatsContractContext,
) -> bool:
    unchanged = (
        down.exists
        and down.source_content_sha256 is not None
        and up.content_sha256 is not None
        and down.source_content_sha256 == up.content_sha256
    )

    if not unchanged:
        return False

    report.skipped_unchanged += 1
    report.runs.append(
        _daily_stats_unchanged_run(
            contract_context=contract_context,
            up=up,
            down=down,
        )
    )
    return True


def _append_if_daily_stats_dry_run(
    *,
    up: Any,
    down: Any,
    context: DailyStatsRunContext,
    report: DailyStatsOrchestratorReport,
    contract_context: DailyStatsContractContext,
) -> bool:
    if not context.dry_run:
        return False

    report.runs.append(
        _daily_stats_dry_run(contract_context=contract_context, up=up, down=down)
    )
    return True


def _build_write_and_append_daily_stats(
    *,
    up: Any,
    context: DailyStatsRunContext,
    report: DailyStatsOrchestratorReport,
    contract_context: DailyStatsContractContext,
) -> None:
    dataset = _require_daily_stats_dataset(contract_context)
    publisher_id = _require_daily_stats_publisher_id(contract_context)
    instrument_id = _require_daily_stats_instrument_id(contract_context)

    df_stats = context.stats_store.read(
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
    )

    df_daily, _diag = build_daily_stats_surface(
        df_stats,
        session_date_of=context.session_date_of,
    )

    wmeta = context.daily_store.write(
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        df_new=df_daily,
        source_content_sha256=up.content_sha256,
        skip_if_unchanged=True,
    )

    report.built += 1
    report.runs.append(
        _daily_stats_built_run(
            contract_context=contract_context,
            up=up,
            wmeta=wmeta,
        )
    )


def _daily_stats_unmapped_run(
    contract: FuturesContract,
    error: Exception,
) -> ContractRun:
    return ContractRun(
        contract_id=str(contract.contract_id),
        contract_key=_contract_key(contract),
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
        status_detail=f"mapping_failed:{type(error).__name__}",
    )


def _daily_stats_skipped_no_upstream_run(
    *,
    contract_context: DailyStatsContractContext,
    up: Any,
    down: Any,
    upstream_content_sha256: str | None,
    status_detail: str,
) -> ContractRun:
    return ContractRun(
        contract_id=str(contract_context.contract.contract_id),
        contract_key=_contract_key(contract_context.contract),
        dataset=_require_daily_stats_dataset(contract_context),
        publisher_id=_require_daily_stats_publisher_id(contract_context),
        instrument_id=_require_daily_stats_instrument_id(contract_context),
        raw_symbol=_require_daily_stats_raw_symbol(contract_context),
        upstream_exists=bool(up.exists),
        upstream_rows=int(up.row_count),
        upstream_min=fmt_run_ts(up.min_ts) if up.min_ts is not None else None,
        upstream_max=fmt_run_ts(up.max_ts) if up.max_ts is not None else None,
        upstream_content_sha256=upstream_content_sha256,
        downstream_exists=bool(down.exists),
        downstream_rows=int(down.row_count),
        downstream_min=fmt_day_ts(down.min_ts) if down.min_ts is not None else None,
        downstream_max=fmt_day_ts(down.max_ts) if down.max_ts is not None else None,
        downstream_content_sha256=down.content_sha256,
        downstream_source_content_sha256=down.source_content_sha256,
        status="skipped_no_upstream",
        status_detail=status_detail,
        daily_stats_path=str(down.stats_path) if down.stats_path is not None else None,
    )


def _daily_stats_unchanged_run(
    *,
    contract_context: DailyStatsContractContext,
    up: Any,
    down: Any,
) -> ContractRun:
    return ContractRun(
        contract_id=str(contract_context.contract.contract_id),
        contract_key=_contract_key(contract_context.contract),
        dataset=_require_daily_stats_dataset(contract_context),
        publisher_id=_require_daily_stats_publisher_id(contract_context),
        instrument_id=_require_daily_stats_instrument_id(contract_context),
        raw_symbol=_require_daily_stats_raw_symbol(contract_context),
        upstream_exists=True,
        upstream_rows=int(up.row_count),
        upstream_min=fmt_run_ts(up.min_ts) if up.min_ts is not None else None,
        upstream_max=fmt_run_ts(up.max_ts) if up.max_ts is not None else None,
        upstream_content_sha256=up.content_sha256,
        downstream_exists=True,
        downstream_rows=int(down.row_count),
        downstream_min=fmt_day_ts(down.min_ts) if down.min_ts is not None else None,
        downstream_max=fmt_day_ts(down.max_ts) if down.max_ts is not None else None,
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


def _daily_stats_dry_run(
    *,
    contract_context: DailyStatsContractContext,
    up: Any,
    down: Any,
) -> ContractRun:
    return ContractRun(
        contract_id=str(contract_context.contract.contract_id),
        contract_key=_contract_key(contract_context.contract),
        dataset=_require_daily_stats_dataset(contract_context),
        publisher_id=_require_daily_stats_publisher_id(contract_context),
        instrument_id=_require_daily_stats_instrument_id(contract_context),
        raw_symbol=_require_daily_stats_raw_symbol(contract_context),
        upstream_exists=True,
        upstream_rows=int(up.row_count),
        upstream_min=fmt_run_ts(up.min_ts) if up.min_ts is not None else None,
        upstream_max=fmt_run_ts(up.max_ts) if up.max_ts is not None else None,
        upstream_content_sha256=up.content_sha256,
        downstream_exists=bool(down.exists),
        downstream_rows=int(down.row_count),
        downstream_min=fmt_day_ts(down.min_ts) if down.min_ts is not None else None,
        downstream_max=fmt_day_ts(down.max_ts) if down.max_ts is not None else None,
        downstream_content_sha256=down.content_sha256,
        downstream_source_content_sha256=down.source_content_sha256,
        status="dry_run",
        status_detail="would_build_and_write",
        wrote=None,
        daily_stats_path=str(down.stats_path) if down.stats_path is not None else None,
    )


def _daily_stats_built_run(
    *,
    contract_context: DailyStatsContractContext,
    up: Any,
    wmeta: dict[str, Any],
) -> ContractRun:
    ds_min = wmeta.get("session_start")
    ds_max = wmeta.get("session_end")
    ds_min_s = fmt_day_ts(ds_min) if isinstance(ds_min, pd.Timestamp) else None
    ds_max_s = fmt_day_ts(ds_max) if isinstance(ds_max, pd.Timestamp) else None

    content_sha = wmeta.get("content_sha256")
    artifact_sha = wmeta.get("artifact_sha256")

    return ContractRun(
        contract_id=str(contract_context.contract.contract_id),
        contract_key=_contract_key(contract_context.contract),
        dataset=_require_daily_stats_dataset(contract_context),
        publisher_id=_require_daily_stats_publisher_id(contract_context),
        instrument_id=_require_daily_stats_instrument_id(contract_context),
        raw_symbol=_require_daily_stats_raw_symbol(contract_context),
        upstream_exists=True,
        upstream_rows=int(up.row_count),
        upstream_min=fmt_run_ts(up.min_ts) if up.min_ts is not None else None,
        upstream_max=fmt_run_ts(up.max_ts) if up.max_ts is not None else None,
        upstream_content_sha256=up.content_sha256,
        downstream_exists=True,
        downstream_rows=int(wmeta.get("rows", 0)),
        downstream_min=ds_min_s,
        downstream_max=ds_max_s,
        downstream_content_sha256=str(content_sha) if content_sha is not None else None,
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
            str(wmeta.get("path")) if wmeta.get("path") is not None else None
        ),
    )


def _daily_stats_error_run(
    contract_context: DailyStatsContractContext,
    error: Exception,
) -> ContractRun:
    ident = contract_context.ident
    contract = contract_context.contract

    return ContractRun(
        contract_id=str(getattr(contract, "contract_id", "unknown")),
        contract_key=(
            _contract_key(contract) if hasattr(contract, "contract_id") else "unknown"
        ),
        dataset=str(getattr(ident, "dataset", None)) if ident else None,
        publisher_id=(
            int(ident.publisher_id)
            if ident and getattr(ident, "publisher_id", None) is not None
            else None
        ),
        instrument_id=(
            int(ident.instrument_id)
            if ident and getattr(ident, "instrument_id", None) is not None
            else None
        ),
        raw_symbol=str(getattr(ident, "raw_symbol", None)) if ident else None,
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
        status_detail=f"{type(error).__name__}:{str(error)[:300]}",
    )


def _finalize_daily_stats_report(report: DailyStatsOrchestratorReport) -> None:
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
        "runs": len(report.runs),
    }
