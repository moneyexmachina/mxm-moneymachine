#
# MXM V1 — Product-level market data meta-orchestrator.
#
# This module is pure control-plane composition:
# - orchestrates dataset-level orchestrators in order
# - enforces a single product-level budget
# - produces a coherent product-level report
# - writes a product-level attempt envelope row
#
# Non-goals (by contract):
# - no vendor logic
# - no dataset state derivation or completeness interpretation
# - no contract universe handling (belongs to dataset orchestrators)
# - no retries (except optional exception-level wrapper, deferred)

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Literal, cast

from mxm.moneymachine.marketdata.datasets.daily_stats.store import DailyStatsStore
from mxm.moneymachine.marketdata.datasets.instrument_definition_mappings.build import (
    rebuild_instrument_definition_mappings,
)
from mxm.moneymachine.marketdata.datasets.instrument_definition_mappings.store import (
    InstrumentDefinitionMappingsStore,
)
from mxm.moneymachine.marketdata.datasets.instrument_definitions.ingest import (
    ingest_instrument_definitions,
)
from mxm.moneymachine.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.moneymachine.marketdata.datasets.ohlcv_1d.store import OHLCV1DStore
from mxm.moneymachine.marketdata.datasets.statistics_1d.store import Statistics1DStore
from mxm.moneymachine.marketdata.orchestrators.daily_stats import (
    derive_daily_stats_for_product,
)
from mxm.moneymachine.marketdata.orchestrators.ohlcv_1d import (
    ingest_ohlcv_1d_for_product,
)
from mxm.moneymachine.marketdata.orchestrators.product_marketdata_attempts_store import (
    ProductMarketdataAttemptsStore,
)
from mxm.moneymachine.marketdata.orchestrators.statistics_1d import (
    ingest_statistics_1d_for_product,
)
from mxm.moneymachine.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.moneymachine.utils.time_utils import utc_now_run_ts

Mode = Literal["bootstrap", "update"]


class StageStatus(str, Enum):
    OK = "ok"
    HALTED = "halted"
    ERROR = "error"


class ProductStatus(str, Enum):
    SUCCESS = "success"
    HALTED = "halted"
    ERROR = "error"


class ProductStopReason(str, Enum):
    BUDGET_EXHAUSTED = "budget_exhausted"
    COST_CAP = "cost_cap"
    MAX_CONTRACTS = "max_contracts"
    DOWNSTREAM_BLOCKED = "downstream_blocked"
    NO_WORK = "no_work"
    DRY_RUN_ONLY = "dry_run_only"
    ERROR = "error"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class StageEnvelope:
    """
    Control-plane view of a dataset orchestrator result.

    IMPORTANT:
    This is not dataset truth. It is a normalized view for
    product-level gating and reporting.
    """

    name: str
    status: StageStatus
    stop_reason: str | None
    cost_used_usd: float
    counts: dict[str, Any]
    raw_report: Any

    # Optional gating hint (used for mappings → ohlcv dependency)
    mapping_ready_for_ohlcv: bool | None = None


@dataclass(frozen=True)
class ProductMarketDataReport:
    product_id: str
    mode: Mode
    dry_run: bool
    reset: bool
    reset_local: bool

    cost_cap_usd: float
    cost_used_usd: float
    remaining_usd: float

    status: ProductStatus
    stop_reason: ProductStopReason

    stages: list[StageEnvelope]
    attempt_uid: str

    # Optional: high-level message for operator output/logging
    message: str | None = None


@dataclass(frozen=True)
class ProductRunContext:
    product_id: str
    mode: Mode
    dry_run: bool
    reset: bool
    reset_local: bool
    cost_cap_usd: float
    attempt_uid: str


@dataclass(frozen=True)
class ProductStageDecision:
    should_stop: bool
    status: ProductStatus
    stop_reason: ProductStopReason
    message: str | None


