# TODO(mxm-moneymachine): statistics_1d.py and ohlcv_1d.py currently implement
# the same windowed vendor-ingest orchestration pattern with dataset-
# specific adapters layered on top (store, attempts store, pull,
# normalize, cost estimation, coverage semantics, reporting).
#
# After mxm-moneymachine publication and CI stabilization, extract a generic
# windowed-ingest orchestration framework under:
#
#   mxm.moneymachine.marketdata.orchestration.windowed_ingest
#
# with dataset-specific configuration/spec objects rather than
# duplicated orchestration control flow.
#
# Important:
# - preserve explicit semantic stages and auditability
# - preserve per-dataset reporting surfaces
# - avoid premature abstraction of genuinely different semantics
# - align future extraction with mxm-pipeline / Prefect execution model

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

import pandas as pd

from mxm.moneymachine.marketdata.datasets.instrument_definitions.api import (
    get_watermark_for_product,
    read_lifecycle_for_product_instrument,
)
from mxm.moneymachine.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.moneymachine.marketdata.datasets.ohlcv_1d.api import (
    contract_window_utc_half_open,
)
from mxm.moneymachine.marketdata.datasets.ohlcv_1d.attempts_store import (
    AttemptsCoverageSnapshot,
    OHLCV1DAttemptsStore,
)
from mxm.moneymachine.marketdata.datasets.ohlcv_1d.coverage import (
    DayRange,
    complete_from_expected_and_observed,
)
from mxm.moneymachine.marketdata.datasets.ohlcv_1d.expected import (
    derive_expected_window,
)
from mxm.moneymachine.marketdata.datasets.ohlcv_1d.state import (
    BudgetContext,
    RetryPolicy,
    decide_action,
    derive_state,
)
from mxm.moneymachine.marketdata.datasets.ohlcv_1d.store import (
    OHLCV1DStore,
    StoreCoverageSnapshot,
)
from mxm.moneymachine.marketdata.mapping.vendors.databento.instrument_resolver import (
    DatabentoInstrumentIdentity,
    contract_year_month,
    resolve_databento_instrument,
)
from mxm.moneymachine.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)
from mxm.moneymachine.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.moneymachine.marketdata.vendors.databento.cost import (
    estimate_cost_ohlcv_1d,
)
from mxm.moneymachine.marketdata.vendors.databento.dataset_range import (
    get_dataset_range,
)
from mxm.moneymachine.marketdata.vendors.databento.normalize.ohlcv_1d import (
    normalize_ohlcv_1d,
)
from mxm.moneymachine.marketdata.vendors.databento.pull import (
    pull_ohlcv_1d_by_instrument_id,
)
from mxm.moneymachine.utils.time_utils import (
    fmt_day_ts,
    fmt_run_ts,
    parse_ts,
    to_utc_ts,
    utc_now_run_ts,
)
from mxm.refdata import RefDataReader
from mxm.refdata.models.contracts.futures_contract import FuturesContract

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
    target_start: str
    target_end: str
    stored_min: str | None
    stored_max: str | None
    stored_rows: int
    status: str
    windows_complete: bool
    vendor_start: str | None = None
    vendor_end: str | None = None
    vendor_final: bool = False
    cost_usd: float = 0.0
    bars_path: str | None = None


def _empty_gates() -> list[GateResult]:
    return []


def _empty_contract_runs() -> list[ContractRun]:
    return []


def _empty_counts() -> dict[str, Any]:
    return {}


@dataclass
class OHLCV1DOrchestratorReport:
    product_id: str
    mode: Mode
    ts_utc: str

    gates: list[GateResult] = field(default_factory=_empty_gates)

    cost_cap_usd: float = 0.0
    cost_usd_total: float = 0.0

    contracts_total: int = 0
    contracts_mapped: int = 0
    complete_before: int = 0
    completed_this_run: int = 0
    incomplete_remaining: int = 0
    contracts_excluded_unavailable: int = 0
    contracts_considered: int = 0
    dataset_range_start: str | None = None
    dataset_range_end: str | None = None
    runs: list[ContractRun] = field(default_factory=_empty_contract_runs)

    stopped_reason: str = ""

    counts: dict[str, Any] = field(default_factory=_empty_counts)
    cost_used_usd: float = 0.0
    stage_status: str = ""
    stop_reason: str = ""


