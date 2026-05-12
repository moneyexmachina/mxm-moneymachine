from __future__ import annotations

import numpy as np
import pytest

from mxm.v1.calendars.models import TradingCalendar
from mxm.v1.utils.date_utils import coerce_np_day


def _synthetic_trading_days() -> np.ndarray:
    """
    Two trading weeks (Mon-Fri) starting 2026-02-02.

    Trading days:
      2026-02-02 .. 2026-02-06
      2026-02-09 .. 2026-02-13
    """
    days = [
        "2026-02-02",
        "2026-02-03",
        "2026-02-04",
        "2026-02-05",
        "2026-02-06",
        "2026-02-09",
        "2026-02-10",
        "2026-02-11",
        "2026-02-12",
        "2026-02-13",
    ]
    return np.array(days, dtype="datetime64[D]")


def _make_calendar() -> TradingCalendar:
    tdays = _synthetic_trading_days()
    observed_end = tdays[-1]

    return TradingCalendar(
        calendar_id="test_cal",
        trading_days=tdays,
        observed_end=observed_end,
    )


def test_is_trading_day() -> None:
    cal = _make_calendar()

    assert cal.is_trading_day("2026-02-04") is True
    assert cal.is_trading_day("2026-02-01") is False  # Sunday
    assert cal.is_trading_day("2026-02-07") is False  # Saturday


def test_normalize_next_prev_raise() -> None:
    cal = _make_calendar()

    # already trading day -> unchanged
    assert cal.normalize("2026-02-04", how="next") == coerce_np_day("2026-02-04")
    assert cal.normalize("2026-02-04", how="prev") == coerce_np_day("2026-02-04")

    # Sunday -> next Monday
    assert cal.normalize("2026-02-01", how="next") == coerce_np_day("2026-02-02")
    # Sunday -> prev Friday (not in this synthetic calendar; expect it to raise if out-of-range)
    with pytest.raises(ValueError):
        _ = cal.normalize("2026-02-01", how="prev")

    # Saturday inside window -> prev Friday, next Monday
    assert cal.normalize("2026-02-07", how="prev") == coerce_np_day("2026-02-06")
    assert cal.normalize("2026-02-07", how="next") == coerce_np_day("2026-02-09")

    with pytest.raises(ValueError):
        _ = cal.normalize("2026-02-07", how="raise")


def test_add_trading_days() -> None:
    cal = _make_calendar()

    assert cal.add_trading_days("2026-02-04", 0) == coerce_np_day("2026-02-04")
    assert cal.add_trading_days("2026-02-04", 1) == coerce_np_day("2026-02-05")
    assert cal.add_trading_days("2026-02-04", -1) == coerce_np_day("2026-02-03")

    # across a weekend: Fri + 1 -> next Mon
    assert cal.add_trading_days("2026-02-06", 1) == coerce_np_day("2026-02-09")
    # across a weekend backwards: Mon - 1 -> prev Fri
    assert cal.add_trading_days("2026-02-09", -1) == coerce_np_day("2026-02-06")


def test_trading_days_between_strict_inclusive() -> None:
    cal = _make_calendar()

    s = coerce_np_day("2026-02-03")
    e = coerce_np_day("2026-02-05")

    got = cal.trading_days_between(s, e, strict=True)
    exp = np.array(["2026-02-03", "2026-02-04", "2026-02-05"], dtype="datetime64[D]")
    assert got.dtype == np.dtype("datetime64[D]")
    assert np.array_equal(got, exp)

    # strict: start not trading day -> raise
    with pytest.raises(ValueError):
        _ = cal.trading_days_between("2026-02-01", "2026-02-05", strict=True)

    # strict: end not trading day -> raise
    with pytest.raises(ValueError):
        _ = cal.trading_days_between("2026-02-03", "2026-02-07", strict=True)


def test_bdays_to_ltd_basic() -> None:
    cal = _make_calendar()

    ltd = coerce_np_day("2026-02-13")  # last day in synthetic calendar

    assert cal.bdays_to_ltd("2026-02-13", ltd) == 0
    assert cal.bdays_to_ltd("2026-02-12", ltd) == 1
    assert cal.bdays_to_ltd("2026-02-10", ltd) == 3

    # Non-trading asof should raise under strict semantics (if that is your contract)
    with pytest.raises(ValueError):
        _ = cal.bdays_to_ltd("2026-02-07", ltd)
