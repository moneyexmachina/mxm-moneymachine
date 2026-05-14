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
from mxm.v1.marketdata.datasets.daily_mark.builder import (
    DailyMarkBuildDiagnostics,
    build_daily_mark,
)
from mxm.v1.marketdata.datasets.daily_mark.store import (
    DailyMarkStore,
    DailyMarkWriteResult,
    StoreCoverageSnapshot,
)
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


@dataclass(frozen=True)
class DailyMarkRunContext:
    product_id: str
    calendar_id: str
    business_calendar: MXMBusinessCalendar
    daily_mark_store: DailyMarkStore
    root: Path | None
    dry_run: bool
    force_reset: bool


@dataclass
class DailyMarkContractContext:
    contract: FuturesContract
    contract_id: str

    requested_min_session_id: int | None = None
    requested_max_session_id: int | None = None
    session_ids: np.ndarray | None = None

    upstream_rows: int = 0
    upstream_min_trading_date: str | None = None
    upstream_max_trading_date: str | None = None
    upstream_content_sha256: str | None = None
    daily_stats_path: str | None = None
    df_daily_stats: pd.DataFrame | None = None

    daily_mark_path: str | None = None
    downstream_calendar_ok: bool = False
    downstream: StoreCoverageSnapshot | None = None


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
    """
    report = _init_daily_mark_report(
        product_id=product_id,
        calendar_id=calendar_id,
        mode=mode,
    )

    context = DailyMarkRunContext(
        product_id=product_id,
        calendar_id=calendar_id,
        business_calendar=business_calendar,
        daily_mark_store=daily_mark_store,
        root=root,
        dry_run=dry_run,
        force_reset=force_reset,
    )

    contracts = _prepare_daily_mark_contracts(
        product_id=product_id,
        mode=mode,
        max_contracts=max_contracts,
        contract_ids=contract_ids,
        report=report,
    )

    for contract in contracts:
        _process_daily_mark_contract(
            context=context,
            report=report,
            contract_context=DailyMarkContractContext(
                contract=contract,
                contract_id=str(contract.contract_id),
            ),
        )

    _finalize_daily_mark_report(report)
    return report


def _init_daily_mark_report(
    *,
    product_id: str,
    calendar_id: str,
    mode: Mode,
) -> DailyMarkOrchestratorReport:
    return DailyMarkOrchestratorReport(
        product_id=product_id,
        calendar_id=calendar_id,
        mode=mode,
        ts_utc=utc_now_run_ts(),
    )


def _prepare_daily_mark_contracts(
    *,
    product_id: str,
    mode: Mode,
    max_contracts: int | None,
    contract_ids: set[str] | None,
    report: DailyMarkOrchestratorReport,
) -> list[FuturesContract]:
    contracts = _enumerate_contracts(product_id, mode=mode)
    contracts = _filter_contracts_by_id(
        contracts=contracts,
        product_id=product_id,
        contract_ids=contract_ids,
    )

    contracts = _limit_daily_mark_contracts(
        contracts=contracts,
        max_contracts=max_contracts,
    )

    report.contracts_total = len(contracts)
    return contracts


def _limit_daily_mark_contracts(
    *,
    contracts: list[FuturesContract],
    max_contracts: int | None,
) -> list[FuturesContract]:
    if max_contracts is None:
        return contracts

    if max_contracts <= 0:
        raise ValueError("max_contracts must be > 0")

    return contracts[: int(max_contracts)]


def _process_daily_mark_contract(
    *,
    context: DailyMarkRunContext,
    report: DailyMarkOrchestratorReport,
    contract_context: DailyMarkContractContext,
) -> None:
    try:
        if _append_if_daily_mark_out_of_calendar_range(
            context=context,
            report=report,
            contract_context=contract_context,
        ):
            return

        _apply_daily_mark_reset_if_requested(context, contract_context)
        _load_daily_mark_upstream(context, contract_context)
        _load_daily_mark_downstream(context, contract_context)

        if _append_if_daily_mark_no_upstream(
            context=context,
            report=report,
            contract_context=contract_context,
        ):
            return

        if _append_if_daily_mark_unchanged(
            context=context,
            report=report,
            contract_context=contract_context,
        ):
            return

        if _append_if_daily_mark_dry_run(
            context=context,
            report=report,
            contract_context=contract_context,
        ):
            return

        _build_write_and_append_daily_mark(
            context=context,
            report=report,
            contract_context=contract_context,
        )

    except InstrumentNotMappedError as e:
        report.unmapped += 1
        report.runs.append(
            _daily_mark_unmapped_run(
                context=context, contract_context=contract_context, error=e
            )
        )

    except Exception as e:
        report.errors += 1
        report.runs.append(
            _daily_mark_error_run(
                context=context, contract_context=contract_context, error=e
            )
        )


def _append_if_daily_mark_out_of_calendar_range(
    *,
    context: DailyMarkRunContext,
    report: DailyMarkOrchestratorReport,
    contract_context: DailyMarkContractContext,
) -> bool:
    session_range = _contract_session_ids(
        contract=contract_context.contract,
        business_calendar=context.business_calendar,
    )

    if session_range is not None:
        (
            contract_context.requested_min_session_id,
            contract_context.requested_max_session_id,
            contract_context.session_ids,
        ) = session_range
        return False

    report.skipped_out_of_calendar_range += 1
    report.runs.append(
        ContractRun(
            product_id=context.product_id,
            contract_id=contract_context.contract_id,
            calendar_id=context.calendar_id,
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
    return True


def _apply_daily_mark_reset_if_requested(
    context: DailyMarkRunContext,
    contract_context: DailyMarkContractContext,
) -> None:
    if not context.force_reset or context.dry_run:
        return

    context.daily_mark_store.delete(
        calendar_id=context.calendar_id,
        contract_id=contract_context.contract_id,
    )


def _load_daily_mark_upstream(
    context: DailyMarkRunContext,
    contract_context: DailyMarkContractContext,
) -> None:
    daily_stats_meta = read_daily_stats_contract_meta(
        contract_id=contract_context.contract_id,
        root=context.root,
    )

    df_daily_stats = read_daily_stats_contract(
        contract_id=contract_context.contract_id,
        root=context.root,
    )
    (
        contract_context.upstream_rows,
        contract_context.upstream_min_trading_date,
        contract_context.upstream_max_trading_date,
    ) = _upstream_snapshot_from_daily_stats(df_daily_stats)

    contract_context.df_daily_stats = df_daily_stats

    if daily_stats_meta is None:
        return

    raw = daily_stats_meta.get("content_sha256")
    if raw is not None:
        contract_context.upstream_content_sha256 = str(raw)

    path = daily_stats_meta.get("path")
    if path is not None:
        contract_context.daily_stats_path = str(path)


def _load_daily_mark_downstream(
    context: DailyMarkRunContext,
    contract_context: DailyMarkContractContext,
) -> None:
    daily_mark_path = context.daily_mark_store.mark_path(
        calendar_id=context.calendar_id,
        contract_id=contract_context.contract_id,
    )
    contract_context.daily_mark_path = str(daily_mark_path)

    contract_context.downstream = context.daily_mark_store.scan_coverage(
        calendar_id=context.calendar_id,
        contract_id=contract_context.contract_id,
    )

    down_meta = context.daily_mark_store.read_meta(
        calendar_id=context.calendar_id,
        contract_id=contract_context.contract_id,
    )

    if down_meta is None:
        contract_context.downstream_calendar_ok = False
        return

    meta_calendar_id = down_meta.get("calendar_id")
    contract_context.downstream_calendar_ok = (
        isinstance(meta_calendar_id, str) and meta_calendar_id == context.calendar_id
    )


def _append_if_daily_mark_no_upstream(
    *,
    context: DailyMarkRunContext,
    report: DailyMarkOrchestratorReport,
    contract_context: DailyMarkContractContext,
) -> bool:
    if contract_context.upstream_rows > 0:
        return False

    report.skipped_no_upstream += 1
    report.runs.append(
        _daily_mark_no_upstream_run(context=context, contract_context=contract_context)
    )
    return True


def _append_if_daily_mark_unchanged(
    *,
    context: DailyMarkRunContext,
    report: DailyMarkOrchestratorReport,
    contract_context: DailyMarkContractContext,
) -> bool:
    down = _require_daily_mark_downstream(contract_context)

    unchanged = (
        bool(down.exists)
        and contract_context.downstream_calendar_ok
        and contract_context.upstream_content_sha256 is not None
        and down.source_content_sha256 is not None
        and down.source_content_sha256 == contract_context.upstream_content_sha256
        and down.min_session_id == contract_context.requested_min_session_id
        and down.max_session_id == contract_context.requested_max_session_id
    )

    if not unchanged:
        return False

    report.skipped_unchanged += 1
    report.runs.append(
        _daily_mark_unchanged_run(context=context, contract_context=contract_context)
    )
    return True


def _append_if_daily_mark_dry_run(
    *,
    context: DailyMarkRunContext,
    report: DailyMarkOrchestratorReport,
    contract_context: DailyMarkContractContext,
) -> bool:
    if not context.dry_run:
        return False

    report.dry_run_n += 1
    report.runs.append(
        _daily_mark_dry_run(context=context, contract_context=contract_context)
    )
    return True


def _build_write_and_append_daily_mark(
    *,
    context: DailyMarkRunContext,
    report: DailyMarkOrchestratorReport,
    contract_context: DailyMarkContractContext,
) -> None:
    session_ids = _require_daily_mark_session_ids(contract_context)
    df_daily_stats = _require_daily_mark_upstream_frame(contract_context)

    df_daily_mark, diag = build_daily_mark(
        contract_id=contract_context.contract_id,
        session_ids=session_ids,
        business_calendar=context.business_calendar,
        daily_stats=df_daily_stats,
    )

    wmeta = context.daily_mark_store.write(
        calendar_id=context.calendar_id,
        contract_id=contract_context.contract_id,
        df_new=df_daily_mark,
        source_content_sha256=contract_context.upstream_content_sha256,
        skip_if_unchanged=True,
    )

    report.built += 1
    report.runs.append(
        _daily_mark_built_run(
            context=context,
            contract_context=contract_context,
            wmeta=wmeta,
            diag=diag,
        )
    )


def _require_daily_mark_session_ids(
    contract_context: DailyMarkContractContext,
) -> np.ndarray:
    if contract_context.session_ids is None:
        raise RuntimeError("daily_mark session_ids have not been derived")
    return contract_context.session_ids


def _require_daily_mark_upstream_frame(
    contract_context: DailyMarkContractContext,
) -> pd.DataFrame:
    if contract_context.df_daily_stats is None:
        raise RuntimeError("daily_mark upstream daily_stats frame has not been loaded")
    return contract_context.df_daily_stats


def _require_daily_mark_downstream(
    contract_context: DailyMarkContractContext,
) -> StoreCoverageSnapshot:
    if contract_context.downstream is None:
        raise RuntimeError("daily_mark downstream snapshot has not been loaded")
    return contract_context.downstream


def _daily_mark_no_upstream_run(
    *,
    context: DailyMarkRunContext,
    contract_context: DailyMarkContractContext,
) -> ContractRun:
    down = _require_daily_mark_downstream(contract_context)

    return ContractRun(
        product_id=context.product_id,
        contract_id=contract_context.contract_id,
        calendar_id=context.calendar_id,
        requested_min_session_id=contract_context.requested_min_session_id,
        requested_max_session_id=contract_context.requested_max_session_id,
        upstream_exists=False,
        upstream_rows=0,
        upstream_min_trading_date=None,
        upstream_max_trading_date=None,
        upstream_content_sha256=contract_context.upstream_content_sha256,
        daily_stats_path=contract_context.daily_stats_path,
        downstream_exists=bool(down.exists),
        downstream_rows=int(down.row_count),
        downstream_min_session_id=down.min_session_id,
        downstream_max_session_id=down.max_session_id,
        downstream_content_sha256=down.content_sha256,
        downstream_source_content_sha256=down.source_content_sha256,
        daily_mark_path=contract_context.daily_mark_path,
        status="skipped_no_upstream",
        status_detail="daily_stats_missing_or_empty",
    )


def _daily_mark_unchanged_run(
    *,
    context: DailyMarkRunContext,
    contract_context: DailyMarkContractContext,
) -> ContractRun:
    down = _require_daily_mark_downstream(contract_context)

    return ContractRun(
        product_id=context.product_id,
        contract_id=contract_context.contract_id,
        calendar_id=context.calendar_id,
        requested_min_session_id=contract_context.requested_min_session_id,
        requested_max_session_id=contract_context.requested_max_session_id,
        upstream_exists=True,
        upstream_rows=contract_context.upstream_rows,
        upstream_min_trading_date=contract_context.upstream_min_trading_date,
        upstream_max_trading_date=contract_context.upstream_max_trading_date,
        upstream_content_sha256=contract_context.upstream_content_sha256,
        daily_stats_path=contract_context.daily_stats_path,
        downstream_exists=True,
        downstream_rows=int(down.row_count),
        downstream_min_session_id=down.min_session_id,
        downstream_max_session_id=down.max_session_id,
        downstream_content_sha256=down.content_sha256,
        downstream_source_content_sha256=down.source_content_sha256,
        daily_mark_path=contract_context.daily_mark_path,
        status="skipped_unchanged",
        status_detail="source_content_sha256_and_exact_range_match",
        wrote=False,
        daily_mark_rows_after=int(down.row_count),
        daily_mark_content_sha256_after=down.content_sha256,
        daily_mark_artifact_sha256_after=down.artifact_sha256,
    )


def _daily_mark_dry_run(
    *,
    context: DailyMarkRunContext,
    contract_context: DailyMarkContractContext,
) -> ContractRun:
    down = _require_daily_mark_downstream(contract_context)

    return ContractRun(
        product_id=context.product_id,
        contract_id=contract_context.contract_id,
        calendar_id=context.calendar_id,
        requested_min_session_id=contract_context.requested_min_session_id,
        requested_max_session_id=contract_context.requested_max_session_id,
        upstream_exists=True,
        upstream_rows=contract_context.upstream_rows,
        upstream_min_trading_date=contract_context.upstream_min_trading_date,
        upstream_max_trading_date=contract_context.upstream_max_trading_date,
        upstream_content_sha256=contract_context.upstream_content_sha256,
        daily_stats_path=contract_context.daily_stats_path,
        downstream_exists=bool(down.exists),
        downstream_rows=int(down.row_count),
        downstream_min_session_id=down.min_session_id,
        downstream_max_session_id=down.max_session_id,
        downstream_content_sha256=down.content_sha256,
        downstream_source_content_sha256=down.source_content_sha256,
        daily_mark_path=contract_context.daily_mark_path,
        status="dry_run",
        status_detail="would_build_and_write",
    )


def _daily_mark_built_run(
    *,
    context: DailyMarkRunContext,
    contract_context: DailyMarkContractContext,
    wmeta: DailyMarkWriteResult,
    diag: DailyMarkBuildDiagnostics,
) -> ContractRun:
    min_session_id = wmeta["min_session_id"]
    max_session_id = wmeta["max_session_id"]

    downstream_min_session_id = (
        int(min_session_id) if min_session_id is not None else None
    )
    downstream_max_session_id = (
        int(max_session_id) if max_session_id is not None else None
    )

    artifact_sha = wmeta.get("artifact_sha256")

    return ContractRun(
        product_id=context.product_id,
        contract_id=contract_context.contract_id,
        calendar_id=context.calendar_id,
        requested_min_session_id=contract_context.requested_min_session_id,
        requested_max_session_id=contract_context.requested_max_session_id,
        upstream_exists=True,
        upstream_rows=contract_context.upstream_rows,
        upstream_min_trading_date=contract_context.upstream_min_trading_date,
        upstream_max_trading_date=contract_context.upstream_max_trading_date,
        upstream_content_sha256=contract_context.upstream_content_sha256,
        daily_stats_path=contract_context.daily_stats_path,
        downstream_exists=True,
        downstream_rows=int(wmeta.get("rows", 0)),
        downstream_min_session_id=downstream_min_session_id,
        downstream_max_session_id=downstream_max_session_id,
        downstream_content_sha256=str(wmeta["content_sha256"]),
        downstream_source_content_sha256=contract_context.upstream_content_sha256,
        daily_mark_path=str(wmeta["path"]),
        status="built",
        status_detail="derived_and_persisted",
        wrote=bool(wmeta.get("wrote", True)),
        daily_mark_rows_after=int(wmeta.get("rows", 0)),
        daily_mark_content_sha256_after=str(wmeta["content_sha256"]),
        daily_mark_artifact_sha256_after=(
            str(artifact_sha) if artifact_sha is not None else None
        ),
        observed_settle_n=int(diag.observed_settle_n),
        observed_close_n=int(diag.observed_close_n),
        carry_forward_n=int(diag.carry_forward_n),
        unavailable_n=int(diag.unavailable_n),
        max_carry_streak=int(diag.max_carry_streak),
    )


def _daily_mark_unmapped_run(
    *,
    context: DailyMarkRunContext,
    contract_context: DailyMarkContractContext,
    error: Exception,
) -> ContractRun:
    return ContractRun(
        product_id=context.product_id,
        contract_id=contract_context.contract_id,
        calendar_id=context.calendar_id,
        requested_min_session_id=contract_context.requested_min_session_id,
        requested_max_session_id=contract_context.requested_max_session_id,
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
        status_detail=f"{type(error).__name__}:{str(error)[:300]}",
    )


def _daily_mark_error_run(
    *,
    context: DailyMarkRunContext,
    contract_context: DailyMarkContractContext,
    error: Exception,
) -> ContractRun:
    return ContractRun(
        product_id=context.product_id,
        contract_id=contract_context.contract_id,
        calendar_id=context.calendar_id,
        requested_min_session_id=contract_context.requested_min_session_id,
        requested_max_session_id=contract_context.requested_max_session_id,
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
        status_detail=f"{type(error).__name__}:{str(error)[:300]}",
    )


def _finalize_daily_mark_report(report: DailyMarkOrchestratorReport) -> None:
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