@dataclass(frozen=True)
class OHLCV1DRunContext:
    """
    Concrete dependencies and run state for one OHLCV-1D orchestration.

    This is deliberately a local orchestration context, not an mxm-runtime
    RuntimeContext. All dependencies have already been resolved before this
    object is constructed.
    """

    refdata_reader: RefDataReader
    attempts_store: OHLCV1DAttemptsStore
    defs_store: InstrumentDefinitionsStore
    retry_policy: RetryPolicy
    avail_start_ts: pd.Timestamp
    avail_end_ts: pd.Timestamp


@dataclass
class OHLCV1DContractContext:
    contract: FuturesContract
    contract_key: str
    remaining_usd: float

    ident: DatabentoInstrumentIdentity | None = None
    ew: Any | None = None

    cov_before: AttemptsCoverageSnapshot | None = None
    cov_after: AttemptsCoverageSnapshot | None = None

    status: str | None = None
    status_detail: str | None = None

    cost_estimated_usd: float | None = None
    cost_used_usd: float | None = None
    cost_charged_usd: float | None = None

    error_type: str | None = None
    error_message: str | None = None

    should_break_after: bool = False

    interest_start_s: str | None = None
    interest_end_s: str | None = None
    exp_start_s: str | None = None
    exp_end_s: str | None = None

    windows_complete: bool = False
    is_complete_now: bool | None = None


def _contract_key(
    contract: FuturesContract,
    *,
    refdata_reader: RefDataReader,
) -> str:
    year, month = contract_year_month(
        contract,
        refdata_reader=refdata_reader,
    )
    return f"{contract.product_id}:{year:04d}-{month:02d}"


def _subset_eligible_contracts(
    *,
    contracts_all: list[FuturesContract],
    dataset_start: pd.Timestamp,
    dataset_end: pd.Timestamp,
) -> tuple[list[FuturesContract], int]:
    eligible: list[FuturesContract] = []
    excluded = 0

    for contract in contracts_all:
        window = contract_window_utc_half_open(
            start_date=contract.first_day_of_interest,
            end_date_inclusive=contract.last_trading_day,
        )

        window_range = DayRange(
            start=to_utc_ts(window.start),
            end=to_utc_ts(window.end),
        )
        dataset_range = DayRange(
            start=dataset_start,
            end=dataset_end,
        )

        if not window_range.intersects(dataset_range):
            excluded += 1
            continue

        eligible.append(contract)

    return eligible, excluded


def _gate_definitions_available(
    *,
    backend: SQLiteBackend,
    product_id: str,
) -> GateResult:
    """
    Minimal gate: definitions watermark exists for the product's feed.

    This does NOT ensure "up-to-date"; it ensures the dataset is present at all.
    """
    store = InstrumentDefinitionsStore(backend=backend)
    watermark = get_watermark_for_product(
        store=store,
        product_id=product_id,
    )

    if watermark is None:
        return GateResult(
            name="instrument_definitions_watermark_exists",
            ok=False,
            detail=f"missing watermark for product_id={product_id}",
        )

    return GateResult(
        name="instrument_definitions_watermark_exists",
        ok=True,
        detail=f"watermark={watermark}",
    )


def _as_date(x: Any) -> date:
    if isinstance(x, date):
        return x

    if isinstance(x, str):
        return date.fromisoformat(x)

    raise TypeError(f"expected date or ISO date string, got {type(x).__name__}: {x!r}")


def _enumerate_contracts(
    product_id: str,
    *,
    mode: Mode,
    context: OHLCV1DRunContext,
) -> list[FuturesContract]:
    contracts = list(context.refdata_reader.get_contracts_for_product(product_id))

    contracts.sort(
        key=lambda contract: (
            *contract_year_month(
                contract,
                refdata_reader=context.refdata_reader,
            ),
            str(contract.contract_id),
        )
    )

    if mode == "bootstrap":
        return contracts

    today = date.today()
    cutoff = today.replace(year=today.year - 1)

    eligible: list[FuturesContract] = []

    for contract in contracts:
        ltd = _as_date(
            getattr(
                contract,
                "last_trading_day",
                None,
            )
        )
        if ltd >= cutoff:
            eligible.append(contract)

    return eligible


def _cov_snapshot(
    coverage: StoreCoverageSnapshot,
) -> AttemptsCoverageSnapshot:
    """
    Adapter for OHLCV1DStore.scan_coverage(...) return.
    """
    return AttemptsCoverageSnapshot(
        min_ts=getattr(coverage, "min_ts", None),
        max_ts=getattr(coverage, "max_ts", None),
        row_count=int(getattr(coverage, "row_count", 0)),
        bars_path=(
            str(coverage.bars_path)
            if getattr(coverage, "bars_path", None) is not None
            else None
        ),
    )