# -------------------------
# Public entry point
# -------------------------
def ingest_product_marketdata(
    *,
    product_id: str,
    mode: Mode,
    cost_cap_usd: float,
    stores: ProductMarketDataStores,
    client: Any,
    dry_run: bool = False,
    reset: bool = False,
    force_reset: bool = False,
    max_windows: int | None = None,
    max_contracts: int | None = None,
    run_ts_utc: str | None = None,
    allow_fallback_provenance: bool = False,
) -> ProductMarketDataReport:
    if cost_cap_usd <= 0:
        raise ValueError("cost_cap_usd must be > 0")

    attempts = stores.product_attempts
    run_ts = run_ts_utc or utc_now_run_ts()
    attempt_uid = _start_product_marketdata_attempt(
        attempts=attempts,
        product_id=product_id,
        mode=mode,
        dry_run=dry_run,
        reset=reset,
        reset_local=force_reset,
        cost_cap_usd=cost_cap_usd,
        run_ts_utc=run_ts,
    )

    context = ProductRunContext(
        product_id=product_id,
        mode=mode,
        dry_run=dry_run,
        reset=reset,
        reset_local=force_reset,
        cost_cap_usd=float(cost_cap_usd),
        attempt_uid=attempt_uid,
    )

    stages: list[StageEnvelope] = []
    remaining = float(cost_cap_usd)

    try:
        remaining, decision = _run_product_marketdata_stages(
            stores=stores,
            client=client,
            context=context,
            stages=stages,
            remaining=remaining,
            max_windows=max_windows,
            max_contracts=max_contracts,
            allow_fallback_provenance=allow_fallback_provenance,
        )

        return _finalize_attempt_and_report(
            attempts=attempts,
            attempt_uid=attempt_uid,
            product_id=product_id,
            mode=mode,
            dry_run=dry_run,
            reset=reset,
            reset_local=force_reset,
            cost_cap_usd=float(cost_cap_usd),
            stages=stages,
            remaining_usd=remaining,
            status=decision.status,
            stop_reason=decision.stop_reason,
            message=decision.message,
        )

    except Exception as e:
        _finish_product_marketdata_error_attempt(
            attempts=attempts,
            attempt_uid=attempt_uid,
            product_id=product_id,
            mode=mode,
            dry_run=dry_run,
            reset=reset,
            reset_local=force_reset,
            cost_cap_usd=cost_cap_usd,
            stages=stages,
            error=e,
        )
        raise


def _run_product_marketdata_stages(
    *,
    stores: ProductMarketDataStores,
    client: Any,
    context: ProductRunContext,
    stages: list[StageEnvelope],
    remaining: float,
    max_windows: int | None,
    max_contracts: int | None,
    allow_fallback_provenance: bool,
) -> tuple[float, ProductStageDecision]:
    remaining, decision = _run_and_gate_product_stage(
        stage=_run_stage_instrument_definitions(
            product_id=context.product_id,
            mode=context.mode,
            remaining_usd=remaining,
            stores=stores,
            client=client,
            dry_run=context.dry_run,
            reset=context.reset,
            max_windows=max_windows,
        ),
        stages=stages,
        remaining=remaining,
        stage_label="instrument_definitions",
        default_stop_reason=ProductStopReason.DOWNSTREAM_BLOCKED,
    )
    if decision.should_stop:
        return remaining, decision

    remaining, decision = _run_and_gate_product_stage(
        stage=_run_stage_instrument_definition_mappings(
            product_id=context.product_id,
            mode=context.mode,
            remaining_usd=remaining,
            stores=stores,
            dry_run=context.dry_run,
            reset=context.reset,
            max_contracts=max_contracts,
        ),
        stages=stages,
        remaining=remaining,
        stage_label="instrument_definition_mappings",
        default_stop_reason=ProductStopReason.DOWNSTREAM_BLOCKED,
    )
    if decision.should_stop:
        return remaining, decision

    mapping_decision = _mapping_ready_decision(stages[-1])
    if mapping_decision.should_stop:
        return remaining, mapping_decision

    remaining, decision = _run_and_gate_product_stage(
        stage=_run_stage_ohlcv_1d(
            product_id=context.product_id,
            mode=context.mode,
            remaining_usd=remaining,
            stores=stores,
            client=client,
            dry_run=context.dry_run,
            reset=context.reset,
            reset_local=context.reset_local,
            max_windows=max_windows,
            max_contracts=max_contracts,
        ),
        stages=stages,
        remaining=remaining,
        stage_label="ohlcv_1d",
        default_stop_reason=ProductStopReason.ERROR,
    )
    if decision.should_stop:
        return remaining, decision

    remaining, decision = _run_and_gate_product_stage(
        stage=_run_stage_statistics_1d(
            product_id=context.product_id,
            mode=context.mode,
            remaining_usd=remaining,
            stores=stores,
            client=client,
            dry_run=context.dry_run,
            reset=context.reset,
            reset_local=context.reset_local,
            max_windows=max_windows,
            max_contracts=max_contracts,
        ),
        stages=stages,
        remaining=remaining,
        stage_label="statistics_1d",
        default_stop_reason=ProductStopReason.ERROR,
    )
    if decision.should_stop:
        return remaining, decision

    remaining, decision = _run_and_gate_product_stage(
        stage=_run_stage_daily_stats(
            product_id=context.product_id,
            mode=context.mode,
            remaining_usd=remaining,
            stores=stores,
            dry_run=context.dry_run,
            reset=context.reset,
            reset_local=context.reset_local,
            max_contracts=max_contracts,
            allow_fallback_provenance=allow_fallback_provenance,
        ),
        stages=stages,
        remaining=remaining,
        stage_label="daily_stats",
        default_stop_reason=ProductStopReason.ERROR,
        gate_budget=False,
    )
    if decision.should_stop:
        return remaining, decision

    return remaining, ProductStageDecision(
        should_stop=True,
        status=ProductStatus.SUCCESS,
        stop_reason=(
            ProductStopReason.DRY_RUN_ONLY
            if context.dry_run
            else ProductStopReason.UNKNOWN
        ),
        message="completed all stages",
    )


