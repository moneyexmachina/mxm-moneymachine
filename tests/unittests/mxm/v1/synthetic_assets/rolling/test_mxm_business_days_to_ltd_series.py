# tests/unittests/mxm/v1/synthetic_assets/rolling/test_mxm_business_days_to_ltd_series.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pytest

from mxm.v1.calendars.mxm_business_calendar import MxMBusinessCalendar
from mxm.v1.synthetic_assets.rolling.mxm_business_days_to_ltd_series import (
    LTDPrecedesSession,
    MXMBusinessDaysToLTDSeries,
    NoBusinessDayOnOrBeforeLTD,
    SessionNotInMXMBusinessCalendar,
    UnknownContractId,
    build_mxm_business_days_to_ltd_series,
)

# -----------------------------------------------------------------------------
# Minimal fakes for RefDataAPI objects
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeContract:
    last_trading_day: date


class _FakeRefDataAPI:
    """
    Minimal surface used by build_mxm_business_days_to_ltd_series.

    Only method required:
      - get_contract_by_id(contract_id) -> contract or None
    """

    def __init__(self, contracts: dict[str, _FakeContract]) -> None:
        self._contracts = contracts

    def get_contract_by_id(self, contract_id: str) -> Optional[_FakeContract]:
        return self._contracts.get(contract_id)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _days(*xs: str) -> np.ndarray:
    return np.array(xs, dtype="datetime64[D]")


def _make_business_calendar() -> MxMBusinessCalendar:
    """
    Tiny MXM business calendar with a weekend-like gap.

    Index positions:
      0 -> 2026-03-18
      1 -> 2026-03-19
      2 -> 2026-03-20
      3 -> 2026-03-23
      4 -> 2026-03-24
      5 -> 2026-06-19
    """
    return MxMBusinessCalendar(
        calendar_id="mxm_v1_business",
        business_days=_days(
            "2026-03-18",
            "2026-03-19",
            "2026-03-20",
            "2026-03-23",
            "2026-03-24",
            "2026-06-19",
        ),
        observed_end=np.datetime64("2026-06-19", "D"),
    )


# -----------------------------------------------------------------------------
# Dataclass model tests
# -----------------------------------------------------------------------------


def test_mxm_business_days_to_ltd_series_accepts_valid_payload() -> None:
    out = MXMBusinessDaysToLTDSeries(
        product_id="ANY",
        sessions=_days("2026-03-18", "2026-03-19", "2026-03-20"),
        contract_ids=["C1", "C1", "C2"],
        mxm_business_days_to_ltd=np.array([2, 1, 3], dtype=np.int64),
    )

    assert out.product_id == "ANY"
    assert out.sessions.dtype == np.dtype("datetime64[D]")
    assert out.mxm_business_days_to_ltd.dtype == np.dtype("int64")


def test_mxm_business_days_to_ltd_series_rejects_length_mismatch() -> None:
    with pytest.raises(
        ValueError, match="sessions and contract_ids must have equal length"
    ):
        MXMBusinessDaysToLTDSeries(
            product_id="ANY",
            sessions=_days("2026-03-18", "2026-03-19"),
            contract_ids=["C1"],
            mxm_business_days_to_ltd=np.array([2, 1], dtype=np.int64),
        )


def test_mxm_business_days_to_ltd_series_rejects_bdays_length_mismatch() -> None:
    with pytest.raises(
        ValueError,
        match="sessions and mxm_business_days_to_ltd must have equal length",
    ):
        MXMBusinessDaysToLTDSeries(
            product_id="ANY",
            sessions=_days("2026-03-18", "2026-03-19"),
            contract_ids=["C1", "C1"],
            mxm_business_days_to_ltd=np.array([2], dtype=np.int64),
        )


def test_mxm_business_days_to_ltd_series_casts_bdays_to_int64() -> None:
    out = MXMBusinessDaysToLTDSeries(
        product_id="ANY",
        sessions=_days("2026-03-18", "2026-03-19"),
        contract_ids=["C1", "C1"],
        mxm_business_days_to_ltd=np.array([2, 1], dtype=np.int32),
    )

    assert out.mxm_business_days_to_ltd.dtype == np.dtype("int64")


# -----------------------------------------------------------------------------
# Functional / semantic tests
# -----------------------------------------------------------------------------