def ingest_ohlcv_1d_for_product(
    *,
    refdata_reader: RefDataReader,
    backend: SQLiteBackend,
    store: OHLCV1DStore,
    product_id: str,
    mode: Mode,
    cost_cap_usd: float,
    client: Any,
    max_contracts: int | None = None,
    dry_run: bool = False,
    reset_local: bool = False,
) -> OHLCV1DOrchestratorReport:
    """
    Orchestrate ohlcv-1d persistence for a product_id.
    """
    _validate_ohlcv_1d_request(
        cost_cap_usd=cost_cap_usd,
    )

    report = _init_ohlcv_1d_report(
        product_id=product_id,
        mode=mode,
        cost_cap_usd=cost_cap_usd,
    )

    context = _prepare_ohlcv_1d_run_context(
        refdata_reader=refdata_reader,
        backend=backend,
        product_id=product_id,
        client=client,
        report=report,
    )

    contracts = _prepare_ohlcv_1d_contracts(
        product_id=product_id,
        mode=mode,
        max_contracts=max_contracts,
        context=context,
        report=report,
    )

    remaining = float(cost_cap_usd)

    for contract in contracts:
        contract_context = OHLCV1DContractContext(
            contract=contract,
            contract_key=_contract_key(
                contract,
                refdata_reader=context.refdata_reader,
            ),
            remaining_usd=remaining,
        )

        _process_ohlcv_1d_contract(
            backend=backend,
            store=store,
            product_id=product_id,
            mode=mode,
            cost_cap_usd=cost_cap_usd,
            client=client,
            dry_run=dry_run,
            reset_local=reset_local,
            context=context,
            report=report,
            contract_context=contract_context,
        )

        remaining -= float(contract_context.cost_used_usd or 0.0)

        if contract_context.should_break_after:
            break

    _finalize_ohlcv_1d_report(report)
    return report


def _validate_ohlcv_1d_request(
    *,
    cost_cap_usd: float,
) -> None:
    if cost_cap_usd <= 0:
        raise ValueError("cost_cap_usd must be > 0")


def _init_ohlcv_1d_report(
    *,
    product_id: str,
    mode: Mode,
    cost_cap_usd: float,
) -> OHLCV1DOrchestratorReport:
    return OHLCV1DOrchestratorReport(
        product_id=product_id,
        mode=mode,
        ts_utc=utc_now_run_ts(),
        cost_cap_usd=float(cost_cap_usd),
        cost_usd_total=0.0,
        stopped_reason="",
    )


def _prepare_ohlcv_1d_run_context(
    *,
    refdata_reader: RefDataReader,
    backend: SQLiteBackend,
    product_id: str,
    client: Any,
    report: OHLCV1DOrchestratorReport,
) -> OHLCV1DRunContext:
    attempts_store = OHLCV1DAttemptsStore(
        backend=backend,
    )
    defs_store = InstrumentDefinitionsStore(
        backend=backend,
    )
    retry_policy = RetryPolicy(
        max_consecutive_errors=3,
        stop_run_on_systemic_error=True,
    )

    _run_ohlcv_1d_gates(
        backend=backend,
        product_id=product_id,
        client=client,
        report=report,
    )

    if report.dataset_range_start is None or report.dataset_range_end is None:
        raise RuntimeError("ohlcv_1d dataset range gate did not populate report range")

    avail_start_ts = parse_ts(report.dataset_range_start)
    avail_end_ts = parse_ts(report.dataset_range_end)

    return OHLCV1DRunContext(
        refdata_reader=refdata_reader,
        attempts_store=attempts_store,
        defs_store=defs_store,
        retry_policy=retry_policy,
        avail_start_ts=avail_start_ts,
        avail_end_ts=avail_end_ts,
    )


