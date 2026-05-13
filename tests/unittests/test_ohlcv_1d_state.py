
from __future__ import annotations

from types import SimpleNamespace

import pandas as pd

from mxm.v1.marketdata.datasets.ohlcv_1d.state import (
    BudgetContext,
    Decision,
    DerivedState,
    RetryPolicy,
    decide_action,
    derive_state,
)


def _ts(s: str) -> pd.Timestamp:
    """UTC Timestamp helper."""
    t = pd.Timestamp(s)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def _ew(
    *,
    expected_start: pd.Timestamp,
    expected_end: pd.Timestamp,
    is_empty: bool = False,
    vendor_final: bool = False,
):
    """
    Minimal ExpectedWindow-like object for unit tests.
    We only populate attributes used by derive_state/decide_action paths.
    """
    return SimpleNamespace(
        expected_start=expected_start,
        expected_end=expected_end,
        is_empty=is_empty,
        vendor_final=vendor_final,
    )


def _cov(
    *,
    min_ts: pd.Timestamp | None,
    max_ts: pd.Timestamp | None,
    row_count: int,
):
    """Minimal CoverageSnapshot-like object."""
    return SimpleNamespace(min_ts=min_ts, max_ts=max_ts, row_count=int(row_count))


def _attempt(
    *,
    status: str,
    error_type: str | None = None,
    error_message: str | None = None,
):
    """Minimal OHLCV1DAttemptRow-like object (only fields used by decision logic)."""
    return SimpleNamespace(
        status=status, error_type=error_type, error_message=error_message
    )


# -------------------------
# derive_state tests
# -------------------------


def test_derive_state_blocked_unmapped():
    ew = _ew(expected_start=_ts("2020-01-01"), expected_end=_ts("2020-01-02"))
    state = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=None,
        is_mapped=False,
        reset_local=False,
    )
    assert state == DerivedState.BLOCKED_UNMAPPED


def test_derive_state_blocked_empty_expected():
    ew = _ew(
        expected_start=_ts("2020-01-01"),
        expected_end=_ts("2020-01-01"),
        is_empty=True,
    )
    state = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=None,
        is_mapped=True,
        reset_local=False,
    )
    assert state == DerivedState.BLOCKED_EMPTY_EXPECTED


def test_derive_state_reset_local_forces_ingest_even_if_complete_now():
    ew = _ew(expected_start=_ts("2020-01-01"), expected_end=_ts("2020-01-10"))
    cov = _cov(min_ts=_ts("2020-01-01"), max_ts=_ts("2020-01-09"), row_count=10)

    state = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov,
        is_mapped=True,
        reset_local=True,
    )
    assert state == DerivedState.NEEDS_INGEST


def test_derive_state_done_when_vendor_final_even_if_incomplete_when_not_reset():
    ew = _ew(
        expected_start=_ts("2020-01-01"),
        expected_end=_ts("2020-01-10"),
        vendor_final=True,
    )
    # Deliberately incomplete coverage
    cov = _cov(min_ts=_ts("2020-01-01"), max_ts=_ts("2020-01-05"), row_count=5)
    state = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov,
        is_mapped=True,
        reset_local=False,
    )
    assert state == DerivedState.DONE


def test_derive_state_needs_ingest_when_vendor_final_but_reset_local_true():
    ew = _ew(
        expected_start=_ts("2020-01-01"),
        expected_end=_ts("2020-01-10"),
        vendor_final=True,
    )
    # Incomplete coverage (or "empty after reset" semantics)
    cov = _cov(min_ts=_ts("2020-01-01"), max_ts=_ts("2020-01-05"), row_count=5)
    state = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov,
        is_mapped=True,
        reset_local=True,
    )
    assert state == DerivedState.NEEDS_INGEST


def test_derive_state_needs_ingest_when_incomplete_and_not_vendor_final():
    ew = _ew(
        expected_start=_ts("2020-01-01"),
        expected_end=_ts("2020-01-10"),
        vendor_final=False,
    )
    cov = _cov(min_ts=_ts("2020-01-01"), max_ts=_ts("2020-01-05"), row_count=5)
    state = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov,
        is_mapped=True,
        reset_local=False,
    )
    assert state == DerivedState.NEEDS_INGEST


def test_derive_state_reset_local_true_needs_ingest_when_no_coverage():
    ew = _ew(expected_start=_ts("2020-01-01"), expected_end=_ts("2020-01-10"))
    state = derive_state(
        latest_attempt=_attempt(status="complete"),
        ew=ew,
        coverage_now=None,
        is_mapped=True,
        reset_local=True,
    )
    assert state == DerivedState.NEEDS_INGEST


def test_derive_state_skipped_budget_from_latest_attempt():
    ew = _ew(expected_start=_ts("2020-01-01"), expected_end=_ts("2020-01-10"))
    state = derive_state(
        latest_attempt=_attempt(status="skipped_cost_cap"),
        ew=ew,
        coverage_now=None,
        is_mapped=True,
        reset_local=False,
    )
    assert state == DerivedState.SKIPPED_BUDGET