def test_build_mxm_business_days_to_ltd_series_functional_oracle() -> None:
    """
    Input-output (functional) test under fully controlled inputs.

    Verifies:
      - per-session LTD anchoring (contract switch changes the LTD used)
      - numeric output is correct on a tiny MXM business-day grid
      - dtype and alignment properties hold
    """
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
            "C2": _FakeContract(last_trading_day=date(2026, 6, 19)),
        }
    )
    cal = _make_business_calendar()

    sessions = _days(
        "2026-03-18",
        "2026-03-19",
        "2026-03-20",
        "2026-03-23",
        "2026-03-24",
    )
    contract_ids = ["C1", "C1", "C2", "C2", "C2"]

    out = build_mxm_business_days_to_ltd_series(
        product_id="ANY",
        sessions=sessions,
        contract_ids=contract_ids,
        mxm_business_calendar=cal,
        refdata_api=ref,
    )

    assert out.sessions.tolist() == sessions.tolist()
    assert out.contract_ids == contract_ids
    assert out.mxm_business_days_to_ltd.dtype == np.dtype("int64")

    # Business-day indices in the calendar:
    # 03-18 -> 0
    # 03-19 -> 1
    # 03-20 -> 2
    # 03-23 -> 3
    # 03-24 -> 4
    # 06-19 -> 5
    #
    # C1 ltd=03-20:
    #   03-18 -> 2-0 = 2
    #   03-19 -> 2-1 = 1
    #
    # C2 ltd=06-19:
    #   03-20 -> 5-2 = 3
    #   03-23 -> 5-3 = 2
    #   03-24 -> 5-4 = 1
    assert out.mxm_business_days_to_ltd.tolist() == [2, 1, 3, 2, 1]


def test_build_mxm_business_days_to_ltd_series_maps_ltd_to_prev_business_day() -> None:
    """
    LTD does not need to be an exact MXM business day.

    The function should map LTD to the greatest business day <= LTD.
    """
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 21)),  # Saturday
        }
    )
    cal = _make_business_calendar()

    sessions = _days("2026-03-18", "2026-03-19")
    contract_ids = ["C1", "C1"]

    out = build_mxm_business_days_to_ltd_series(
        product_id="ANY",
        sessions=sessions,
        contract_ids=contract_ids,
        mxm_business_calendar=cal,
        refdata_api=ref,
    )

    # LTD 2026-03-21 maps back to 2026-03-20 (index 2)
    # 03-18 -> 2-0 = 2
    # 03-19 -> 2-1 = 1
    assert out.mxm_business_days_to_ltd.tolist() == [2, 1]


# -----------------------------------------------------------------------------
# Error handling
# -----------------------------------------------------------------------------


def test_build_mxm_business_days_to_ltd_series_raises_on_unknown_contract_id() -> None:
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
        }
    )
    cal = _make_business_calendar()

    sessions = _days("2026-03-18", "2026-03-19")
    contract_ids = ["C1", "C_UNKNOWN"]

    with pytest.raises(UnknownContractId, match="Unknown contract_id"):
        build_mxm_business_days_to_ltd_series(
            product_id="ANY",
            sessions=sessions,
            contract_ids=contract_ids,
            mxm_business_calendar=cal,
            refdata_api=ref,
        )


def test_build_mxm_business_days_to_ltd_series_raises_when_session_not_in_business_calendar() -> (
    None
):
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
        }
    )
    cal = _make_business_calendar()

    sessions = _days("2026-03-18", "2026-03-21")  # second session not a business day
    contract_ids = ["C1", "C1"]

    with pytest.raises(
        SessionNotInMXMBusinessCalendar,
        match="is not an exact MXM business day",
    ):
        build_mxm_business_days_to_ltd_series(
            product_id="ANY",
            sessions=sessions,
            contract_ids=contract_ids,
            mxm_business_calendar=cal,
            refdata_api=ref,
        )


def test_build_mxm_business_days_to_ltd_series_raises_when_no_business_day_exists_on_or_before_ltd() -> (
    None
):
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(
                last_trading_day=date(2026, 3, 17)
            ),  # before first business day
        }
    )
    cal = _make_business_calendar()

    sessions = _days("2026-03-18")
    contract_ids = ["C1"]

    with pytest.raises(
        NoBusinessDayOnOrBeforeLTD,
        match="No MXM business day exists on or before LTD",
    ):
        build_mxm_business_days_to_ltd_series(
            product_id="ANY",
            sessions=sessions,
            contract_ids=contract_ids,
            mxm_business_calendar=cal,
            refdata_api=ref,
        )


def test_build_mxm_business_days_to_ltd_series_raises_when_ltd_precedes_session() -> (
    None
):
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
        }
    )
    cal = _make_business_calendar()

    sessions = _days("2026-03-23")  # after mapped LTD business day 2026-03-20
    contract_ids = ["C1"]

    with pytest.raises(
        LTDPrecedesSession,
        match="LTD maps to a business day before the input session",
    ):
        build_mxm_business_days_to_ltd_series(
            product_id="ANY",
            sessions=sessions,
            contract_ids=contract_ids,
            mxm_business_calendar=cal,
            refdata_api=ref,
        )


def test_build_mxm_business_days_to_ltd_series_raises_on_length_mismatch() -> None:
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
        }
    )
    cal = _make_business_calendar()

    with pytest.raises(
        ValueError, match="sessions and contract_ids must have equal length"
    ):
        build_mxm_business_days_to_ltd_series(
            product_id="ANY",
            sessions=_days("2026-03-18", "2026-03-19"),
            contract_ids=["C1"],
            mxm_business_calendar=cal,
            refdata_api=ref,
        )