def _run_ohlcv_1d_gates(
    *,
    backend: SQLiteBackend,
    product_id: str,
    client: Any,
    report: OHLCV1DOrchestratorReport,
) -> None:
    definitions_gate = _gate_definitions_available(
        backend=backend,
        product_id=product_id,
    )
    report.gates.append(definitions_gate)

    if not definitions_gate.ok:
        raise RuntimeError(
            "ohlcv_1d orchestrator gate failed: "
            "instrument_definitions not present. "
            "Run ops/instrument_definitions.py first."
        )

    root = get_databento_product_root(product_id)
    available = get_dataset_range(
        client=client,
        dataset=root.dataset,
        schema="ohlcv-1d",
    )

    report.dataset_range_start = available.start
    report.dataset_range_end = available.end

    report.gates.append(
        GateResult(
            name="databento_dataset_range_ohlcv_1d",
            ok=True,
            detail=(f"start={available.start} end={available.end} (end exclusive)"),
        )
    )


def _prepare_ohlcv_1d_contracts(
    *,
    product_id: str,
    mode: Mode,
    max_contracts: int | None,
    context: OHLCV1DRunContext,
    report: OHLCV1DOrchestratorReport,
) -> list[FuturesContract]:
    contracts_all = _enumerate_contracts(
        product_id,
        mode=mode,
        context=context,
    )

    eligible, excluded = _subset_eligible_contracts(
        contracts_all=contracts_all,
        dataset_start=context.avail_start_ts,
        dataset_end=context.avail_end_ts,
    )

    report.contracts_excluded_unavailable = excluded
    report.contracts_considered = len(eligible)

    contracts = eligible
    report.contracts_total = len(contracts)

    if max_contracts is not None:
        if max_contracts <= 0:
            raise ValueError("max_contracts must be > 0")

        contracts = contracts[: int(max_contracts)]
        report.stopped_reason = "max_contracts"

    return contracts


def _process_ohlcv_1d_contract(
    *,
    backend: SQLiteBackend,
    store: OHLCV1DStore,
    product_id: str,
    mode: Mode,
    cost_cap_usd: float,
    client: Any,
    dry_run: bool,
    reset_local: bool,
    context: OHLCV1DRunContext,
    report: OHLCV1DOrchestratorReport,
    contract_context: OHLCV1DContractContext,
) -> None:
    try:
        _populate_ohlcv_1d_interest_window(contract_context)

        _resolve_ohlcv_1d_identity(
            backend=backend,
            product_id=product_id,
            context=context,
            report=report,
            contract_context=contract_context,
        )

        if contract_context.status == "unmapped":
            return

        _populate_ohlcv_1d_expected_window(
            product_id=product_id,
            context=context,
            contract_context=contract_context,
        )

        expected_window = _require_ohlcv_1d_expected_window(contract_context)

        if expected_window.is_empty:
            contract_context.status = "skipped_empty_expected_window"
            contract_context.status_detail = "expected_window_empty"
            return

        _apply_ohlcv_1d_reset_if_requested(
            store=store,
            dry_run=dry_run,
            reset_local=reset_local,
            contract_context=contract_context,
        )

        _populate_ohlcv_1d_coverage_before(
            store=store,
            dry_run=dry_run,
            reset_local=reset_local,
            contract_context=contract_context,
        )

        _decide_ohlcv_1d_contract_action(
            context=context,
            reset_local=reset_local,
            contract_context=contract_context,
        )

        _execute_ohlcv_1d_contract_decision(
            client=client,
            store=store,
            dry_run=dry_run,
            report=report,
            contract_context=contract_context,
        )

    except Exception as error:
        contract_context.status = "error"
        contract_context.status_detail = "exception"
        contract_context.error_type = type(error).__name__
        contract_context.error_message = str(error)[:500]

    finally:
        _ensure_ohlcv_1d_expected_window(
            product_id=product_id,
            context=context,
            contract_context=contract_context,
        )

        _record_ohlcv_1d_attempt(
            mode=mode,
            dry_run=dry_run,
            reset_local=reset_local,
            cost_cap_usd=cost_cap_usd,
            product_id=product_id,
            context=context,
            report=report,
            contract_context=contract_context,
        )

        _append_ohlcv_1d_contract_run(
            report=report,
            contract_context=contract_context,
        )


def _populate_ohlcv_1d_interest_window(
    contract_context: OHLCV1DContractContext,
) -> None:
    contract = contract_context.contract

    window = contract_window_utc_half_open(
        start_date=contract.first_day_of_interest,
        end_date_inclusive=contract.last_trading_day,
    )

    window_start = to_utc_ts(window.start)
    window_end = to_utc_ts(window.end)

    contract_context.interest_start_s = fmt_day_ts(window_start)
    contract_context.interest_end_s = fmt_day_ts(window_end)


