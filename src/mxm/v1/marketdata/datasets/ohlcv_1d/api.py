from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta

import pandas as pd


@dataclass(frozen=True)
class OHLCV1DWindow:
    """
    Canonical half-open window [start, end) for ohlcv-1d pulls.
    """

    start: pd.Timestamp
    end: pd.Timestamp


def _coerce_date(x: date | datetime | str) -> date:
    """
    Coerce an ISO date string ('YYYY-MM-DD') or date/datetime into `datetime.date`.

    Accepted:
      - datetime.date
      - datetime.datetime (converted via .date())
      - str in ISO 'YYYY-MM-DD' form
    """
    if isinstance(x, date) and not isinstance(x, datetime):
        return x
    if isinstance(x, datetime):
        return x.date()
    return date.fromisoformat(x)


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