def _run_and_gate_product_stage(
    *,
    stage: StageEnvelope,
    stages: list[StageEnvelope],
    remaining: float,
    stage_label: str,
    default_stop_reason: ProductStopReason,
    gate_budget: bool = True,
) -> tuple[float, ProductStageDecision]:
    stages.append(stage)
    remaining_after = max(0.0, remaining - stage.cost_used_usd)

    if stage.status is not StageStatus.OK:
        stop_reason = _coerce_stop_reason(stage, default=default_stop_reason)
        status = (
            ProductStatus.HALTED
            if stage.status is StageStatus.HALTED
            else ProductStatus.ERROR
        )
        return remaining_after, ProductStageDecision(
            should_stop=True,
            status=status,
            stop_reason=stop_reason,
            message=f"stopped after {stage_label}: {stage.status} ({stage.stop_reason})",
        )

    if gate_budget and remaining_after <= 0.0:
        return remaining_after, ProductStageDecision(
            should_stop=True,
            status=ProductStatus.HALTED,
            stop_reason=ProductStopReason.BUDGET_EXHAUSTED,
            message=f"budget exhausted after {stage_label}",
        )

    return remaining_after, ProductStageDecision(
        should_stop=False,
        status=ProductStatus.HALTED,
        stop_reason=ProductStopReason.UNKNOWN,
        message=None,
    )


def _mapping_ready_decision(stage: StageEnvelope) -> ProductStageDecision:
    if stage.mapping_ready_for_ohlcv is not False:
        return ProductStageDecision(
            should_stop=False,
            status=ProductStatus.HALTED,
            stop_reason=ProductStopReason.UNKNOWN,
            message=None,
        )

    return ProductStageDecision(
        should_stop=True,
        status=ProductStatus.HALTED,
        stop_reason=ProductStopReason.DOWNSTREAM_BLOCKED,
        message="ohlcv_1d blocked: mappings not ready",
    )


def _start_product_marketdata_attempt(
    *,
    attempts: ProductMarketdataAttemptsStore,
    product_id: str,
    mode: Mode,
    dry_run: bool,
    reset: bool,
    reset_local: bool,
    cost_cap_usd: float,
    run_ts_utc: str,
) -> str:
    return attempts.start_attempt(
        run_ts_utc=run_ts_utc,
        product_id=product_id,
        mode=str(mode),
        dry_run=dry_run,
        reset=reset,
        reset_local=bool(reset_local),
        cost_cap_usd=float(cost_cap_usd),
        started_at=utc_now_run_ts(),
        summary={
            "product_id": product_id,
            "mode": str(mode),
            "dry_run": dry_run,
            "reset": reset,
            "reset_local": reset_local,
            "stages": {},
        },
    )