def _resolve_ohlcv_1d_identity(
    *,
    backend: SQLiteBackend,
    product_id: str,
    context: OHLCV1DRunContext,
    report: OHLCV1DOrchestratorReport,
    contract_context: OHLCV1DContractContext,
) -> None:
    contract = contract_context.contract

    try:
        contract_context.ident = resolve_databento_instrument(
            backend,
            contract,
            refdata_reader=context.refdata_reader,
        )
        report.contracts_mapped += 1

    except Exception as error:
        expected_window = derive_expected_window(
            product_id=product_id,
            contract_id=str(contract.contract_id),
            first_day_of_interest=(contract.first_day_of_interest),
            last_trading_day=(contract.last_trading_day),
            dataset_start=context.avail_start_ts,
            dataset_end=context.avail_end_ts,
            activation=None,
            expiration=None,
        )

        contract_context.ew = expected_window
        contract_context.exp_start_s = fmt_day_ts(expected_window.expected_start)
        contract_context.exp_end_s = fmt_day_ts(expected_window.expected_end)
        contract_context.interest_start_s = fmt_day_ts(expected_window.interest_start)
        contract_context.interest_end_s = fmt_day_ts(expected_window.interest_end)
        contract_context.status = "unmapped"
        contract_context.status_detail = f"mapping_failed:{type(error).__name__}"


def _populate_ohlcv_1d_expected_window(
    *,
    product_id: str,
    context: OHLCV1DRunContext,
    contract_context: OHLCV1DContractContext,
) -> None:
    contract = contract_context.contract
    ident = _require_ohlcv_1d_identity(contract_context)

    lifecycle = read_lifecycle_for_product_instrument(
        store=context.defs_store,
        product_id=product_id,
        publisher_id=ident.publisher_id,
        instrument_id=ident.instrument_id,
    )

    activation_ns, expiration_ns = lifecycle if lifecycle is not None else (None, None)

    expected_window = derive_expected_window(
        product_id=product_id,
        contract_id=str(contract.contract_id),
        first_day_of_interest=(contract.first_day_of_interest),
        last_trading_day=(contract.last_trading_day),
        dataset_start=context.avail_start_ts,
        dataset_end=context.avail_end_ts,
        activation=activation_ns,
        expiration=expiration_ns,
    )

    contract_context.ew = expected_window
    contract_context.exp_start_s = fmt_day_ts(expected_window.expected_start)
    contract_context.exp_end_s = fmt_day_ts(expected_window.expected_end)
    contract_context.interest_start_s = fmt_day_ts(expected_window.interest_start)
    contract_context.interest_end_s = fmt_day_ts(expected_window.interest_end)


def _require_ohlcv_1d_identity(
    contract_context: OHLCV1DContractContext,
) -> DatabentoInstrumentIdentity:
    if contract_context.ident is None:
        raise RuntimeError("ohlcv_1d contract identity has not been resolved")

    return contract_context.ident


def _require_ohlcv_1d_expected_window(
    contract_context: OHLCV1DContractContext,
) -> Any:
    if contract_context.ew is None:
        raise RuntimeError("ohlcv_1d expected window has not been derived")

    return contract_context.ew


def _require_ohlcv_1d_expected_window_bounds(
    contract_context: OHLCV1DContractContext,
) -> tuple[str, str]:
    start = contract_context.exp_start_s
    end = contract_context.exp_end_s

    if start is None or end is None:
        raise RuntimeError("ohlcv_1d expected window bounds have not been derived")

    return start, end


def _apply_ohlcv_1d_reset_if_requested(
    *,
    store: OHLCV1DStore,
    dry_run: bool,
    reset_local: bool,
    contract_context: OHLCV1DContractContext,
) -> None:
    if not reset_local or dry_run:
        return

    ident = _require_ohlcv_1d_identity(contract_context)

    store.delete(
        dataset=ident.dataset,
        publisher_id=ident.publisher_id,
        instrument_id=ident.instrument_id,
    )


def _populate_ohlcv_1d_coverage_before(
    *,
    store: OHLCV1DStore,
    dry_run: bool,
    reset_local: bool,
    contract_context: OHLCV1DContractContext,
) -> None:
    if reset_local and dry_run:
        contract_context.cov_before = AttemptsCoverageSnapshot(
            min_ts=None,
            max_ts=None,
            row_count=0,
        )
        return

    ident = _require_ohlcv_1d_identity(contract_context)

    contract_context.cov_before = _cov_snapshot(
        store.scan_coverage(
            dataset=ident.dataset,
            publisher_id=ident.publisher_id,
            instrument_id=ident.instrument_id,
        )
    )