def test_derive_state_retryable_error_from_latest_attempt():
    ew = _ew(expected_start=_ts("2020-01-01"), expected_end=_ts("2020-01-10"))
    state = derive_state(
        latest_attempt=_attempt(
            status="error", error_type="TimeoutError", error_message="timed out"
        ),
        ew=ew,
        coverage_now=None,
        is_mapped=True,
        reset_local=False,
    )
    assert state == DerivedState.RETRYABLE_ERROR


def test_derive_state_vendor_final_but_empty_coverage_still_needs_ingest():
    # vendor_final=True but we have *no local data* (row_count=0, min/max None)
    ew = _ew(
        expected_start=_ts("2020-01-01"),
        expected_end=_ts("2020-01-10"),
        vendor_final=True,
    )
    cov_empty = _cov(min_ts=None, max_ts=None, row_count=0)

    state = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov_empty,
        is_mapped=True,
        reset_local=False,
    )
    assert state == DerivedState.NEEDS_INGEST


def test_derive_state_vendor_final_with_partial_data_is_done():
    # vendor_final=True and we have some local data (row_count>0) but not complete
    ew = _ew(
        expected_start=_ts("2020-01-01"),
        expected_end=_ts("2020-01-10"),
        vendor_final=True,
    )
    cov_partial = _cov(min_ts=_ts("2020-01-01"), max_ts=_ts("2020-01-05"), row_count=5)

    state = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov_partial,
        is_mapped=True,
        reset_local=False,
    )
    assert state == DerivedState.DONE


def test_derive_state_reset_local_overrides_vendor_final_and_forces_ingest():
    # Even if vendor_final and coverage exists, reset_local forces NEEDS_INGEST
    ew = _ew(
        expected_start=_ts("2020-01-01"),
        expected_end=_ts("2020-01-10"),
        vendor_final=True,
    )
    cov_partial = _cov(min_ts=_ts("2020-01-01"), max_ts=_ts("2020-01-05"), row_count=5)

    state = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov_partial,
        is_mapped=True,
        reset_local=True,
    )
    assert state == DerivedState.NEEDS_INGEST


# -------------------------
# decide_action tests
# -------------------------


def test_decide_action_done_is_noop():
    d = decide_action(
        state=DerivedState.DONE,
        policy=RetryPolicy(),
        budgets=BudgetContext(remaining_usd=1.0),
        latest_attempt=None,
    )
    assert isinstance(d, Decision)
    assert d.action == "noop"


def test_decide_action_needs_ingest_attempts_when_budget_positive():
    d = decide_action(
        state=DerivedState.NEEDS_INGEST,
        policy=RetryPolicy(),
        budgets=BudgetContext(remaining_usd=1.0),
        latest_attempt=None,
    )
    assert d.action == "attempt_ingest"


def test_decide_action_needs_ingest_noop_when_budget_exhausted():
    d = decide_action(
        state=DerivedState.NEEDS_INGEST,
        policy=RetryPolicy(),
        budgets=BudgetContext(remaining_usd=0.0),
        latest_attempt=None,
    )
    assert d.action == "noop"
    assert d.reason == "budget_exhausted"


def test_decide_action_retryable_error_stops_on_systemic_error():
    latest = _attempt(
        status="error",
        error_type="OperationalError",
        error_message="no such table: ohlcv_1d_attempts",
    )
    d = decide_action(
        state=DerivedState.RETRYABLE_ERROR,
        policy=RetryPolicy(max_consecutive_errors=3, stop_run_on_systemic_error=True),
        budgets=BudgetContext(remaining_usd=10.0),
        latest_attempt=latest,
    )
    assert d.action == "stop_run"
    assert d.reason == "systemic_error"


def test_decide_action_retryable_error_respects_retry_limit():
    latest = _attempt(
        status="error", error_type="TimeoutError", error_message="timed out"
    )
    d = decide_action(
        state=DerivedState.RETRYABLE_ERROR,
        policy=RetryPolicy(max_consecutive_errors=1, stop_run_on_systemic_error=False),
        budgets=BudgetContext(remaining_usd=10.0),
        latest_attempt=latest,
    )
    assert d.action == "noop"
    assert d.reason == "retry_limit_reached"


def test_decide_action_retryable_error_noop_when_budget_exhausted():
    latest = _attempt(
        status="error", error_type="TimeoutError", error_message="timed out"
    )
    d = decide_action(
        state=DerivedState.RETRYABLE_ERROR,
        policy=RetryPolicy(stop_run_on_systemic_error=False),
        budgets=BudgetContext(remaining_usd=0.0),
        latest_attempt=latest,
    )
    assert d.action == "noop"
    assert d.reason == "budget_exhausted_after_error"


def test_decide_action_unknown_stops_run():
    d = decide_action(
        state=DerivedState.UNKNOWN,
        policy=RetryPolicy(),
        budgets=BudgetContext(remaining_usd=1.0),
        latest_attempt=None,
    )
    assert d.action == "stop_run"
    assert d.reason == "unknown_state"