def _finish_product_marketdata_error_attempt(
    *,
    attempts: ProductMarketdataAttemptsStore,
    attempt_uid: str,
    product_id: str,
    mode: Mode,
    dry_run: bool,
    reset: bool,
    reset_local: bool,
    cost_cap_usd: float,
    stages: list[StageEnvelope],
    error: Exception,
) -> None:
    stop_reason = ProductStopReason.ERROR
    status = ProductStatus.ERROR
    message = f"error: {type(error).__name__}: {error}"

    attempts.finish_attempt(
        attempt_uid=attempt_uid,
        status="error",
        stop_reason=stop_reason.value,
        finished_at=utc_now_run_ts(),
        cost_used_usd=_sum_costs(stages),
        remaining_usd=max(0.0, float(cost_cap_usd) - _sum_costs(stages)),
        summary=_summary_json(
            product_id=product_id,
            mode=mode,
            dry_run=dry_run,
            reset=reset,
            reset_local=reset_local,
            stages=stages,
            status=status,
            stop_reason=stop_reason,
            message=message,
        ),
        error_type=type(error).__name__,
        error_message=str(error),
    )


# -------------------------
# Stores container
# -------------------------


@dataclass(frozen=True)
class ProductMarketDataStores:
    """
    Bundle of stores required by the meta-orchestrator.

    Note:
    The dataset orchestrators each have their own required stores.
    This container exists purely to pass dependencies cleanly.
    """

    backend: SQLiteBackend
    product_attempts: ProductMarketdataAttemptsStore

    # Dataset-level stores (opaque here; passed through)
    instrument_definitions_store: InstrumentDefinitionsStore

    instrument_definition_mappings_store: InstrumentDefinitionMappingsStore
    ohlcv_1d_store: OHLCV1DStore
    statistics_1d_store: Statistics1DStore
    daily_stats_store: DailyStatsStore


# -------------------------
# Stage runners (normalize reports)
# -------------------------


def _run_stage_instrument_definitions(
    *,
    product_id: str,
    mode: Mode,
    remaining_usd: float,
    stores: ProductMarketDataStores,
    client: Any,
    dry_run: bool,
    reset: bool,
    max_windows: int | None,
) -> StageEnvelope:
    """
    Calls instrument_definitions orchestrator and normalizes its report.
    """
    _ = dry_run  # dry-run currently not supported by instrument_definitions
    report = ingest_instrument_definitions(
        store=stores.instrument_definitions_store,
        product_id=product_id,
        client=client,
        mode=mode,
        cost_cap_usd=float(remaining_usd),
        max_windows=max_windows if max_windows is not None else 3,
        reset=reset,
    )

    return _normalize_stage_report(
        name="instrument_definitions",
        report=report,
        mapping_ready_for_ohlcv=None,
    )


def _run_stage_instrument_definition_mappings(
    *,
    product_id: str,
    mode: Mode,
    remaining_usd: float,
    stores: ProductMarketDataStores,
    dry_run: bool,
    reset: bool,
    max_contracts: int | None,
) -> StageEnvelope:
    """
    Calls instrument_definition_mappings orchestrator and normalizes its report.
    """
    _ = remaining_usd  # stage has no vendor calls; budget not consumed here
    _ = dry_run  # stage is vendor-free by construction
    _ = max_contracts  # stage currently uses full refdata universe; scope controls deferred

    report = rebuild_instrument_definition_mappings(
        defs_store=stores.instrument_definitions_store,
        mappings_store=stores.instrument_definition_mappings_store,
        product_id=product_id,
        mode=mode,
        reset=reset,
    )

    mapping_ready = getattr(report, "mapping_ready_for_ohlcv", None)
    mapping_ready_bool = mapping_ready if isinstance(mapping_ready, bool) else None
    return _normalize_stage_report(
        name="instrument_definition_mappings",
        report=report,
        mapping_ready_for_ohlcv=mapping_ready_bool,
    )