def _decide_ohlcv_1d_contract_action(
    *,
    context: OHLCV1DRunContext,
    reset_local: bool,
    contract_context: OHLCV1DContractContext,
) -> None:
    contract = contract_context.contract
    expected_window = _require_ohlcv_1d_expected_window(contract_context)

    latest_attempt = context.attempts_store.get_latest_attempt_for_contract(
        product_id=contract.product_id,
        contract_id=str(contract.contract_id),
    )

    is_complete_now = complete_from_expected_and_observed(
        expected_start=(expected_window.expected_start),
        expected_end=(expected_window.expected_end),
        row_count=(
            contract_context.cov_before.row_count if contract_context.cov_before else 0
        ),
        min_ts=(
            contract_context.cov_before.min_ts if contract_context.cov_before else None
        ),
        max_ts=(
            contract_context.cov_before.max_ts if contract_context.cov_before else None
        ),
    )

    contract_context.is_complete_now = bool(is_complete_now)
    contract_context.windows_complete = bool(is_complete_now)

    derived_state = derive_state(
        latest_attempt=latest_attempt,
        ew=expected_window,
        coverage_now=contract_context.cov_before,
        is_mapped=True,
        reset_local=reset_local,
    )

    decision = decide_action(
        state=derived_state,
        policy=context.retry_policy,
        budgets=BudgetContext(remaining_usd=float(contract_context.remaining_usd)),
        latest_attempt=latest_attempt,
    )

    _apply_ohlcv_1d_decision_status(
        decision=decision,
        derived_state=derived_state,
        contract_context=contract_context,
    )


def _apply_ohlcv_1d_decision_status(
    *,
    decision: Any,
    derived_state: Any,
    contract_context: OHLCV1DContractContext,
) -> None:
    if decision.action == "attempt_ingest":
        return

    if decision.action == "stop_run":
        contract_context.status = "error"
        contract_context.status_detail = f"stop_run:{decision.reason}"
        contract_context.should_break_after = True
        return

    if decision.action == "noop":
        _apply_ohlcv_1d_noop_status(
            derived_state=derived_state,
            decision=decision,
            contract_context=contract_context,
        )
        return

    contract_context.status = "error"
    contract_context.status_detail = f"unhandled_decision:{decision.action}"


def _apply_ohlcv_1d_noop_status(
    *,
    derived_state: Any,
    decision: Any,
    contract_context: OHLCV1DContractContext,
) -> None:
    state_value = getattr(
        derived_state,
        "value",
        None,
    )

    expected_window = _require_ohlcv_1d_expected_window(contract_context)

    if state_value == "done":
        if contract_context.is_complete_now:
            contract_context.status = "complete"
            contract_context.status_detail = "already_complete"
        elif bool(
            getattr(
                expected_window,
                "vendor_final",
                False,
            )
        ):
            contract_context.status = "complete"
            contract_context.status_detail = "vendor_final_noop_partial"
        else:
            contract_context.status = "error"
            contract_context.status_detail = "inconsistent_done_without_vendor_final"
        return

    if state_value == "blocked_unmapped":
        contract_context.status = "unmapped"
        contract_context.status_detail = "blocked_unmapped"
        return

    if state_value == "blocked_empty_expected":
        contract_context.status = "skipped_empty_expected_window"
        contract_context.status_detail = "expected_window_empty"
        return

    if state_value == "skipped_budget":
        contract_context.status = "skipped_cost_cap"
        contract_context.status_detail = "skipped_budget"
        return

    if state_value in (
        "retryable_error",
        "unknown",
        "needs_ingest",
    ):
        contract_context.status = "error"
        contract_context.status_detail = (
            f"noop_in_state:{state_value}:{decision.reason}"
        )
        return

    contract_context.status = "error"
    contract_context.status_detail = (
        f"noop_unhandled_state:{state_value}:{decision.reason}"
    )


def _execute_ohlcv_1d_contract_decision(
    *,
    client: Any,
    store: OHLCV1DStore,
    dry_run: bool,
    report: OHLCV1DOrchestratorReport,
    contract_context: OHLCV1DContractContext,
) -> None:
    if contract_context.status is not None:
        if contract_context.status == "complete":
            report.complete_before += 1
        return

    if dry_run:
        contract_context.status = "dry_run"
        contract_context.status_detail = "dry_run_decision=attempt_ingest"
        return

    if contract_context.remaining_usd <= 0:
        contract_context.status = "skipped_cost_cap"
        contract_context.status_detail = "cost_cap_reached"
        contract_context.should_break_after = True
        return

    _vendor_pull_normalize_write_ohlcv_1d(
        client=client,
        store=store,
        report=report,
        contract_context=contract_context,
    )


