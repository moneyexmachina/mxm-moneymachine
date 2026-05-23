from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mxm.moneymachine.calendars.models import CalendarOutOfRange, TradingCalendar


def _make_calendar() -> TradingCalendar:
    # Two sessions: 2025-01-02 and 2025-01-03
    trading_days = np.array(
        [np.datetime64("2025-01-02", "D"), np.datetime64("2025-01-03", "D")],
        dtype="datetime64[D]",
    )
    observed_end = np.datetime64("2025-01-03", "D")

    # Define UTC open/close with a gap between sessions
    schedule = pd.DataFrame(
        {
            "open_utc": pd.to_datetime(
                ["2025-01-02T08:00:00Z", "2025-01-03T08:00:00Z"], utc=True
            ),
            "close_utc": pd.to_datetime(
                ["2025-01-02T16:00:00Z", "2025-01-03T16:00:00Z"], utc=True
            ),
        },
        index=pd.to_datetime(
            ["2025-01-02", "2025-01-03"]
        ).date,  # date-like index ok; model coerces
    )

    return TradingCalendar(
        calendar_id="test",
        trading_days=trading_days,
        observed_end=observed_end,
        schedule=schedule,
    )


def test_current_sessions_matches_scalar() -> None:
    cal = _make_calendar()

    ts = pd.Series(
        pd.to_datetime(
            [
                "2025-01-02T08:00:00Z",  # exactly open -> in session day1
                "2025-01-02T15:59:59Z",  # in session day1
                "2025-01-02T16:00:00Z",  # exactly close -> NOT in session (half-open)
                "2025-01-03T09:00:00Z",  # in session day2
            ],
            utc=True,
        )
    )

    got = cal.current_sessions(ts)

    # Compare elementwise with scalar
    exp: list[np.datetime64 | str | None] = []
    for x in ts:
        try:
            exp.append(cal.current_session(x))
        except CalendarOutOfRange:
            exp.append("OOR")  # should not happen in this test
    assert list(got) == exp


def test_current_sessions_gap_returns_none() -> None:
    cal = _make_calendar()

    # Gap between day1 close and day2 open
    ts = pd.Series(pd.to_datetime(["2025-01-02T20:00:00Z"], utc=True))
    got = cal.current_sessions(ts)
    assert got.iloc[0] is None


def test_current_sessions_raises_out_of_range_by_default() -> None:
    cal = _make_calendar()

    ts = pd.Series(
        pd.to_datetime(
            [
                "2025-01-02T09:00:00Z",
                "2025-01-01T09:00:00Z",  # before first open -> out of range
            ],
            utc=True,
        )
    )

    with pytest.raises(CalendarOutOfRange):
        _ = cal.current_sessions(ts)


def test_current_sessions_out_of_range_null_mode() -> None:
    cal = _make_calendar()

    ts = pd.Series(
        pd.to_datetime(
            [
                "2025-01-02T09:00:00Z",
                "2025-01-01T09:00:00Z",  # before coverage
                "2025-01-04T09:00:00Z",  # after coverage
            ],
            utc=True,
        )
    )

    got = cal.current_sessions(ts, out_of_range="null")
    assert got.iloc[0] == np.datetime64("2025-01-02", "D")
    assert got.iloc[1] is None
    assert got.iloc[2] is None


def test_current_sessions_handles_nat() -> None:
    cal = _make_calendar()

    ts = pd.Series([pd.Timestamp("2025-01-02T09:00:00Z"), pd.NaT])
    got = cal.current_sessions(ts)
    assert got.iloc[0] == np.datetime64("2025-01-02", "D")
    assert got.iloc[1] is None
