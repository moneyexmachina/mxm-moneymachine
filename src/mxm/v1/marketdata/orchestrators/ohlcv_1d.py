from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any, Literal

import pandas as pd
from mxm_refdata.api.ref_data_api import RefDataAPI  # type: ignore
from mxm_refdata.models.contracts.futures_contract import (
    FuturesContract,  # type: ignore
)

from mxm.v1.marketdata.datasets.instrument_definitions.api import (
    get_watermark_for_product,
    read_lifecycle_for_product_instrument,
)
from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.api import (
    contract_window_utc_half_open,
    is_complete_level0,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import (  # S12.1
    CoverageSnapshot,
    OHLCV1DAttemptsStore,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.expected import derive_expected_window
from mxm.v1.marketdata.datasets.ohlcv_1d.state import (
    BudgetContext,
    RetryPolicy,
    decide_action,
    derive_state,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.store import OHLCV1DStore
from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    DatabentoInstrumentIdentity,
    contract_year_month,
    resolve_databento_instrument,
)
from mxm.v1.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.marketdata.vendors.databento.cost import (
    estimate_cost_ohlcv_1d,
)
from mxm.v1.marketdata.vendors.databento.dataset_range import get_dataset_range
from mxm.v1.marketdata.vendors.databento.normalize.ohlcv_1d import normalize_ohlcv_1d
from mxm.v1.marketdata.vendors.databento.pull import pull_ohlcv_1d_by_instrument_id

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
    status: str  # complete | ingested | unmapped | skipped_cost_cap | dry_run | incomplete | error
    vendor_start: str | None = None
    vendor_end: str | None = None
    vendor_final: bool = False
    cost_usd: float = 0.0
    bars_path: str | None = None


@dataclass
class OHLCV1DOrchestratorReport:
    product_id: str
    mode: Mode
    ts_utc: str

    gates: list[GateResult] = field(default_factory=list)

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
    runs: list[ContractRun] = field(default_factory=list)

    stopped_reason: str = ""  # ok | cost_cap | max_contracts

    # Meta-orchestrator fields:
    counts: dict[str, Any] = field(default_factory=dict)
    cost_used_usd: float = 0.0
    stage_status: str = ""
    stop_reason: str = ""


def _utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _contract_key(c: FuturesContract) -> str:
    y, m = contract_year_month(c)
    return f"{c.product_id}:{y:04d}-{m:02d}"


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
        w_start = (
            w.start.tz_convert("UTC") if w.start.tzinfo else w.start.tz_localize("UTC")
        )
        w_end = w.end.tz_convert("UTC") if w.end.tzinfo else w.end.tz_localize("UTC")

        # overlap between [w_start, w_end) and [dataset_start, dataset_end)
        if w_end <= dataset_start or w_start >= dataset_end:
            excluded += 1
            continue

        eligible.append(c)

    return eligible, excluded


def _gate_definitions_available(
    *,
    backend: SQLiteBackend,
    product_id: str,
) -> GateResult:
    """
    Minimal gate: definitions watermark exists for the product's feed.
    This does NOT ensure “up-to-date”; it ensures the dataset is present at all.
    """
    store = InstrumentDefinitionsStore(backend=backend)
    wm = get_watermark_for_product(store=store, product_id=product_id)

    if wm is None:
        return GateResult(
            name="instrument_definitions_watermark_exists",
            ok=False,
            detail=f"missing watermark for product_id={product_id}",
        )

    return GateResult(
        name="instrument_definitions_watermark_exists",
        ok=True,
        detail=f"watermark={wm}",
    )


def _enumerate_contracts(product_id: str, *, mode: Mode) -> list[FuturesContract]:
    """
    Deterministic enumeration of refdata contracts.

    For now:
      - bootstrap: all contracts for product
      - update: contracts whose last_trading_day is within a recent horizon
               (simple, conservative; avoids reprocessing deep history)
    """
    api = RefDataAPI()
    contracts = list(api.get_contracts_for_product(product_id))

    # Deterministic ordering
    contracts.sort(key=lambda c: (*contract_year_month(c), str(c.contract_id)))

    if mode == "bootstrap":
        return contracts

    today = date.today()
    cutoff = today.replace(year=today.year - 1)
    return [c for c in contracts if c.last_trading_day >= cutoff]


def _to_ts_utc(x: str) -> pd.Timestamp:
    ts = pd.Timestamp(x)
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _fmt_ts_utc(ts: pd.Timestamp) -> str:
    """
    Keep consistent with attempts_store formatting: UTC ISO8601Z, second resolution.
    """
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _cov_snapshot(cov) -> CoverageSnapshot:
    """
    Adapter for OHLCV1DStore.scan_coverage(...) return.
    Expected attributes:
      - min_ts, max_ts, row_count, bars_path
    """
    return CoverageSnapshot(
        min_ts=getattr(cov, "min_ts", None),
        max_ts=getattr(cov, "max_ts", None),
        row_count=int(getattr(cov, "row_count", 0)),
        bars_path=(
            str(getattr(cov, "bars_path"))
            if getattr(cov, "bars_path", None) is not None
            else None
        ),
    )


def ingest_ohlcv_1d_for_product(
    *,
    backend: SQLiteBackend,
    store: OHLCV1DStore,
    product_id: str,
    mode: Mode,
    cost_cap_usd: float,
    client,  # databento.Historical; untyped to avoid hard dependency
    max_contracts: int | None = None,
    dry_run: bool = False,
    reset_local: bool = False,
) -> OHLCV1DOrchestratorReport:
    """
    Orchestrate ohlcv-1d persistence for a product_id.

    Hard boundaries:
    - No instrument_definitions ingest.
    - No instrument_definition_mappings rebuild.
    - Uses mapping table only to resolve contract -> instrument identity.

    Completeness:
    - Level 0, half-open windows as defined in datasets/ohlcv_1d/api.py.

    S12.1:
    - Record exactly one ohlcv_1d_attempts row per contract considered.

    S12.2:
    - Derive per-contract DerivedState + Decision (noop/attempt_ingest/stop_run),
      then execute decision and record attempt row.
    """
    if cost_cap_usd <= 0:
        raise ValueError("cost_cap_usd must be > 0")

    report = OHLCV1DOrchestratorReport(
        product_id=product_id,
        mode=mode,
        ts_utc=_utc_now_iso_z(),
        cost_cap_usd=float(cost_cap_usd),
        cost_usd_total=0.0,
        stopped_reason="",
    )

    attempts_store = OHLCV1DAttemptsStore(backend=backend)
    retry_policy = RetryPolicy(
        max_consecutive_errors=3,
        stop_run_on_systemic_error=True,
    )

    # -------------------------
    # Gates (read-only)
    # -------------------------
    g_defs = _gate_definitions_available(backend=backend, product_id=product_id)
    report.gates.append(g_defs)
    if not g_defs.ok:
        raise RuntimeError(
            "ohlcv_1d orchestrator gate failed: instrument_definitions not present. "
            "Run ops/instrument_definitions.py first."
        )

    root = get_databento_product_root(product_id)
    avail = get_dataset_range(
        client=client,
        dataset=root.dataset,
        schema="ohlcv-1d",
    )
    report.dataset_range_start = avail.start
    report.dataset_range_end = avail.end

    report.gates.append(
        GateResult(
            name="databento_dataset_range_ohlcv_1d",
            ok=True,
            detail=f"start={avail.start} end={avail.end} (end exclusive)",
        )
    )

    defs_store = InstrumentDefinitionsStore(backend=backend)

    avail_start_ts = _to_ts_utc(avail.start)
    avail_end_ts = _to_ts_utc(avail.end)

    # -------------------------
    # Contract enumeration + eligibility filter
    # -------------------------
    contracts_all = _enumerate_contracts(product_id, mode=mode)
    eligible, excluded = _subset_eligible_contracts(
        contracts_all=contracts_all,
        dataset_start=avail_start_ts,
        dataset_end=avail_end_ts,
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

    remaining = float(cost_cap_usd)

    # -------------------------
    # Main loop
    # -------------------------
    for c in contracts:
        # ---- per-contract attempt context (filled progressively) ----
        ident: DatabentoInstrumentIdentity | None = None
        ew = None

        cov_before: CoverageSnapshot | None = None
        cov_after: CoverageSnapshot | None = None

        status: str | None = None
        status_detail: str | None = None

        cost_estimated_usd: float | None = None
        cost_used_usd: float | None = None
        cost_charged_usd: float | None = None

        error_type: str | None = None
        error_message: str | None = None

        should_break_after = False  # stop after recording attempt row

        # For report surface fields
        interest_start_s: str | None = None
        interest_end_s: str | None = None
        exp_start_s: str | None = None
        exp_end_s: str | None = None

        # For state/decision
        latest_attempt = None
        decision = None
        derived_state = None

        # Track “complete now” for mapping to ledger/report
        is_complete_now: bool | None = None

        try:
            # 1) Interest window (baseline surfaces)
            window = contract_window_utc_half_open(
                start_date=c.first_day_of_interest,
                end_date_inclusive=c.last_trading_day,
            )
            w_start = (
                window.start.tz_convert("UTC")
                if window.start.tzinfo
                else window.start.tz_localize("UTC")
            )
            w_end = (
                window.end.tz_convert("UTC")
                if window.end.tzinfo
                else window.end.tz_localize("UTC")
            )
            interest_start_s = _fmt_ts_utc(w_start)
            interest_end_s = _fmt_ts_utc(w_end)

            # 2) Resolve mapping
            try:
                ident = resolve_databento_instrument(backend, c)
                report.contracts_mapped += 1
            except Exception as e:
                # Still produce ew (no lifecycle bounds available)
                ew = derive_expected_window(
                    product_id=product_id,
                    contract_id=str(c.contract_id),
                    first_day_of_interest=c.first_day_of_interest,
                    last_trading_day=c.last_trading_day,
                    dataset_start=avail_start_ts,
                    dataset_end=avail_end_ts,
                    activation=None,
                    expiration=None,
                )
                exp_start_s = _fmt_ts_utc(ew.expected_start)
                exp_end_s = _fmt_ts_utc(ew.expected_end)
                interest_start_s = _fmt_ts_utc(ew.interest_start)
                interest_end_s = _fmt_ts_utc(ew.interest_end)

                status = "unmapped"
                status_detail = f"mapping_failed:{type(e).__name__}"
                continue

            # 3) Lifecycle bounds (from instrument_definitions)
            lifecycle = read_lifecycle_for_product_instrument(
                store=defs_store,
                product_id=product_id,
                publisher_id=ident.publisher_id,
                instrument_id=ident.instrument_id,
            )
            activation_ns, expiration_ns = (
                lifecycle if lifecycle is not None else (None, None)
            )

            # 4) Strong expected window
            ew = derive_expected_window(
                product_id=product_id,
                contract_id=str(c.contract_id),
                first_day_of_interest=c.first_day_of_interest,
                last_trading_day=c.last_trading_day,
                dataset_start=avail_start_ts,
                dataset_end=avail_end_ts,
                activation=activation_ns,
                expiration=expiration_ns,
            )
            exp_start_s = _fmt_ts_utc(ew.expected_start)
            exp_end_s = _fmt_ts_utc(ew.expected_end)
            interest_start_s = _fmt_ts_utc(ew.interest_start)
            interest_end_s = _fmt_ts_utc(ew.interest_end)

            # Fetch latest attempt (used for retry/systemic error policy)
            latest_attempt = attempts_store.get_latest_attempt_for_contract(
                product_id=product_id,
                contract_id=str(c.contract_id),
            )

            # If expected is empty, decision is trivially noop; still record attempt
            if ew.is_empty:
                status = "skipped_empty_expected_window"
                status_detail = "expected_window_empty"
                continue

            # 5) Optional local reset for this identity (parquet only)
            # Note: this remains a run-level knob for now.
            if reset_local and not dry_run:
                store.delete(
                    dataset=ident.dataset,
                    publisher_id=ident.publisher_id,
                    instrument_id=ident.instrument_id,
                )

            # 6) Coverage now (pre-decision surface)
            if reset_local and dry_run:
                # simulate reset without deleting on disk
                cov0 = CoverageSnapshot(min_ts=None, max_ts=None, row_count=0)
            else:
                cov0 = store.scan_coverage(
                    dataset=ident.dataset,
                    publisher_id=ident.publisher_id,
                    instrument_id=ident.instrument_id,
                )
            cov_before = _cov_snapshot(cov0)

            is_complete_now = is_complete_level0(
                stored_min=cov0.min_ts,
                stored_max=cov0.max_ts,
                row_count=cov0.row_count,
                target_start=ew.expected_start,
                target_end=ew.expected_end,
            )

            # Derived state + decision
            derived_state = derive_state(
                latest_attempt=latest_attempt,
                ew=ew,
                coverage_now=cov_before,
                is_mapped=True,
                reset_local=reset_local,
            )
            decision = decide_action(
                state=derived_state,
                policy=retry_policy,
                budgets=BudgetContext(remaining_usd=float(remaining)),
                latest_attempt=latest_attempt,
            )

            # Dry-run overrides: never vendor-call; record as dry_run regardless
            if dry_run:
                status = "dry_run"
                status_detail = f"dry_run_decision={decision.action}"
                continue
            # Map decision/state to ledger status for noop paths
            if decision.action == "noop":
                if derived_state.value == "done":
                    # DONE may be complete or vendor_final partial.
                    if is_complete_now:
                        report.complete_before += 1
                        status = "complete"
                        status_detail = "already_complete"
                    else:
                        # Vendor-final partial “done” (explicitly tagged)
                        status = "complete"
                        status_detail = "vendor_final_partial_done"
                elif derived_state.value == "blocked_unmapped":
                    status = "unmapped"
                    status_detail = "blocked_unmapped"
                elif derived_state.value == "blocked_empty_expected":
                    status = "skipped_empty_expected_window"
                    status_detail = "expected_window_empty"
                elif derived_state.value == "skipped_budget":
                    status = "skipped_cost_cap"
                    status_detail = "skipped_budget"
                else:
                    # Includes "final_error" and other noop-returning states
                    status = "dry_run" if dry_run else "complete"
                    status_detail = decision.reason
                continue

            if decision.action == "stop_run":
                status = "error"
                status_detail = f"stop_run:{decision.reason}"
                report.stopped_reason = "stop_run"
                should_break_after = True
                continue

            # decision.action == "attempt_ingest"
            # Budget hard stop: no remaining budget means stop run (after recording attempt)
            if remaining <= 0:
                status = "skipped_cost_cap"
                status_detail = "cost_cap_reached"
                report.stopped_reason = "cost_cap"
                should_break_after = True
                continue

            # -------------------------
            # Vendor call + normalise + persist
            # -------------------------
            est = estimate_cost_ohlcv_1d(
                client=client,
                dataset=ident.dataset,
                symbols=str(ident.instrument_id),
                stype_in="instrument_id",
                start=exp_start_s,
                end=exp_end_s,
            )
            cost_estimated_usd = float(est.estimated_cost_usd)

            # Budget gate: insufficient remaining for this contract is a normal skip, not an error.
            # Do NOT break: later contracts may be cheaper.
            if cost_estimated_usd > remaining:
                status = "skipped_cost_cap"
                status_detail = "estimate_exceeds_remaining"
                continue

            df_raw = pull_ohlcv_1d_by_instrument_id(
                dataset=ident.dataset,
                instrument_id=ident.instrument_id,
                start=exp_start_s,
                end=exp_end_s,
                source="databento",
            )
            df = normalize_ohlcv_1d(
                df_raw, dataset=ident.dataset, raw_symbol=ident.raw_symbol
            )

            store.write(
                dataset=ident.dataset,
                publisher_id=ident.publisher_id,
                instrument_id=ident.instrument_id,
                df_new=df,
            )

            # MVP: treat estimate as used/charged
            cost_used_usd = cost_estimated_usd
            cost_charged_usd = cost_estimated_usd

            report.cost_usd_total += cost_used_usd
            remaining -= cost_used_usd

            cov1 = store.scan_coverage(
                dataset=ident.dataset,
                publisher_id=ident.publisher_id,
                instrument_id=ident.instrument_id,
            )
            cov_after = _cov_snapshot(cov1)

            complete_after = is_complete_level0(
                stored_min=cov1.min_ts,
                stored_max=cov1.max_ts,
                row_count=cov1.row_count,
                target_start=ew.expected_start,
                target_end=ew.expected_end,
            )

            if complete_after:
                status = "ingested"
                status_detail = "ingested_complete"
                report.completed_this_run += 1
            elif ew.vendor_final:
                status = "ingested"
                status_detail = "vendor_final_partial_done"
                report.completed_this_run += 1
            else:
                status = "incomplete"
                status_detail = "incomplete_after_ingest"

        except Exception as e:
            status = "error"
            status_detail = "exception"
            error_type = type(e).__name__
            error_message = str(e)[:500]

        finally:
            # Ensure ew always exists (ledger invariant)
            if ew is None:
                ew = derive_expected_window(
                    product_id=product_id,
                    contract_id=str(c.contract_id),
                    first_day_of_interest=c.first_day_of_interest,
                    last_trading_day=c.last_trading_day,
                    dataset_start=avail_start_ts,
                    dataset_end=avail_end_ts,
                    activation=None,
                    expiration=None,
                )
                exp_start_s = _fmt_ts_utc(ew.expected_start)
                exp_end_s = _fmt_ts_utc(ew.expected_end)
                interest_start_s = _fmt_ts_utc(ew.interest_start)
                interest_end_s = _fmt_ts_utc(ew.interest_end)

            # Record attempt row (exactly once per contract considered)
            attempts_store.record_attempt(
                run_ts_utc=report.ts_utc,
                mode=mode,
                dry_run=bool(dry_run),
                reset_local=bool(reset_local),
                cost_cap_usd=float(cost_cap_usd),
                product_id=product_id,
                contract_id=str(c.contract_id),
                contract_key=_contract_key(c),
                feed=getattr(ident, "feed", None) if ident else None,
                dataset=getattr(ident, "dataset", None) if ident else None,
                publisher_id=getattr(ident, "publisher_id", None) if ident else None,
                instrument_id=getattr(ident, "instrument_id", None) if ident else None,
                raw_symbol=getattr(ident, "raw_symbol", None) if ident else None,
                ew=ew,
                status=(status or "error"),
                status_detail=status_detail,
                cost_estimated_usd=cost_estimated_usd,
                cost_used_usd=cost_used_usd,
                cost_charged_usd=cost_charged_usd,
                coverage_before=cov_before,
                coverage_after=cov_after,
                error_type=error_type,
                error_message=error_message,
            )

            # Emit report row (prefer after coverage if present)
            cov_for_report = cov_after or cov_before
            stored_min = (
                _fmt_ts_utc(cov_for_report.min_ts)
                if cov_for_report and cov_for_report.min_ts is not None
                else None
            )
            stored_max = (
                _fmt_ts_utc(cov_for_report.max_ts)
                if cov_for_report and cov_for_report.max_ts is not None
                else None
            )
            stored_rows = int(cov_for_report.row_count) if cov_for_report else 0
            bars_path = cov_for_report.bars_path if cov_for_report else None

            report.runs.append(
                ContractRun(
                    contract_id=str(c.contract_id),
                    contract_key=_contract_key(c),
                    target_start=interest_start_s or _fmt_ts_utc(ew.interest_start),
                    target_end=interest_end_s or _fmt_ts_utc(ew.interest_end),
                    vendor_start=exp_start_s,
                    vendor_end=exp_end_s,
                    vendor_final=bool(getattr(ew, "vendor_final", False)),
                    stored_min=stored_min,
                    stored_max=stored_max,
                    stored_rows=stored_rows,
                    status=(status or "error"),
                    cost_usd=float(cost_used_usd or 0.0),
                    bars_path=bars_path,
                )
            )

        if should_break_after:
            break

    report.incomplete_remaining = sum(
        1
        for r in report.runs
        if r.status in ("incomplete", "dry_run", "skipped_cost_cap", "error")
    )

    if report.stopped_reason == "":
        report.stopped_reason = "ok"
    # --- meta-orchestrator surface (Session 13) ---
    report.cost_used_usd = float(report.cost_usd_total)
    report.stop_reason = report.stopped_reason

    if report.stopped_reason == "ok":
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
        "runs": int(len(report.runs)),
        "dataset_range_start": report.dataset_range_start,
        "dataset_range_end": report.dataset_range_end,
        "stopped_reason": report.stopped_reason,
    }
    return report
