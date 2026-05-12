from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, TypedDict

import numpy as np
import pandas as pd

from mxm.refdata.api.ref_data_api import RefDataAPI  # type: ignore
from mxm.refdata.models.contracts.futures_contract import (  # type: ignore
    FuturesContract,
)
from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.marketdata.datasets.daily_mark.builder import build_daily_mark
from mxm.v1.marketdata.datasets.daily_mark.store import DailyMarkStore
from mxm.v1.marketdata.datasets.daily_stats.api import (
    read_daily_stats_contract,
    read_daily_stats_contract_meta,
)
from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    InstrumentNotMappedError,
)
from mxm.v1.utils.date_utils import coerce_np_day, fmt_iso_day
from mxm.v1.utils.time_utils import utc_now_run_ts

Mode = Literal["bootstrap", "update"]


@dataclass(frozen=True)
class GateResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ContractRun:
    product_id: str
    contract_id: str
    calendar_id: str

    requested_min_session_id: int | None
    requested_max_session_id: int | None

    upstream_exists: bool
    upstream_rows: int
    upstream_min_trading_date: str | None
    upstream_max_trading_date: str | None
    upstream_content_sha256: str | None
    daily_stats_path: str | None

    downstream_exists: bool
    downstream_rows: int
    downstream_min_session_id: int | None
    downstream_max_session_id: int | None
    downstream_content_sha256: str | None
    downstream_source_content_sha256: str | None
    daily_mark_path: str | None
    status: str  # built | skipped_unchanged | skipped_no_upstream | skipped_out_of_calendar_range | unmapped | dry_run | error
    status_detail: str | None = None

    wrote: bool | None = None
    daily_mark_rows_after: int | None = None
    daily_mark_content_sha256_after: str | None = None
    daily_mark_artifact_sha256_after: str | None = None

    observed_settle_n: int | None = None
    observed_close_n: int | None = None
    carry_forward_n: int | None = None
    unavailable_n: int | None = None
    max_carry_streak: int | None = None


def _empty_gate_results() -> list[GateResult]:
    return []


def _empty_contract_runs() -> list[ContractRun]:
    return []


class DailyMarkCounts(TypedDict):
    contracts_total: int
    built: int
    skipped_unchanged: int
    skipped_no_upstream: int
    skipped_out_of_calendar_range: int
    unmapped: int
    dry_run_n: int
    errors: int
    runs: int


def _empty_counts() -> DailyMarkCounts:
    return {
        "contracts_total": 0,
        "built": 0,
        "skipped_unchanged": 0,
        "skipped_no_upstream": 0,
        "skipped_out_of_calendar_range": 0,
        "unmapped": 0,
        "dry_run_n": 0,
        "errors": 0,
        "runs": 0,
    }


@dataclass
class DailyMarkOrchestratorReport:
    product_id: str
    calendar_id: str
    mode: Mode
    ts_utc: str

    gates: list[GateResult] = field(default_factory=_empty_gate_results)

    contracts_total: int = 0
    built: int = 0
    skipped_unchanged: int = 0
    skipped_no_upstream: int = 0
    skipped_out_of_calendar_range: int = 0
    unmapped: int = 0
    dry_run_n: int = 0
    errors: int = 0

    runs: list[ContractRun] = field(default_factory=_empty_contract_runs)

    cost_used_usd: float = 0.0
    stage_status: str = ""
    stop_reason: str = ""
    counts: DailyMarkCounts = field(default_factory=_empty_counts)


def _enumerate_contracts(product_id: str, *, mode: Mode) -> list[FuturesContract]:
    _ = mode
    api = RefDataAPI()
    contracts = list(api.get_contracts_for_product(product_id))
    contracts.sort(key=lambda c: str(c.contract_id))
    return contracts


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

    return [c for c in contracts if str(c.contract_id) in wanted]


def _contract_session_ids(
    *,
    contract: FuturesContract,
    business_calendar: MXMBusinessCalendar,
) -> tuple[int, int, np.ndarray] | None:
    """
    Derive the exact requested business-session range for a contract,
    clipped to the configured business-calendar support.

    Contract semantics:
    - contract support = [first_day_of_interest, last_trading_day] inclusive
    - business-calendar support = the ordered label support of the configured
      MXM business calendar
    - requested build range = intersection of those two intervals

    Returns
    -------
    tuple[int, int, np.ndarray] | None
        (min_session_id, max_session_id, session_ids_slice) for the inclusive
        overlap, or None if the contract lifecycle does not overlap the
        configured business calendar at all.
    """
    contract_start = coerce_np_day(contract.first_day_of_interest)
    contract_end = coerce_np_day(contract.last_trading_day)

    if contract_end < contract_start:
        raise ValueError(
            "contract lifecycle implies negative date range: "
            f"contract_id={contract.contract_id!r}, "
            f"first_day_of_interest={contract.first_day_of_interest!r}, "
            f"last_trading_day={contract.last_trading_day!r}"
        )

    labels = business_calendar.labels.astype("datetime64[D]")
    session_ids = business_calendar.session_ids

    if labels.size == 0:
        return None

    # Inclusive interval intersection against sorted business-session labels.
    left = int(np.searchsorted(labels, contract_start, side="left"))
    right_exclusive = int(np.searchsorted(labels, contract_end, side="right"))

    if left >= right_exclusive:
        return None

    selected_session_ids = session_ids[left:right_exclusive]
    if selected_session_ids.size == 0:
        return None

    min_session_id = int(selected_session_ids[0])
    max_session_id = int(selected_session_ids[-1])

    return min_session_id, max_session_id, selected_session_ids