def _vendor_pull_normalize_write_ohlcv_1d(
    *,
    client: Any,
    store: OHLCV1DStore,
    report: OHLCV1DOrchestratorReport,
    contract_context: OHLCV1DContractContext,
) -> None:
    ident = _require_ohlcv_1d_identity(contract_context)
    expected_window = _require_ohlcv_1d_expected_window(contract_context)
    exp_start_s, exp_end_s = _require_ohlcv_1d_expected_window_bounds(contract_context)

    estimate = estimate_cost_ohlcv_1d(
        client=client,
        dataset=ident.dataset,
        symbols=str(ident.instrument_id),
        stype_in="instrument_id",
        start=exp_start_s,
        end=exp_end_s,
    )

    cost_estimated_usd = float(estimate.estimated_cost_usd)
    contract_context.cost_estimated_usd = cost_estimated_usd

    if cost_estimated_usd > contract_context.remaining_usd:
        contract_context.status = "skipped_cost_cap"
        contract_context.status_detail = "estimate_exceeds_remaining"
        return

    df_raw = pull_ohlcv_1d_by_instrument_id(
        dataset=ident.dataset,
        instrument_id=ident.instrument_id,
        start=exp_start_s,
        end=exp_end_s,
        source="databento",
    )

    df = normalize_ohlcv_1d(
        df_raw,
        dataset=ident.dataset,
        raw_symbol=ident.raw_symbol,
    )

    store.write(
        dataset=ident.dataset,
        publisher_id=ident.publisher_id,
        instrument_id=ident.instrument_id,
        df_new=df,
    )

    contract_context.cost_used_usd = cost_estimated_usd
    contract_context.cost_charged_usd = cost_estimated_usd
    report.cost_usd_total += cost_estimated_usd

    contract_context.cov_after = _cov_snapshot(
        store.scan_coverage(
            dataset=ident.dataset,
            publisher_id=ident.publisher_id,
            instrument_id=ident.instrument_id,
        )
    )

    complete_after = complete_from_expected_and_observed(
        expected_start=(expected_window.expected_start),
        expected_end=(expected_window.expected_end),
        row_count=(contract_context.cov_after.row_count),
        min_ts=(contract_context.cov_after.min_ts),
        max_ts=(contract_context.cov_after.max_ts),
    )

    if complete_after:
        contract_context.status = "ingested"
        contract_context.status_detail = "ingested_complete"
        contract_context.windows_complete = True
        report.completed_this_run += 1

    elif expected_window.vendor_final:
        contract_context.status = "ingested"
        contract_context.status_detail = "vendor_final_partial"
        contract_context.windows_complete = False

    else:
        contract_context.status = "incomplete"
        contract_context.status_detail = "incomplete_after_ingest"
        contract_context.windows_complete = False


def _ensure_ohlcv_1d_expected_window(
    *,
    product_id: str,
    context: OHLCV1DRunContext,
    contract_context: OHLCV1DContractContext,
) -> None:
    if contract_context.ew is not None:
        return

    contract = contract_context.contract

    expected_window = derive_expected_window(
        product_id=product_id,
        contract_id=str(contract.contract_id),
        first_day_of_interest=(contract.first_day_of_interest),
        last_trading_day=(contract.last_trading_day),
        dataset_start=context.avail_start_ts,
        dataset_end=context.avail_end_ts,
        activation=None,
        expiration=None,
    )

    contract_context.ew = expected_window
    contract_context.exp_start_s = fmt_day_ts(expected_window.expected_start)
    contract_context.exp_end_s = fmt_day_ts(expected_window.expected_end)
    contract_context.interest_start_s = fmt_day_ts(expected_window.interest_start)
    contract_context.interest_end_s = fmt_day_ts(expected_window.interest_end)


