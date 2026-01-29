# mxm/v1/marketdata/orchestrators/product_marketdata.py
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
from typing import Any, Literal

from mxm.v1.marketdata.datasets.instrument_definition_mappings.store import (
    InstrumentDefinitionMappingsStore,
)
from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.store import OHLCV1DStore
from mxm.v1.marketdata.orchestrators.instrument_definition_mappings import (
    rebuild_instrument_definition_mappings,
)
from mxm.v1.marketdata.orchestrators.instrument_definitions import (
    ingest_instrument_definitions,
)
from mxm.v1.marketdata.orchestrators.ohlcv_1d import ingest_ohlcv_1d_for_product
from mxm.v1.marketdata.orchestrators.product_marketdata_attempts_store import (
    ProductMarketdataAttemptsStore,
)
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.marketdata.time_utils import utc_now_run_ts

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


# -------------------------
# Public entry point
# -------------------------


def ingest_product_marketdata(
    *,
    product_id: str,
    mode: Mode,
    cost_cap_usd: float,
    stores: ProductMarketDataStores,
    client: Any,  # databento.Historical; keep untyped to avoid hard dependency
    dry_run: bool = False,
    reset: bool = False,
    reset_local: bool = False,
    max_windows: int | None = None,
    max_contracts: int | None = None,
    run_ts_utc: str | None = None,
) -> ProductMarketDataReport:
    """
    Orchestrate end-to-end product ingestion:

      1) instrument_definitions
      2) instrument_definition_mappings
      3) ohlcv_1d

    Control-plane only:
    - budget propagation
    - stage gating
    - product-level attempt envelope
    """

    if cost_cap_usd <= 0:
        raise ValueError("cost_cap_usd must be > 0")

    # We prefer caller-provided run_ts_utc for reproducible logs; otherwise store uses started_at.
    # In most MXM orchestrators, you already have a now_utc_iso() helper; wire it here.
    ts_now = utc_now_run_ts()
    run_ts = run_ts_utc or ts_now

    attempts = stores.product_attempts

    attempt_uid = attempts.start_attempt(
        run_ts_utc=run_ts,
        product_id=product_id,
        mode=str(mode),
        dry_run=dry_run,
        reset=reset,
        reset_local=reset_local,
        cost_cap_usd=float(cost_cap_usd),
        started_at=ts_now,
        summary={
            "product_id": product_id,
            "mode": str(mode),
            "dry_run": dry_run,
            "reset": reset,
            "reset_local": reset_local,
            "stages": {},
        },
    )

    remaining = float(cost_cap_usd)
    stages: list[StageEnvelope] = []
    stop_reason: ProductStopReason = ProductStopReason.UNKNOWN
    status: ProductStatus = ProductStatus.HALTED
    message: str | None = None

    try:
        # -------------------------
        # Stage 1: instrument_definitions
        # -------------------------
        st1 = _run_stage_instrument_definitions(
            product_id=product_id,
            mode=mode,
            remaining_usd=remaining,
            stores=stores,
            client=client,
            dry_run=dry_run,
            reset=reset,
            max_windows=max_windows,
        )
        stages.append(st1)
        remaining = max(0.0, remaining - st1.cost_used_usd)

        if st1.status is not StageStatus.OK:
            stop_reason = _coerce_stop_reason(
                st1, default=ProductStopReason.DOWNSTREAM_BLOCKED
            )
            status = (
                ProductStatus.HALTED
                if st1.status is StageStatus.HALTED
                else ProductStatus.ERROR
            )
            message = f"stopped after instrument_definitions: {st1.status} ({st1.stop_reason})"
            return _finalize_attempt_and_report(
                attempts=attempts,
                attempt_uid=attempt_uid,
                product_id=product_id,
                mode=mode,
                dry_run=dry_run,
                reset=reset,
                reset_local=reset_local,
                cost_cap_usd=float(cost_cap_usd),
                stages=stages,
                remaining_usd=remaining,
                status=status,
                stop_reason=stop_reason,
                message=message,
            )

        if remaining <= 0.0:
            stop_reason = ProductStopReason.BUDGET_EXHAUSTED
            status = ProductStatus.HALTED
            message = "budget exhausted after instrument_definitions"
            return _finalize_attempt_and_report(
                attempts=attempts,
                attempt_uid=attempt_uid,
                product_id=product_id,
                mode=mode,
                dry_run=dry_run,
                reset=reset,
                reset_local=reset_local,
                cost_cap_usd=float(cost_cap_usd),
                stages=stages,
                remaining_usd=remaining,
                status=status,
                stop_reason=stop_reason,
                message=message,
            )

        # -------------------------
        # Stage 2: instrument_definition_mappings
        # -------------------------
        st2 = _run_stage_instrument_definition_mappings(
            product_id=product_id,
            mode=mode,
            remaining_usd=remaining,
            stores=stores,
            dry_run=dry_run,
            reset=reset,
            max_contracts=max_contracts,
        )
        stages.append(st2)
        remaining = max(0.0, remaining - st2.cost_used_usd)

        if st2.status is not StageStatus.OK:
            stop_reason = _coerce_stop_reason(
                st2, default=ProductStopReason.DOWNSTREAM_BLOCKED
            )
            status = (
                ProductStatus.HALTED
                if st2.status is StageStatus.HALTED
                else ProductStatus.ERROR
            )
            message = f"stopped after instrument_definition_mappings: {st2.status} ({st2.stop_reason})"
            return _finalize_attempt_and_report(
                attempts=attempts,
                attempt_uid=attempt_uid,
                product_id=product_id,
                mode=mode,
                dry_run=dry_run,
                reset=reset,
                reset_local=reset_local,
                cost_cap_usd=float(cost_cap_usd),
                stages=stages,
                remaining_usd=remaining,
                status=status,
                stop_reason=stop_reason,
                message=message,
            )

        # Gate: mappings must declare ready for ohlcv
        if st2.mapping_ready_for_ohlcv is False:
            stop_reason = ProductStopReason.DOWNSTREAM_BLOCKED
            status = ProductStatus.HALTED
            message = "ohlcv_1d blocked: mappings not ready"
            return _finalize_attempt_and_report(
                attempts=attempts,
                attempt_uid=attempt_uid,
                product_id=product_id,
                mode=mode,
                dry_run=dry_run,
                reset=reset,
                reset_local=reset_local,
                cost_cap_usd=float(cost_cap_usd),
                stages=stages,
                remaining_usd=remaining,
                status=status,
                stop_reason=stop_reason,
                message=message,
            )

        if remaining <= 0.0:
            stop_reason = ProductStopReason.BUDGET_EXHAUSTED
            status = ProductStatus.HALTED
            message = "budget exhausted after instrument_definition_mappings"
            return _finalize_attempt_and_report(
                attempts=attempts,
                attempt_uid=attempt_uid,
                product_id=product_id,
                mode=mode,
                dry_run=dry_run,
                reset=reset,
                reset_local=reset_local,
                cost_cap_usd=float(cost_cap_usd),
                stages=stages,
                remaining_usd=remaining,
                status=status,
                stop_reason=stop_reason,
                message=message,
            )

        # -------------------------
        # Stage 3: ohlcv_1d
        # -------------------------
        st3 = _run_stage_ohlcv_1d(
            product_id=product_id,
            mode=mode,
            remaining_usd=remaining,
            stores=stores,
            client=client,
            dry_run=dry_run,
            reset=reset,
            reset_local=reset_local,
            max_windows=max_windows,
            max_contracts=max_contracts,
        )
        stages.append(st3)
        remaining = max(0.0, remaining - st3.cost_used_usd)

        # If ohlcv stage says "no work", meta-orchestrator may consider overall NO_WORK on update.
        if st3.status is StageStatus.OK:
            stop_reason = (
                ProductStopReason.DRY_RUN_ONLY if dry_run else ProductStopReason.UNKNOWN
            )
            status = ProductStatus.SUCCESS
            message = "completed all stages"
        else:
            stop_reason = _coerce_stop_reason(st3, default=ProductStopReason.ERROR)
            status = (
                ProductStatus.HALTED
                if st3.status is StageStatus.HALTED
                else ProductStatus.ERROR
            )
            message = f"stopped after ohlcv_1d: {st3.status} ({st3.stop_reason})"

        return _finalize_attempt_and_report(
            attempts=attempts,
            attempt_uid=attempt_uid,
            product_id=product_id,
            mode=mode,
            dry_run=dry_run,
            reset=reset,
            reset_local=reset_local,
            cost_cap_usd=float(cost_cap_usd),
            stages=stages,
            remaining_usd=remaining,
            status=status,
            stop_reason=stop_reason,
            message=message,
        )

    except Exception as e:
        # Terminalize attempt as error and re-raise.
        stop_reason = ProductStopReason.ERROR
        status = ProductStatus.ERROR
        message = f"error: {type(e).__name__}: {e}"

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
            error_type=type(e).__name__,
            error_message=str(e),
        )
        raise


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
    counts = getattr(report, "counts", None)
    if counts is None:
        # attempt common alternatives
        counts = getattr(report, "summary", None) or {}
    if not isinstance(counts, dict):
        counts = {"_counts": counts}

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
