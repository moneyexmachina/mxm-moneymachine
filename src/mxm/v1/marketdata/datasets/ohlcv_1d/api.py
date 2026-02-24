from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import pandas as pd

from mxm.v1.utils.date_utils import (
    coerce_date,
    utc_day_end_exclusive,
    utc_day_start,
)


@dataclass(frozen=True)
class OHLCV1DWindow:
    """
    Canonical half-open window [start, end) for ohlcv-1d pulls.
    """

    start: pd.Timestamp
    end: pd.Timestamp


def contract_window_utc_half_open(
    *, start_date: date, end_date_inclusive: date
) -> OHLCV1DWindow:
    """
    Convert an inclusive date lifecycle window into a half-open UTC timestamp window.
    """
    start_d = coerce_date(start_date)
    end_d = coerce_date(end_date_inclusive)

    start = utc_day_start(start_d)
    end = utc_day_end_exclusive(end_d)  # +1 day 00:00Z
    return OHLCV1DWindow(start=start, end=end)
