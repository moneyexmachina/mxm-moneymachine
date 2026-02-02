from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from mxm.v1.marketdata.datasets.ohlcv_1d.expected import ExpectedWindow
from mxm.v1.marketdata.datasets.ohlcv_1d.state import (
    BudgetContext,
    DerivedState,
    RetryPolicy,
    decide_action,
    derive_state,
)


# Minimal fakes for typing convenience
@dataclass(frozen=True)
class _FakeAttemptRow:
    status: str
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class _FakeCov:
    min_ts: pd.Timestamp | None
    max_ts: pd.Timestamp | None
    row_count: int


def _ts(day: str) -> pd.Timestamp:
    """
    Day-aligned UTC timestamp.
    """
    # pd.Timestamp("2020-01-01", tz="UTC") is day-aligned and tz-aware.
    return pd.Timestamp(day, tz="UTC")


def _ew(
    *,
    product_id: str = "p",
    contract_id: str = "c",
    interest_start: str = "2020-01-01",
    interest_end: str = "2020-01-10",
    dataset_start: str = "2000-01-01",
    dataset_end: str = "2030-01-01",
    activation_floor: str | None = None,
    expiration_ceiling: str | None = None,
    expected_start: str = "2020-01-01",
    expected_end: str = "2020-01-10",
    is_empty: bool = False,
    is_vendor_limited: bool = False,
    is_lifecycle_limited: bool = False,
    vendor_final: bool = False,
) -> ExpectedWindow:
    return ExpectedWindow(
        product_id=product_id,
        contract_id=contract_id,
        interest_start=_ts(interest_start),
        interest_end=_ts(interest_end),
        dataset_start=_ts(dataset_start),
        dataset_end=_ts(dataset_end),
        activation_floor=_ts(activation_floor) if activation_floor else None,
        expiration_ceiling=_ts(expiration_ceiling) if expiration_ceiling else None,
        expected_start=_ts(expected_start),
        expected_end=_ts(expected_end),
        is_empty=bool(is_empty),
        is_vendor_limited=bool(is_vendor_limited),
        is_lifecycle_limited=bool(is_lifecycle_limited),
        vendor_final=bool(vendor_final),
    )


def test_derive_state_unmapped_blocks_first() -> None:
    ew = _ew(is_empty=False, vendor_final=False)
    s = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=None,  # no local info
        is_mapped=False,
        reset_local=False,
    )
    assert s == DerivedState.BLOCKED_UNMAPPED


def test_derive_state_empty_expected_blocks() -> None:
    ew = _ew(is_empty=True, vendor_final=False)
    s = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=None,
        is_mapped=True,
        reset_local=False,
    )
    assert s == DerivedState.BLOCKED_EMPTY_EXPECTED


def test_derive_state_reset_local_forces_needs_ingest_even_if_complete() -> None:
    """
    Operator override: reset_local prevents DONE short-circuit.
    """
    ew = _ew(
        is_empty=False,
        vendor_final=False,
        expected_start="2020-01-01",
        expected_end="2020-01-03",
    )
    cov = _FakeCov(min_ts=_ts("2020-01-01"), max_ts=_ts("2020-01-02"), row_count=2)
    s = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov,  # type: ignore[arg-type]
        is_mapped=True,
        reset_local=True,
    )
    assert s == DerivedState.NEEDS_INGEST


def test_vendor_final_does_not_short_circuit_without_any_local_data() -> None:
    """
    Normative 14e: vendor_final only allows DONE-for-partial when there is evidence of any local data.
    If no local data, we must still attempt ingest at least once.
    """
    ew = _ew(is_empty=False, vendor_final=True)
    cov = _FakeCov(min_ts=None, max_ts=None, row_count=0)
    s = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov,  # type: ignore[arg-type]
        is_mapped=True,
        reset_local=False,
    )
    assert s == DerivedState.NEEDS_INGEST


def test_vendor_final_allows_done_when_any_local_data_exists_but_not_complete() -> None:
    """
    If there is evidence of some local data and vendor_final is true, derive_state may return DONE
    even if windows are incomplete (policy-level acceptance of 'cannot improve').
    """
    ew = _ew(is_empty=False, vendor_final=True)
    cov = _FakeCov(min_ts=_ts("2020-01-01"), max_ts=_ts("2020-01-01"), row_count=1)
    s = derive_state(
        latest_attempt=None,
        ew=ew,
        coverage_now=cov,  # type: ignore[arg-type]
        is_mapped=True,
        reset_local=False,
    )
    assert s == DerivedState.DONE


def test_decide_action_needs_ingest_attempts_if_budget_positive() -> None:
    d = decide_action(
        state=DerivedState.NEEDS_INGEST,
        policy=RetryPolicy(max_consecutive_errors=3, stop_run_on_systemic_error=True),
        budgets=BudgetContext(remaining_usd=1.0),
        latest_attempt=None,
    )
    assert d.action == "attempt_ingest"


def test_decide_action_needs_ingest_noops_if_budget_exhausted() -> None:
    d = decide_action(
        state=DerivedState.NEEDS_INGEST,
        policy=RetryPolicy(max_consecutive_errors=3, stop_run_on_systemic_error=True),
        budgets=BudgetContext(remaining_usd=0.0),
        latest_attempt=None,
    )
    assert d.action == "noop"
