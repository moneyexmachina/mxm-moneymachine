from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mxm.moneymachine.calendars.models import (
    CalendarOutOfRange,
    ScheduleUnavailable,
    TradingCalendar,
)


def _make_calendar() -> TradingCalendar:
    trading_days = np.array(
        [np.datetime64("2025-01-02", "D"), np.datetime64("2025-01-03", "D")],
        dtype="datetime64[D]",
    )
    observed_end = np.datetime64("2025-01-03", "D")

    schedule = pd.DataFrame(
        {
            "open_utc": pd.to_datetime(
                ["2025-01-02T08:00:00Z", "2025-01-03T08:00:00Z"],
                utc=True,
            ),
            "close_utc": pd.to_datetime(
                ["2025-01-02T16:00:00Z", "2025-01-03T16:00:00Z"],
                utc=True,
            ),
        },
        index=pd.to_datetime(["2025-01-02", "2025-01-03"]).date,
    )

    return TradingCalendar(
        calendar_id="test",
        trading_days=trading_days,
        observed_end=observed_end,
        schedule=schedule,
    )


def _make_label_only_calendar() -> TradingCalendar:
    trading_days = np.array(
        [np.datetime64("2025-01-02", "D"), np.datetime64("2025-01-03", "D")],
        dtype="datetime64[D]",
    )
    observed_end = np.datetime64("2025-01-03", "D")

    return TradingCalendar(
        calendar_id="test_label_only",
        trading_days=trading_days,
        observed_end=observed_end,
        schedule=None,
    )


def _make_calendar_with_projected_day() -> TradingCalendar:
    trading_days = np.array(
        [
            np.datetime64("2025-01-02", "D"),
            np.datetime64("2025-01-03", "D"),
            np.datetime64("2025-01-06", "D"),  # projected beyond observed_end
        ],
        dtype="datetime64[D]",
    )
    observed_end = np.datetime64("2025-01-03", "D")

    schedule = pd.DataFrame(
        {
            "open_utc": pd.to_datetime(
                ["2025-01-02T08:00:00Z", "2025-01-03T08:00:00Z"],
                utc=True,
            ),
            "close_utc": pd.to_datetime(
                ["2025-01-02T16:00:00Z", "2025-01-03T16:00:00Z"],
                utc=True,
            ),
        },
        index=pd.to_datetime(["2025-01-02", "2025-01-03"]).date,
    )

    return TradingCalendar(
        calendar_id="test_projected",
        trading_days=trading_days,
        observed_end=observed_end,
        schedule=schedule,
    )


def test_session_open_returns_utc_timestamp() -> None:
    cal = _make_calendar()

    got = cal.session_open("2025-01-02")

    assert isinstance(got, pd.Timestamp)
    assert got == pd.Timestamp("2025-01-02T08:00:00Z")
    assert got.tz is not None
    assert got.tzname() == "UTC"


def test_session_close_returns_utc_timestamp() -> None:
    cal = _make_calendar()

    got = cal.session_close(np.datetime64("2025-01-03", "D"))

    assert isinstance(got, pd.Timestamp)
    assert got == pd.Timestamp("2025-01-03T16:00:00Z")
    assert got.tz is not None
    assert got.tzname() == "UTC"


def test_session_bounds_returns_open_and_close() -> None:
    cal = _make_calendar()

    open_ts, close_ts = cal.session_bounds("2025-01-02")

    assert open_ts == pd.Timestamp("2025-01-02T08:00:00Z")
    assert close_ts == pd.Timestamp("2025-01-02T16:00:00Z")
    assert open_ts.tz is not None
    assert close_ts.tz is not None
    assert open_ts.tzname() == "UTC"
    assert close_ts.tzname() == "UTC"


def test_session_bounds_matches_individual_methods() -> None:
    cal = _make_calendar()

    open_ts, close_ts = cal.session_bounds("2025-01-03")

    assert open_ts == cal.session_open("2025-01-03")
    assert close_ts == cal.session_close("2025-01-03")


def test_session_open_raises_without_schedule() -> None:
    cal = _make_label_only_calendar()

    with pytest.raises(ScheduleUnavailable):
        _ = cal.session_open("2025-01-02")


def test_session_close_raises_without_schedule() -> None:
    cal = _make_label_only_calendar()

    with pytest.raises(ScheduleUnavailable):
        _ = cal.session_close("2025-01-02")


def test_session_bounds_raises_without_schedule() -> None:
    cal = _make_label_only_calendar()

    with pytest.raises(ScheduleUnavailable):
        _ = cal.session_bounds("2025-01-02")


def test_session_open_raises_for_non_trading_day() -> None:
    cal = _make_calendar()

    with pytest.raises(ValueError, match="is not a trading day"):
        _ = cal.session_open("2025-01-04")


def test_session_close_raises_for_non_trading_day() -> None:
    cal = _make_calendar()

    with pytest.raises(ValueError, match="is not a trading day"):
        _ = cal.session_close("2025-01-04")


def test_session_bounds_raises_for_non_trading_day() -> None:
    cal = _make_calendar()

    with pytest.raises(ValueError, match="is not a trading day"):
        _ = cal.session_bounds("2025-01-04")


def test_session_open_raises_for_projected_day_without_schedule_coverage() -> None:
    cal = _make_calendar_with_projected_day()

    with pytest.raises(CalendarOutOfRange, match="outside observed schedule coverage"):
        _ = cal.session_open("2025-01-06")


def test_session_close_raises_for_projected_day_without_schedule_coverage() -> None:
    cal = _make_calendar_with_projected_day()

    with pytest.raises(CalendarOutOfRange, match="outside observed schedule coverage"):
        _ = cal.session_close("2025-01-06")


def test_session_bounds_raises_for_projected_day_without_schedule_coverage() -> None:
    cal = _make_calendar_with_projected_day()

    with pytest.raises(CalendarOutOfRange, match="outside observed schedule coverage"):
        _ = cal.session_bounds("2025-01-06")