def _upstream_snapshot_from_daily_stats(
    df: pd.DataFrame,
) -> tuple[int, str | None, str | None]:
    if df.empty:
        return 0, None, None

    min_td = fmt_iso_day(df["trading_date"].min())
    max_td = fmt_iso_day(df["trading_date"].max())
    return len(df), min_td, max_td


def derive_daily_mark_for_product(
    *,
    product_id: str,
    calendar_id: str,
    business_calendar: MXMBusinessCalendar,
    daily_mark_store: DailyMarkStore,
    root: Path | None = None,
    mode: Mode,
    max_contracts: int | None = None,
    contract_ids: set[str] | None = None,
    dry_run: bool = False,
    force_reset: bool = False,
) -> DailyMarkOrchestratorReport:
    """
    Build daily_mark for a product, contract by contract.

    Unchanged gate (v1)
    -------------------
    Skip rebuild iff:
    - downstream daily_mark exists
    - upstream daily_stats exists and is non-empty
    - downstream_source_content_sha256 == upstream_content_sha256
    - downstream range exactly matches requested session range
    - downstream artifact belongs to the requested calendar_id

    Notes
    -----
    - Builder/policy versioning is not yet part of the gate.
      Use force_reset=True after builder logic changes.
    """
    report = DailyMarkOrchestratorReport(
        product_id=product_id,
        calendar_id=calendar_id,
        mode=mode,
        ts_utc=utc_now_run_ts(),
    )

    contracts = _enumerate_contracts(product_id, mode=mode)
    contracts = _filter_contracts_by_id(
        contracts=contracts,
        product_id=product_id,
        contract_ids=contract_ids,
    )
    if max_contracts is not None:
        if max_contracts <= 0:
            raise ValueError("max_contracts must be > 0")
        contracts = contracts[: int(max_contracts)]

    report.contracts_total = len(contracts)

    for contract in contracts:
        contract_id = str(contract.contract_id)

        requested_min_session_id: int | None = None
        requested_max_session_id: int | None = None

        try:
            session_range = _contract_session_ids(
                contract=contract,
                business_calendar=business_calendar,
            )

            if session_range is None:
                report.skipped_out_of_calendar_range += 1
                report.runs.append(
                    ContractRun(
                        product_id=product_id,
                        contract_id=contract_id,
                        calendar_id=calendar_id,
                        requested_min_session_id=None,
                        requested_max_session_id=None,
                        upstream_exists=False,
                        upstream_rows=0,
                        upstream_min_trading_date=None,
                        upstream_max_trading_date=None,
                        upstream_content_sha256=None,
                        daily_stats_path=None,
                        downstream_exists=False,
                        downstream_rows=0,
                        downstream_min_session_id=None,
                        downstream_max_session_id=None,
                        downstream_content_sha256=None,
                        downstream_source_content_sha256=None,
                        daily_mark_path=None,
                        status="skipped_out_of_calendar_range",
                        status_detail="contract_lifecycle_outside_configured_business_calendar",
                    )
                )
                continue

            requested_min_session_id, requested_max_session_id, session_ids = (
                session_range
            )

            if force_reset and not dry_run:
                daily_mark_store.delete(
                    calendar_id=calendar_id,
                    contract_id=contract_id,
                )

            daily_mark_path = daily_mark_store.mark_path(
                calendar_id=calendar_id,
                contract_id=contract_id,
            )
            daily_stats_path = None

            # -------------------------
            # Upstream daily_stats
            # -------------------------
            daily_stats_meta = read_daily_stats_contract_meta(
                contract_id=contract_id,
                root=root,
            )

            df_daily_stats = read_daily_stats_contract(
                contract_id=contract_id,
                root=root,
            )
            upstream_rows, upstream_min_trading_date, upstream_max_trading_date = (
                _upstream_snapshot_from_daily_stats(df_daily_stats)
            )
            upstream_exists = upstream_rows > 0

            upstream_content_sha256 = None
            if daily_stats_meta is not None:
                raw = daily_stats_meta.get("content_sha256")
                if raw is not None:
                    upstream_content_sha256 = str(raw)
                p = daily_stats_meta.get("path")
                if p is not None:
                    daily_stats_path = str(p)

            # -------------------------
            # Downstream daily_mark
            # -------------------------
            down = daily_mark_store.scan_coverage(
                calendar_id=calendar_id,
                contract_id=contract_id,
            )
            down_meta = daily_mark_store.read_meta(
                calendar_id=calendar_id,
                contract_id=contract_id,
            )

            downstream_calendar_ok = False
            if down_meta is not None:
                meta_calendar_id = down_meta.get("calendar_id")
                downstream_calendar_ok = (
                    isinstance(meta_calendar_id, str)
                    and meta_calendar_id == calendar_id
                )

            if not upstream_exists:
                report.skipped_no_upstream += 1
                report.runs.append(
                    ContractRun(
                        product_id=product_id,
                        contract_id=contract_id,
                        calendar_id=calendar_id,
                        requested_min_session_id=requested_min_session_id,
                        requested_max_session_id=requested_max_session_id,
                        upstream_exists=False,
                        upstream_rows=0,
                        upstream_min_trading_date=None,
                        upstream_max_trading_date=None,
                        upstream_content_sha256=upstream_content_sha256,
                        daily_stats_path=daily_stats_path,
                        downstream_exists=bool(down.exists),
                        downstream_rows=int(down.row_count),
                        downstream_min_session_id=down.min_session_id,
                        downstream_max_session_id=down.max_session_id,
                        downstream_content_sha256=down.content_sha256,
                        downstream_source_content_sha256=down.source_content_sha256,
                        daily_mark_path=str(daily_mark_path),
                        status="skipped_no_upstream",
                        status_detail="daily_stats_missing_or_empty",
                    )
                )
                continue

            unchanged = (
                down.exists
                and downstream_calendar_ok
                and upstream_content_sha256 is not None
                and down.source_content_sha256 is not None
                and down.source_content_sha256 == upstream_content_sha256
                and down.min_session_id == requested_min_session_id
                and down.max_session_id == requested_max_session_id
            )

            if unchanged:
                report.skipped_unchanged += 1
                report.runs.append(
                    ContractRun(
                        product_id=product_id,
                        contract_id=contract_id,
                        calendar_id=calendar_id,
                        requested_min_session_id=requested_min_session_id,
                        requested_max_session_id=requested_max_session_id,
                        upstream_exists=True,
                        upstream_rows=upstream_rows,
                        upstream_min_trading_date=upstream_min_trading_date,
                        upstream_max_trading_date=upstream_max_trading_date,
                        upstream_content_sha256=upstream_content_sha256,
                        daily_stats_path=daily_stats_path,
                        downstream_exists=True,
                        downstream_rows=int(down.row_count),
                        downstream_min_session_id=down.min_session_id,
                        downstream_max_session_id=down.max_session_id,
                        downstream_content_sha256=down.content_sha256,
                        downstream_source_content_sha256=down.source_content_sha256,
                        daily_mark_path=str(daily_mark_path),
                        status="skipped_unchanged",
                        status_detail="source_content_sha256_and_exact_range_match",
                        wrote=False,
                        daily_mark_rows_after=int(down.row_count),
                        daily_mark_content_sha256_after=down.content_sha256,
                        daily_mark_artifact_sha256_after=down.artifact_sha256,
                    )
                )
                continue

            if dry_run:
                report.dry_run_n += 1
                report.runs.append(
                    ContractRun(
                        product_id=product_id,
                        contract_id=contract_id,
                        calendar_id=calendar_id,
                        requested_min_session_id=requested_min_session_id,
                        requested_max_session_id=requested_max_session_id,
                        upstream_exists=True,
                        upstream_rows=upstream_rows,
                        upstream_min_trading_date=upstream_min_trading_date,
                        upstream_max_trading_date=upstream_max_trading_date,
                        upstream_content_sha256=upstream_content_sha256,
                        daily_stats_path=daily_stats_path,
                        downstream_exists=bool(down.exists),
                        downstream_rows=int(down.row_count),
                        downstream_min_session_id=down.min_session_id,
                        downstream_max_session_id=down.max_session_id,
                        downstream_content_sha256=down.content_sha256,
                        downstream_source_content_sha256=down.source_content_sha256,
                        daily_mark_path=str(daily_mark_path),
                        status="dry_run",
                        status_detail="would_build_and_write",
                    )
                )
                continue

            # -------------------------
            # Build + write
            # -------------------------
            df_daily_mark, diag = build_daily_mark(
                contract_id=contract_id,
                session_ids=session_ids,
                business_calendar=business_calendar,
                daily_stats=df_daily_stats,
            )

            wmeta = daily_mark_store.write(
                calendar_id=calendar_id,
                contract_id=contract_id,
                df_new=df_daily_mark,
                source_content_sha256=upstream_content_sha256,
                skip_if_unchanged=True,
            )
            min_session_id = wmeta["min_session_id"]
            max_session_id = wmeta["max_session_id"]

            downstream_min_session_id = (
                int(min_session_id) if min_session_id is not None else None
            )
            downstream_max_session_id = (
                int(max_session_id) if max_session_id is not None else None
            )
            report.built += 1
            report.runs.append(
                ContractRun(
                    product_id=product_id,
                    contract_id=contract_id,
                    calendar_id=calendar_id,
                    requested_min_session_id=requested_min_session_id,
                    requested_max_session_id=requested_max_session_id,
                    upstream_exists=True,
                    upstream_rows=upstream_rows,
                    upstream_min_trading_date=upstream_min_trading_date,
                    upstream_max_trading_date=upstream_max_trading_date,
                    upstream_content_sha256=upstream_content_sha256,
                    daily_stats_path=daily_stats_path,
                    downstream_exists=True,
                    downstream_rows=int(wmeta.get("rows", 0)),
                    downstream_min_session_id=downstream_min_session_id,
                    downstream_max_session_id=downstream_max_session_id,
                    downstream_content_sha256=wmeta["content_sha256"],
                    downstream_source_content_sha256=upstream_content_sha256,
                    daily_mark_path=str(wmeta["path"]),
                    status="built",
                    status_detail="derived_and_persisted",
                    wrote=bool(wmeta.get("wrote", True)),
                    daily_mark_rows_after=int(wmeta.get("rows", 0)),
                    daily_mark_content_sha256_after=wmeta["content_sha256"],
                    daily_mark_artifact_sha256_after=(
                        str(wmeta["artifact_sha256"])
                        if wmeta.get("artifact_sha256") is not None
                        else None
                    ),
                    observed_settle_n=diag.observed_settle_n,
                    observed_close_n=diag.observed_close_n,
                    carry_forward_n=diag.carry_forward_n,
                    unavailable_n=diag.unavailable_n,
                    max_carry_streak=diag.max_carry_streak,
                )
            )
        except InstrumentNotMappedError as e:
            report.unmapped += 1
            report.runs.append(
                ContractRun(
                    product_id=product_id,
                    contract_id=contract_id,
                    calendar_id=calendar_id,
                    requested_min_session_id=requested_min_session_id,
                    requested_max_session_id=requested_max_session_id,
                    upstream_exists=False,
                    upstream_rows=0,
                    upstream_min_trading_date=None,
                    upstream_max_trading_date=None,
                    upstream_content_sha256=None,
                    daily_stats_path=None,
                    downstream_exists=False,
                    downstream_rows=0,
                    downstream_min_session_id=None,
                    downstream_max_session_id=None,
                    downstream_content_sha256=None,
                    downstream_source_content_sha256=None,
                    daily_mark_path=None,
                    status="unmapped",
                    status_detail=f"{type(e).__name__}:{str(e)[:300]}",
                )
            )
        except Exception as e:
            report.errors += 1
            report.runs.append(
                ContractRun(
                    product_id=product_id,
                    contract_id=contract_id,
                    calendar_id=calendar_id,
                    requested_min_session_id=requested_min_session_id,
                    requested_max_session_id=requested_max_session_id,
                    upstream_exists=False,
                    upstream_rows=0,
                    upstream_min_trading_date=None,
                    upstream_max_trading_date=None,
                    upstream_content_sha256=None,
                    daily_stats_path=None,
                    downstream_exists=False,
                    downstream_rows=0,
                    downstream_min_session_id=None,
                    downstream_max_session_id=None,
                    downstream_content_sha256=None,
                    downstream_source_content_sha256=None,
                    daily_mark_path=None,
                    status="error",
                    status_detail=f"{type(e).__name__}:{str(e)[:300]}",
                )
            )

    report.cost_used_usd = 0.0
    report.stop_reason = "ok"
    report.stage_status = "ok" if report.errors == 0 else "halted"
    report.counts = {
        "contracts_total": int(report.contracts_total),
        "built": int(report.built),
        "skipped_unchanged": int(report.skipped_unchanged),
        "skipped_no_upstream": int(report.skipped_no_upstream),
        "skipped_out_of_calendar_range": int(report.skipped_out_of_calendar_range),
        "unmapped": int(report.unmapped),
        "dry_run_n": int(report.dry_run_n),
        "errors": int(report.errors),
        "runs": len(report.runs),
    }
    return report
