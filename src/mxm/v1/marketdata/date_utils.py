# mxm/v1/marketdata/date_utils.py
from __future__ import annotations

from datetime import date, datetime
from typing import Any

import pandas as pd

from mxm.v1.utils.time_utils import ensure_midnight_utc, parse_ts, to_utc_ts


def coerce_date(value: Any) -> date:
    """
    Coerce a date-like input into a datetime.date.

    Accepted:
      - datetime.date
      - datetime.datetime
      - pandas.Timestamp
      - str: 'YYYY-MM-DD' or ISO8601 timestamp
    Rejected:
      - None
      - timezone-naive strings with ambiguous meaning (parse_ts enforces rules)

    Notes:
      - For datetime/pandas.Timestamp, we take `.date()` (UTC conversion not required for dates).
      - For strings:
          - If it's exactly YYYY-MM-DD, parse via date.fromisoformat
          - Otherwise parse as timestamp (parse_ts) and take UTC date
    """
    if value is None:
        raise TypeError("date value is None")

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, pd.Timestamp):
        return value.date()

    if isinstance(value, str):
        s = value.strip()
        # Fast-path: pure date
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return date.fromisoformat(s)

        # Otherwise treat as timestamp string (must be tz-aware / Z etc)
        ts = parse_ts(s)  # returns UTC tz-aware
        return ts.date()

    raise TypeError(f"unsupported date type: {type(value).__name__} value={value!r}")


def utc_day_start(value: Any) -> pd.Timestamp:
    """
    Return UTC midnight Timestamp for the day of `value`.
    """
    d = coerce_date(value)
    return ensure_midnight_utc(to_utc_ts(pd.Timestamp(d)))


def utc_day_end_exclusive(value: Any) -> pd.Timestamp:
    """
    Return end-exclusive boundary for the day of `value`, i.e. next day 00:00Z.
    """
    return utc_day_start(value) + pd.Timedelta(days=1)
