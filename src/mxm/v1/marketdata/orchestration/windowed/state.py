from __future__ import annotations

"""
Generic state derivation and decision logic for windowed datasets.

This module encodes the shared MXM V1 windowed-dataset orchestration semantics:

- Blockers dominate (unmapped, empty expected, missing universe, etc.).
- Completeness dominates ingestion (complete / vacuous / acceptable-final => DONE).
- Attempt outcomes are consulted after coverage/completeness for budget/error gating.
- Budget is a hard gate for initiating a vendor-facing attempt.
- Systemic errors can stop the run (conservative MVP classification).

This module is pure:
- no I/O
- no dependency on dataset/store/vendor modules
- deterministic given its inputs

Dataset-specific code is responsible for producing the evidence inputs:
- block_reason (if any)
- completeness verdict
- latest attempt outcome (if any)
"""

from dataclasses import dataclass

from mxm.v1.marketdata.orchestration.types import (
    AttemptOutcome,
    AttemptStatus,
    BlockedReason,
    BudgetContext,
    CompletenessVerdict,
    Decision,
    DerivedState,
    ErrorClass,
    RetryPolicy,
)

# ---------------------------------------------------------------------------
# Evidence model (optional convenience wrapper)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowedEvidence:
    """
    Minimal evidence bundle used for state derivation.

    Datasets may compute evidence in richer ways, but orchestration should reduce
    it to this minimal shared form.
    """

    block_reason: BlockedReason | None
    completeness: CompletenessVerdict
    latest_outcome: AttemptOutcome | None


# ---------------------------------------------------------------------------
# Systemic error classification (MVP, conservative)
# ---------------------------------------------------------------------------


def is_systemic_error(
    *,
    error_class: ErrorClass | None,
    error_type: str | None,
    error_message: str | None,
) -> bool:
    """
    Conservative classifier for systemic errors.

    The goal is to stop the run when continuing is unlikely to help and may
    spam attempts or waste budget.

    This is intentionally heuristic and should be refined over time.
    """
    if error_class == "systemic":
        return True

    t = (error_type or "").lower()
    m = (error_message or "").lower()

    # Authentication / permission failures
    if "authentication" in m or "permission" in m or "unauthorized" in m:
        return True
    if "forbidden" in m or "invalid api key" in m or "api key" in m and "invalid" in m:
        return True

    # Schema / migration / structural issues
    if "no such table" in m or "migration" in m:
        return True
    if "schema" in m and "error" in m:
        return True

    # Non-transient operational errors (sqlite locked is transient)
    if "operationalerror" in t and "locked" not in m:
        return True

    return False


def consecutive_error_count(latest_outcome: AttemptOutcome | None) -> int:
    """
    MVP approximation: only considers the latest outcome.

    If you later add queries for multiple recent attempts per scope/window,
    this function can become exact.
    """
    if latest_outcome is None:
        return 0
    return 1 if latest_outcome.status == AttemptStatus.ERROR else 0


# ---------------------------------------------------------------------------
# State derivation
# ---------------------------------------------------------------------------


def derive_state(
    *,
    evidence: WindowedEvidence,
    reset_local: bool,
) -> DerivedState:
    """
    Derive the coarse orchestration state for a windowed dataset scope/window.

    Precedence order (normative):
      1) Blockers
      2) Empty/vacuous expectedness (via completeness verdict)
      3) Completeness (complete / acceptable-final => DONE)
      4) Operator override (reset_local forces ingest unless blocked/vacuous)
      5) Attempt outcome signals (budget skipped, retryable error)
      6) Default => NEEDS_INGEST
    """
    # 1) Blockers dominate
    if evidence.block_reason is not None:
        return DerivedState.BLOCKED

    # 2) Vacuous expectedness => DONE
    if evidence.completeness == CompletenessVerdict.VACUOUS:
        return DerivedState.DONE

    # 3) Completeness dominates
    if evidence.completeness in (
        CompletenessVerdict.COMPLETE,
        CompletenessVerdict.ACCEPTABLE_PARTIAL_FINAL,
    ):
        return DerivedState.DONE

    # 4) Operator override: force ingest (unless blocked/vacuous already handled)
    if reset_local:
        return DerivedState.NEEDS_INGEST

    # 5) Attempt-based signals
    lo = evidence.latest_outcome
    if lo is not None:
        # Budget skip from a previous attempt
        if lo.status == AttemptStatus.SKIPPED and lo.status_detail in (
            "skipped_budget",
            "skipped_cost_cap",
        ):
            return DerivedState.SKIPPED_BUDGET

        # Retryable error
        if lo.status == AttemptStatus.ERROR:
            return DerivedState.RETRYABLE_ERROR

    # 6) Default
    return DerivedState.NEEDS_INGEST


# ---------------------------------------------------------------------------
# Decision logic
# ---------------------------------------------------------------------------


def decide_action(
    *,
    state: DerivedState,
    evidence: WindowedEvidence,
    policy: RetryPolicy,
    budget: BudgetContext,
) -> Decision:
    """
    Decide the next orchestration action given a derived state and evidence.

    This function is pure: it does not touch stores or vendors.
    """

    # DONE/BLOCKED => noop
    if state == DerivedState.DONE:
        return Decision(action="noop", reason="done")

    if state == DerivedState.BLOCKED:
        # Preserve specific blocker reason if available
        br = evidence.block_reason or "blocked_unknown"
        return Decision(action="noop", reason=br)

    # Budget-gated states
    if state == DerivedState.SKIPPED_BUDGET:
        if budget.remaining_usd <= 0:
            return Decision(action="noop", reason="budget_exhausted")
        return Decision(action="attempt_ingest", reason="budget_available_retry")

    if state == DerivedState.NEEDS_INGEST:
        if budget.remaining_usd <= 0:
            return Decision(action="noop", reason="budget_exhausted")
        return Decision(action="attempt_ingest", reason="needs_ingest")

    # Error handling
    if state == DerivedState.RETRYABLE_ERROR:
        lo = evidence.latest_outcome

        # Stop-run on systemic error (if policy enabled)
        if (
            lo is not None
            and policy.stop_run_on_systemic_error
            and is_systemic_error(
                error_class=lo.error_class,
                error_type=lo.error_type,
                error_message=lo.error_message,
            )
        ):
            return Decision(action="stop_run", reason="systemic_error")

        # Retry cap (MVP approximation)
        errs = consecutive_error_count(lo)
        if errs >= policy.max_consecutive_errors:
            return Decision(action="noop", reason="retry_limit_reached")

        if budget.remaining_usd <= 0:
            return Decision(action="noop", reason="budget_exhausted_after_error")

        return Decision(action="attempt_ingest", reason="retryable_error")

    # Defensive default
    return Decision(action="stop_run", reason="unknown_state")
