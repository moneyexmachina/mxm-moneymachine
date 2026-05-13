from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import (
    AttemptsCoverageSnapshot,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.coverage import (
    complete_from_expected_and_observed,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.expected import ExpectedWindow
from mxm.v1.marketdata.datasets.statistics_1d.attempts_store import (
    Statistics1DAttemptRow,
)


class DerivedState(str, Enum):
    DONE = "done"
    BLOCKED_UNMAPPED = "blocked_unmapped"
    BLOCKED_EMPTY_EXPECTED = "blocked_empty_expected"
    NEEDS_INGEST = "needs_ingest"
    RETRYABLE_ERROR = "retryable_error"
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


# TODO(mxm-v1): ohlcv_1d/state.py and statistics_1d/state.py currently
# share near-identical windowed-ingest state/decision logic. Revisit
# consolidation after mxm-v1 publication and CI stabilization.
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


def _consecutive_error_count(latest_attempt: Statistics1DAttemptRow | None) -> int:
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
    latest_attempt: Statistics1DAttemptRow | None,
    ew: ExpectedWindow,
    coverage_now: AttemptsCoverageSnapshot | None,
    is_mapped: bool,
    force_reset: bool,
) -> DerivedState:
    """
    Pure, deterministic state derivation.
    """
    blocker_state = _derive_blocker_state(
        ew=ew,
        is_mapped=is_mapped,
    )
    if blocker_state is not None:
        return blocker_state

    if force_reset:
        return DerivedState.NEEDS_INGEST

    coverage_state = _derive_coverage_state(
        ew=ew,
        coverage_now=coverage_now,
    )
    if coverage_state is not None:
        return coverage_state

    attempt_state = _derive_latest_attempt_state(latest_attempt)
    if attempt_state is not None:
        return attempt_state

    return DerivedState.NEEDS_INGEST


def _derive_blocker_state(
    *,
    ew: ExpectedWindow,
    is_mapped: bool,
) -> DerivedState | None:
    if not is_mapped:
        return DerivedState.BLOCKED_UNMAPPED

    if ew.is_empty:
        return DerivedState.BLOCKED_EMPTY_EXPECTED

    return None


def _derive_coverage_state(
    *,
    ew: ExpectedWindow,
    coverage_now: AttemptsCoverageSnapshot | None,
) -> DerivedState | None:
    if not _has_any_local_data(coverage_now):
        return None

    if coverage_now is None:
        return DerivedState.NEEDS_INGEST

    if _coverage_proves_complete(ew=ew, coverage_now=coverage_now):
        return DerivedState.DONE

    if ew.vendor_final:
        return DerivedState.DONE

    return DerivedState.NEEDS_INGEST


def _coverage_proves_complete(
    *,
    ew: ExpectedWindow,
    coverage_now: AttemptsCoverageSnapshot,
) -> bool:
    if not _has_observed_range(coverage_now):
        return False

    return complete_from_expected_and_observed(
        expected_start=ew.expected_start,
        expected_end=ew.expected_end,
        row_count=int(coverage_now.row_count),
        min_ts=coverage_now.min_ts,
        max_ts=coverage_now.max_ts,
    )


def _has_observed_range(coverage_now: AttemptsCoverageSnapshot) -> bool:
    return (
        int(coverage_now.row_count) > 0
        and coverage_now.min_ts is not None
        and coverage_now.max_ts is not None
    )


def _derive_latest_attempt_state(
    latest_attempt: Statistics1DAttemptRow | None,
) -> DerivedState | None:
    if latest_attempt is None:
        return None

    if latest_attempt.status == "skipped_cost_cap":
        return DerivedState.SKIPPED_BUDGET

    if latest_attempt.status == "error":
        return DerivedState.RETRYABLE_ERROR

    if latest_attempt.status == "unmapped":
        return DerivedState.BLOCKED_UNMAPPED

    if latest_attempt.status == "skipped_empty_expected_window":
        return DerivedState.BLOCKED_EMPTY_EXPECTED

    return None


# -------------------------
# Core: decide action
# -------------------------


def decide_action(
    *,
    state: DerivedState,
    policy: RetryPolicy,
    budgets: BudgetContext,
    latest_attempt: Statistics1DAttemptRow | None,
) -> Decision:
    """
    Pure decision. No vendor calls. No IO.
    """
    if _is_terminal_noop_state(state):
        return Decision(action="noop", reason=state.value)

    if state == DerivedState.SKIPPED_BUDGET:
        return _decide_budget_retry(budgets)

    if state == DerivedState.UNKNOWN:
        return Decision(action="stop_run", reason="unknown_state")

    if state == DerivedState.NEEDS_INGEST:
        return _decide_needs_ingest(budgets)

    if state == DerivedState.RETRYABLE_ERROR:
        return _decide_retryable_error(
            policy=policy,
            budgets=budgets,
            latest_attempt=latest_attempt,
        )

    return Decision(action="stop_run", reason="unhandled_state")


def _is_terminal_noop_state(state: DerivedState) -> bool:
    return state in (
        DerivedState.DONE,
        DerivedState.BLOCKED_UNMAPPED,
        DerivedState.BLOCKED_EMPTY_EXPECTED,
    )


def _decide_budget_retry(budgets: BudgetContext) -> Decision:
    if budgets.remaining_usd <= 0:
        return Decision(action="noop", reason="budget_exhausted")

    return Decision(action="attempt_ingest", reason="budget_available_retry")


def _decide_needs_ingest(budgets: BudgetContext) -> Decision:
    if budgets.remaining_usd <= 0:
        return Decision(action="noop", reason="budget_exhausted")

    return Decision(action="attempt_ingest", reason="needs_ingest")


def _decide_retryable_error(
    *,
    policy: RetryPolicy,
    budgets: BudgetContext,
    latest_attempt: Statistics1DAttemptRow | None,
) -> Decision:
    if _should_stop_on_systemic_error(
        policy=policy,
        latest_attempt=latest_attempt,
    ):
        return Decision(action="stop_run", reason="systemic_error")

    if _retry_limit_reached(
        policy=policy,
        latest_attempt=latest_attempt,
    ):
        return Decision(action="noop", reason="retry_limit_reached")

    if budgets.remaining_usd <= 0:
        return Decision(action="noop", reason="budget_exhausted_after_error")

    return Decision(action="attempt_ingest", reason="retryable_error")


def _should_stop_on_systemic_error(
    *,
    policy: RetryPolicy,
    latest_attempt: Statistics1DAttemptRow | None,
) -> bool:
    return (
        latest_attempt is not None
        and policy.stop_run_on_systemic_error
        and _is_systemic_error(
            latest_attempt.error_type,
            latest_attempt.error_message,
        )
    )


def _retry_limit_reached(
    *,
    policy: RetryPolicy,
    latest_attempt: Statistics1DAttemptRow | None,
) -> bool:
    return _consecutive_error_count(latest_attempt) >= policy.max_consecutive_errors