def _record_ohlcv_1d_attempt(
    *,
    mode: Mode,
    dry_run: bool,
    reset_local: bool,
    cost_cap_usd: float,
    product_id: str,
    context: OHLCV1DRunContext,
    report: OHLCV1DOrchestratorReport,
    contract_context: OHLCV1DContractContext,
) -> None:
    contract = contract_context.contract
    ident = contract_context.ident

    expected_window = _require_ohlcv_1d_expected_window(contract_context)

    context.attempts_store.record_attempt(
        run_ts_utc=report.ts_utc,
        mode=mode,
        dry_run=bool(dry_run),
        reset_local=bool(reset_local),
        cost_cap_usd=float(cost_cap_usd),
        product_id=product_id,
        contract_id=str(contract.contract_id),
        contract_key=(contract_context.contract_key),
        feed=(getattr(ident, "feed", None) if ident else None),
        dataset=(getattr(ident, "dataset", None) if ident else None),
        publisher_id=(
            getattr(
                ident,
                "publisher_id",
                None,
            )
            if ident
            else None
        ),
        instrument_id=(
            getattr(
                ident,
                "instrument_id",
                None,
            )
            if ident
            else None
        ),
        raw_symbol=(
            getattr(
                ident,
                "raw_symbol",
                None,
            )
            if ident
            else None
        ),
        ew=expected_window,
        status=(contract_context.status or "error"),
        status_detail=(contract_context.status_detail),
        cost_estimated_usd=(contract_context.cost_estimated_usd),
        cost_used_usd=(contract_context.cost_used_usd),
        cost_charged_usd=(contract_context.cost_charged_usd),
        coverage_before=(contract_context.cov_before),
        coverage_after=(contract_context.cov_after),
        error_type=(contract_context.error_type),
        error_message=(contract_context.error_message),
    )


def _append_ohlcv_1d_contract_run(
    *,
    report: OHLCV1DOrchestratorReport,
    contract_context: OHLCV1DContractContext,
) -> None:
    contract = contract_context.contract

    expected_window = _require_ohlcv_1d_expected_window(contract_context)

    coverage_for_report = contract_context.cov_after or contract_context.cov_before

    stored_min = (
        fmt_run_ts(coverage_for_report.min_ts)
        if (coverage_for_report and coverage_for_report.min_ts is not None)
        else None
    )

    stored_max = (
        fmt_run_ts(coverage_for_report.max_ts)
        if (coverage_for_report and coverage_for_report.max_ts is not None)
        else None
    )

    stored_rows = int(coverage_for_report.row_count) if coverage_for_report else 0

    bars_path = coverage_for_report.bars_path if coverage_for_report else None

    report.runs.append(
        ContractRun(
            contract_id=str(contract.contract_id),
            contract_key=(contract_context.contract_key),
            target_start=(
                contract_context.interest_start_s
                or fmt_day_ts(expected_window.interest_start)
            ),
            target_end=(
                contract_context.interest_end_s
                or fmt_day_ts(expected_window.interest_end)
            ),
            vendor_start=(contract_context.exp_start_s),
            vendor_end=(contract_context.exp_end_s),
            vendor_final=bool(
                getattr(
                    expected_window,
                    "vendor_final",
                    False,
                )
            ),
            stored_min=stored_min,
            stored_max=stored_max,
            stored_rows=stored_rows,
            status=(contract_context.status or "error"),
            windows_complete=(contract_context.windows_complete),
            cost_usd=float(contract_context.cost_used_usd or 0.0),
            bars_path=bars_path,
        )
    )


def _finalize_ohlcv_1d_report(
    report: OHLCV1DOrchestratorReport,
) -> None:
    report.incomplete_remaining = sum(
        1 for run in report.runs if not run.windows_complete
    )

    if report.stopped_reason == "":
        report.stopped_reason = "ok"

    report.cost_used_usd = float(report.cost_usd_total)
    report.stop_reason = report.stopped_reason

    if report.stopped_reason in (
        "ok",
        "max_contracts",
    ):
        report.stage_status = "ok"
    else:
        report.stage_status = "halted"

    report.counts = {
        "contracts_total": int(report.contracts_total),
        "contracts_mapped": int(report.contracts_mapped),
        "complete_before": int(report.complete_before),
        "completed_this_run": int(report.completed_this_run),
        "incomplete_remaining": int(report.incomplete_remaining),
        "contracts_excluded_unavailable": int(report.contracts_excluded_unavailable),
        "contracts_considered": int(report.contracts_considered),
        "runs": len(report.runs),
        "dataset_range_start": (report.dataset_range_start),
        "dataset_range_end": (report.dataset_range_end),
        "stopped_reason": (report.stopped_reason),
    }
