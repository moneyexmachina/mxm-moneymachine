# mxm/v1/marketdata/datasets/ohlcv_1d/state.py

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import (
    AttemptsCoverageSnapshot,
    OHLCV1DAttemptRow,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.coverage import (
    complete_from_expected_and_observed,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.expected import ExpectedWindow


class DerivedState(str, Enum):
    DONE = "done"
    BLOCKED_UNMAPPED = "blocked_unmapped"
    BLOCKED_EMPTY_EXPECTED = "blocked_empty_expected"
    NEEDS_INGEST = "needs_ingest"
    RETRYABLE_ERROR = "retryable_error"
    FINAL_ERROR = "final_error"
    SKIPPED_BUDGET = "skipped_budget"
    UNKNOWN = "unknown"


DecisionAction = Literal["noop", "attempt_ingest", "stop_run"]


@dataclass(frozen=True)
class Decision:
    action: DecisionAction
    reason: str


@dataclass(frozen=True)
class RetryPolicy:
    """
    Minimal MVP retry policy.

    You can extend later with:
    - exponential backoff
    - per-error-type rules
    - max retries per day, etc.
    """

    max_consecutive_errors: int = 3
    stop_run_on_systemic_error: bool = True


@dataclass(frozen=True)
class BudgetContext:
    remaining_usd: float


# -------------------------
# Helpers
# -------------------------


def _is_systemic_error(error_type: str | None, error_message: str | None) -> bool:
    """
    MVP classifier. Keep conservative. Refine over time.

    Examples of systemic errors:
    - auth / permission failures
    - adapter misconfiguration
    - schema/migration issues
    """
    t = (error_type or "").lower()
    m = (error_message or "").lower()

    # coarse string heuristics
    if "authentication" in m or "permission" in m or "unauthorized" in m:
        return True
    if "no such table" in m or "migration" in m:
        return True
    if "schema" in m and "error" in m:
        return True
    if "operationalerror" in t and "locked" not in m:
        # sqlite locked is transient; other operational errors can be systemic
        return True

    return False


def _consecutive_error_count(latest_attempt: OHLCV1DAttemptRow | None) -> int:
    """
    MVP: we only have the latest attempt in hand.
    If you want true consecutive counts, you will extend attempts_store
    with a 'recent attempts for contract' query.
    """
    if latest_attempt is None:
        return 0
    return 1 if latest_attempt.status == "error" else 0


def _has_any_local_data(cov: AttemptsCoverageSnapshot | None) -> bool:
    if cov is None:
        return False
    if (cov.row_count or 0) > 0:
        return True
    if cov.min_ts is not None or cov.max_ts is not None:
        return True
    return False


# -------------------------
# Core: derive state
# -------------------------


def derive_state(
    *,
    latest_attempt: OHLCV1DAttemptRow | None,
    ew: ExpectedWindow,
    coverage_now: AttemptsCoverageSnapshot | None,
    is_mapped: bool,
    reset_local: bool,
) -> DerivedState:
    """
    Pure, deterministic state derivation.

    Principle:
      - Blockers first.
      - coverage_now vs ew dominates for DONE vs NEEDS_INGEST.
      - vendor_final only allows DONE-for-partial when we have evidence of any local data.
      - reset_local is an operator override that forces re-ingest (i.e. prevents DONE short-circuits).
      - latest_attempt is consulted for budget/error classification only after coverage-based checks.
    """
    # Blockers first
    if not is_mapped:
        return DerivedState.BLOCKED_UNMAPPED

    if ew.is_empty:
        return DerivedState.BLOCKED_EMPTY_EXPECTED

    # Operator override: if they reset local, they explicitly want to ingest again
    # (except for empty expected, already handled above).
    if reset_local:
        return DerivedState.NEEDS_INGEST

    has_data_now = _has_any_local_data(coverage_now)
    # Coverage-based evaluation
    if has_data_now:
        # pyright narrowing: we are about to access fields
        if coverage_now is None:
            # defensive: should be impossible given has_data_now, but keeps types strict
            return DerivedState.NEEDS_INGEST

        # Only compute completeness if we have a trustworthy observed range
        has_observed_range = (
            int(coverage_now.row_count) > 0
            and coverage_now.min_ts is not None
            and coverage_now.max_ts is not None
        )

        if has_observed_range:
            is_complete_now = complete_from_expected_and_observed(
                expected_start=ew.expected_start,
                expected_end=ew.expected_end,
                row_count=int(coverage_now.row_count),
                min_ts=coverage_now.min_ts,
                max_ts=coverage_now.max_ts,
            )
            if is_complete_now:
                return DerivedState.DONE

        # Not complete (or cannot prove complete). Vendor-final partial acceptance
        if ew.vendor_final:
            return DerivedState.DONE

        return DerivedState.NEEDS_INGEST

    # No local data now (empty coverage): vendor_final does NOT imply DONE.
    # We still need to attempt ingest at least once.
    # Fall through to attempt-based signals (budget/error), otherwise NEEDS_INGEST.

    if latest_attempt is not None:
        if latest_attempt.status == "skipped_cost_cap":
            return DerivedState.SKIPPED_BUDGET
        if latest_attempt.status == "error":
            return DerivedState.RETRYABLE_ERROR
        if latest_attempt.status == "unmapped":
            return DerivedState.BLOCKED_UNMAPPED
        if latest_attempt.status == "skipped_empty_expected_window":
            return DerivedState.BLOCKED_EMPTY_EXPECTED

    return DerivedState.NEEDS_INGEST


# -------------------------
# Core: decide action
# -------------------------


def decide_action(
    *,
    state: DerivedState,
    policy: RetryPolicy,
    budgets: BudgetContext,
    latest_attempt: OHLCV1DAttemptRow | None,
) -> Decision:
    """
    Pure decision. No vendor calls. No IO.
    """
    if state in (
        DerivedState.DONE,
        DerivedState.BLOCKED_UNMAPPED,
        DerivedState.BLOCKED_EMPTY_EXPECTED,
        DerivedState.SKIPPED_BUDGET,
        DerivedState.FINAL_ERROR,
    ):
        return Decision(action="noop", reason=state.value)

    if state == DerivedState.UNKNOWN:
        return Decision(action="stop_run", reason="unknown_state")

    if state == DerivedState.NEEDS_INGEST:
        if budgets.remaining_usd <= 0:
            return Decision(action="noop", reason="budget_exhausted")
        return Decision(action="attempt_ingest", reason="needs_ingest")

    if state == DerivedState.RETRYABLE_ERROR:
        # systemic error detection
        if (
            latest_attempt is not None
            and policy.stop_run_on_systemic_error
            and _is_systemic_error(
                latest_attempt.error_type, latest_attempt.error_message
            )
        ):
            return Decision(action="stop_run", reason="systemic_error")

        # retry cap (MVP: only counts the latest attempt; refine later)
        errs = _consecutive_error_count(latest_attempt)
        if errs >= policy.max_consecutive_errors:
            return Decision(action="noop", reason="retry_limit_reached")

        if budgets.remaining_usd <= 0:
            return Decision(action="noop", reason="budget_exhausted_after_error")

        return Decision(action="attempt_ingest", reason="retryable_error")

    # Defensive default
    return Decision(action="stop_run", reason="unhandled_state")