def _run_stage_ohlcv_1d(
    *,
    product_id: str,
    mode: Mode,
    remaining_usd: float,
    stores: ProductMarketDataStores,
    client: Any,
    dry_run: bool,
    reset: bool,
    reset_local: bool,
    max_windows: int | None,
    max_contracts: int | None,
) -> StageEnvelope:
    _ = max_windows  # ohlcv_1d product orchestrator currently does not
    # window-slice at this level
    _ = reset  # destructive reset is not supported here;
    # keep the flag for future parity

    report = ingest_ohlcv_1d_for_product(
        backend=stores.backend,
        store=stores.ohlcv_1d_store,
        product_id=product_id,
        mode=mode,
        cost_cap_usd=float(remaining_usd),
        client=client,
        max_contracts=max_contracts,
        dry_run=dry_run,
        reset_local=reset_local,
    )
    return _normalize_stage_report(
        name="ohlcv_1d", report=report, mapping_ready_for_ohlcv=None
    )


def _run_stage_statistics_1d(
    *,
    product_id: str,
    mode: Mode,
    remaining_usd: float,
    stores: ProductMarketDataStores,
    client: Any,
    dry_run: bool,
    reset: bool,
    reset_local: bool,
    max_windows: int | None,
    max_contracts: int | None,
) -> StageEnvelope:
    _ = reset  # if destructive reset not supported at product-level for this dataset yet
    _ = max_windows  # if not used

    report = ingest_statistics_1d_for_product(
        backend=stores.backend,
        store=stores.statistics_1d_store,
        product_id=product_id,
        mode=mode,
        cost_cap_usd=float(remaining_usd),
        client=client,
        max_contracts=max_contracts,
        dry_run=dry_run,
        force_reset=reset_local,
    )
    return _normalize_stage_report(
        name="statistics_1d",
        report=report,
        mapping_ready_for_ohlcv=None,
    )


def _run_stage_daily_stats(
    *,
    product_id: str,
    mode: Mode,
    remaining_usd: float,
    stores: ProductMarketDataStores,
    dry_run: bool,
    reset: bool,
    reset_local: bool,
    max_contracts: int | None,
    allow_fallback_provenance: bool,
) -> StageEnvelope:
    _ = remaining_usd  # compute-only; no vendor calls today
    _ = reset  # destructive reset not supported (or not used) at this meta-layer

    require_source_meta = not bool(allow_fallback_provenance)

    report = derive_daily_stats_for_product(
        backend=stores.backend,
        product_id=product_id,
        mode=mode,
        stats_store=stores.statistics_1d_store,
        daily_store=stores.daily_stats_store,
        dataset_range_start=None,  # product meta-orchestrator currently not passing range hints
        dataset_range_end=None,
        max_contracts=max_contracts,
        dry_run=dry_run,
        force_reset=reset_local,
        require_source_meta=require_source_meta,
    )
    return _normalize_stage_report(
        name="daily_stats",
        report=report,
        mapping_ready_for_ohlcv=None,
    )


def _normalize_stage_report(
    *, name: str, report: Any, mapping_ready_for_ohlcv: bool | None
) -> StageEnvelope:
    """
    Normalize a dataset orchestrator report into StageEnvelope.

    Session 13 requirement:
    We will make minimal changes to dataset orchestrators so they expose a stable surface:
      - cost_used_usd (float)
      - stage_status (str or enum) in {"ok","halted","error"}
      - stop_reason (str|None)
      - counts (dict)

    Until that is done, this function is defensive.
    """
    # cost
    cost_used = float(getattr(report, "cost_used_usd", 0.0))

    # stage_status
    raw_status = (
        getattr(report, "stage_status", None) or getattr(report, "status", None) or "ok"
    )
    status = _coerce_stage_status(raw_status)

    # stop reason (optional)
    stop_reason = getattr(report, "stop_reason", None)

    # counts (optional)
    counts = _coerce_stage_counts(report)

    return StageEnvelope(
        name=name,
        status=status,
        stop_reason=str(stop_reason) if stop_reason is not None else None,
        cost_used_usd=cost_used,
        counts=counts,
        raw_report=report,
        mapping_ready_for_ohlcv=mapping_ready_for_ohlcv,
    )


