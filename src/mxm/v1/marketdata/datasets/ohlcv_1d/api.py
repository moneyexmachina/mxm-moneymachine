from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd


@dataclass(frozen=True)
class OHLCV1DWindow:
    """
    Canonical half-open window [start, end) for ohlcv-1d pulls.
    """

    start: pd.Timestamp
    end: pd.Timestamp


def _coerce_date(x: date | str) -> date:
    """
    Coerce a YYYY-MM-DD string (or date) into a date object.
    """
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, str):
        # Expect ISO 'YYYY-MM-DD'
        return date.fromisoformat(x)
    # If a datetime slips through, convert to date
    if isinstance(x, datetime):
        return x.date()
    raise TypeError(f"Expected date|str for date field, got {type(x)}: {x!r}")


def contract_window_utc_half_open(
    *, start_date: date, end_date_inclusive: date
) -> OHLCV1DWindow:
    """
    Convert a contract lifecycle window defined by dates into a half-open UTC timestamp window.

    If last_trading_day is inclusive (a day on which a bar should exist),
    then the half-open end is (last_trading_day + 1 day) at 00:00Z.

    Returns:
      start = start_date 00:00Z
      end   = (end_date_inclusive + 1 day) 00:00Z
    """
    start_d = _coerce_date(start_date)
    end_d = _coerce_date(end_date_inclusive)

    start = pd.Timestamp(start_d).tz_localize("UTC")
    end = pd.Timestamp(end_d + timedelta(days=1)).tz_localize("UTC")
    return OHLCV1DWindow(start=start, end=end)


def is_complete_level0(
    *,
    stored_min: pd.Timestamp | None,
    stored_max: pd.Timestamp | None,
    row_count: int,
    target_start: pd.Timestamp,
    target_end: pd.Timestamp,
) -> bool:
    """
    Completion definition (Level 0, MVP) for half-open windows [start, end):

      - row_count > 0
      - stored_min <= target_start
      - stored_max >= (target_end - 1 day)

    Why (end - 1 day)?
    Daily bars are stamped on trading days; for a window ending at 00:00Z of the day AFTER
    last_trading_day, the last expected bar is on (target_end - 1 day).
    """
    if row_count <= 0:
        return False
    if stored_min is None or stored_max is None:
        return False

    # Ensure UTC
    smin = (
        stored_min.tz_localize("UTC")
        if stored_min.tzinfo is None
        else stored_min.tz_convert("UTC")
    )
    smax = (
        stored_max.tz_localize("UTC")
        if stored_max.tzinfo is None
        else stored_max.tz_convert("UTC")
    )
    t0 = (
        target_start.tz_localize("UTC")
        if target_start.tzinfo is None
        else target_start.tz_convert("UTC")
    )
    t1 = (
        target_end.tz_localize("UTC")
        if target_end.tzinfo is None
        else target_end.tz_convert("UTC")
    )

    last_expected = t1 - pd.Timedelta(days=1)
    return (smin <= t0) and (smax >= last_expected)