def _coerce_stage_status(raw: Any) -> StageStatus:
    if isinstance(raw, StageStatus):
        return raw
    if isinstance(raw, Enum):
        raw = raw.value
    s = str(raw).lower()
    if s in ("ok", "success", "completed", "complete"):
        return StageStatus.OK
    if s in ("halted", "stopped", "blocked", "no_work"):
        return StageStatus.HALTED
    if s in ("error", "failed", "exception"):
        return StageStatus.ERROR
    return StageStatus.OK


def _coerce_stage_counts(report: Any) -> dict[str, Any]:
    raw_counts = getattr(report, "counts", None)

    if isinstance(raw_counts, dict):
        counts = cast(dict[object, object], raw_counts)
        return {str(key): value for key, value in counts.items()}

    raw_summary = getattr(report, "summary", None)

    if raw_summary is None:
        return {}

    return {"_counts": raw_summary}


def _coerce_stop_reason(
    stage: StageEnvelope, *, default: ProductStopReason
) -> ProductStopReason:
    # If stage provides a stop_reason that matches product stop reasons, use it.
    if stage.stop_reason:
        s = stage.stop_reason.lower().strip()
        for r in ProductStopReason:
            if s == r.value:
                return r
        # Common mappings
        if s in ("budget", "budget_exhausted"):
            return ProductStopReason.BUDGET_EXHAUSTED
        if s in ("blocked", "downstream_blocked"):
            return ProductStopReason.DOWNSTREAM_BLOCKED
        if s in ("dry_run", "dry_run_only"):
            return ProductStopReason.DRY_RUN_ONLY
        if s in ("no_work",):
            return ProductStopReason.NO_WORK
        if s in ("error", "failed"):
            return ProductStopReason.ERROR
    return default


def _finalize_attempt_and_report(
    *,
    attempts: ProductMarketdataAttemptsStore,
    attempt_uid: str,
    product_id: str,
    mode: Mode,
    dry_run: bool,
    reset: bool,
    reset_local: bool,
    cost_cap_usd: float,
    stages: list[StageEnvelope],
    remaining_usd: float,
    status: ProductStatus,
    stop_reason: ProductStopReason,
    message: str | None,
) -> ProductMarketDataReport:
    finished_at = utc_now_run_ts()
    cost_used = _sum_costs(stages)

    attempts.finish_attempt(
        attempt_uid=attempt_uid,
        status=status.value,
        stop_reason=stop_reason.value,
        finished_at=finished_at,
        cost_used_usd=cost_used,
        remaining_usd=float(remaining_usd),
        summary=_summary_json(
            product_id=product_id,
            mode=mode,
            dry_run=dry_run,
            reset=reset,
            reset_local=reset_local,
            stages=stages,
            status=status,
            stop_reason=stop_reason,
            message=message,
        ),
    )

    return ProductMarketDataReport(
        product_id=product_id,
        mode=mode,
        dry_run=dry_run,
        reset=reset,
        reset_local=reset_local,
        cost_cap_usd=float(cost_cap_usd),
        cost_used_usd=cost_used,
        remaining_usd=float(remaining_usd),
        status=status,
        stop_reason=stop_reason,
        stages=stages,
        attempt_uid=attempt_uid,
        message=message,
    )


def _summary_json(
    *,
    product_id: str,
    mode: Mode,
    dry_run: bool,
    reset: bool,
    reset_local: bool,
    stages: list[StageEnvelope],
    status: ProductStatus,
    stop_reason: ProductStopReason,
    message: str | None,
) -> dict[str, Any]:
    stage_map: dict[str, Any] = {}
    for s in stages:
        stage_map[s.name] = {
            "status": s.status.value,
            "stop_reason": s.stop_reason,
            "cost_used_usd": s.cost_used_usd,
            "counts": s.counts,
        }
        if s.mapping_ready_for_ohlcv is not None:
            stage_map[s.name]["mapping_ready_for_ohlcv"] = s.mapping_ready_for_ohlcv

    return {
        "product_id": product_id,
        "mode": str(mode),
        "dry_run": dry_run,
        "reset": reset,
        "reset_local": reset_local,
        "status": status.value,
        "stop_reason": stop_reason.value,
        "message": message,
        "stages": stage_map,
    }


def _sum_costs(stages: list[StageEnvelope]) -> float:
    return float(sum(s.cost_used_usd for s in stages))
