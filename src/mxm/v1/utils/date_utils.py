from __future__ import annotations

from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd

from mxm.v1.utils.time_utils import ensure_midnight_utc, parse_ts, to_utc_ts


def ensure_1d_day_array(
    arr: np.ndarray,
    name: str = "days",
    *,
    allow_empty: bool = False,
) -> np.ndarray:
    """
    Ensure `arr` is a 1D numpy array of dtype datetime64[D] and strictly increasing.

    This is the canonical validator for MXM V1 "day label" arrays such as
    trading-session labels.

    Rules:
      - Must be 1D
      - Must be datetime64 kind
      - Cast to datetime64[D]
      - Must be non-empty unless `allow_empty=True`
      - Must be strictly increasing (sorted, unique)

    Returns:
      - A `datetime64[D]` array view/copy (`astype`) satisfying the above invariants.
    """
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1D, got shape {arr.shape}")
    if arr.dtype.kind != "M":
        raise TypeError(f"{name} must be datetime64 dtype, got {arr.dtype!r}")

    out = arr.astype("datetime64[D]")

    if out.size == 0 and not allow_empty:
        raise ValueError(f"{name} must be non-empty")

    # Monotonic strictly increasing
    if out.size >= 2 and np.any(out[1:] <= out[:-1]):
        raise ValueError(f"{name} must be strictly increasing (sorted, unique)")

    return out


def searchsorted_exact(days: np.ndarray, value: Any) -> int | None:
    """
    Return the index of `value` in a sorted unique day-label array, else None.

    Parameters
    ----------
    days:
        1D array of dtype datetime64[D], sorted strictly increasing.
    value:
        A day-like value coercible by `coerce_np_day`.

    Returns
    -------
    int | None
        Index if present, else None.
    """
    d = coerce_np_day(value)
    i = int(np.searchsorted(days, d, side="left"))
    if i < days.size and days[i] == d:
        return i
    return None


def coerce_np_day(value: Any) -> np.datetime64:
    """
    Coerce a date-like input into numpy datetime64[D].

    Accepted:
      - datetime.date
      - datetime.datetime
      - numpy.datetime64
      - str:
          * 'YYYY-MM-DD'
          * ISO8601 timestamp with explicit timezone (via parse_ts)

    Notes:
      - All timestamp strings are interpreted in UTC before day extraction.
      - Returned value is a pure day label (datetime64[D]).
    """
    if value is None:
        raise TypeError("day value is None")

    if isinstance(value, np.datetime64):
        return value.astype("datetime64[D]")

    if isinstance(value, datetime):
        value = value.date()

    if isinstance(value, date):
        return np.datetime64(value).astype("datetime64[D]")

    if isinstance(value, str):
        s = value.strip()
        # Fast-path: YYYY-MM-DD
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return np.datetime64(s).astype("datetime64[D]")

        # Otherwise: timestamp string (must be tz-aware)
        ts = parse_ts(s)  # UTC pd.Timestamp
        return np.datetime64(ts.date()).astype("datetime64[D]")

    raise TypeError(f"unsupported day type: {type(value).__name__} value={value!r}")


def coerce_date(value: Any) -> date:
    """
    Coerce a date-like input into a datetime.date.

    Accepted:
      - datetime.date
      - datetime.datetime
      - numpy.datetime64
      - pandas.Timestamp
      - str: 'YYYY-MM-DD' or ISO8601 timestamp
    """
    if value is None:
        raise TypeError("date value is None")

    if isinstance(value, date) and not isinstance(value, datetime):
        return value

    if isinstance(value, np.datetime64):
        # Coerce to day label first, then parse as ISO date.
        # Handles datetime64 with any unit (D, ns, etc) deterministically.
        s = str(value.astype("datetime64[D]"))
        return date.fromisoformat(s)

    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, pd.Timestamp):
        return value.date()

    if isinstance(value, str):
        s = value.strip()
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return date.fromisoformat(s)

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


def fmt_iso_day(value: Any) -> str:
    """
    Format a day-like value as 'YYYY-MM-DD'.

    Accepts anything coercible by `coerce_np_day`.
    """
    d = coerce_np_day(value)
    return str(d.astype("datetime64[D]"))


def day_in_set(value: Any, days: set[np.datetime64]) -> bool:
    """
    Test whether a day-like value is present in a set of day labels.

    The input is coerced to datetime64[D] before membership testing.
    """
    d = coerce_np_day(value)
    return d in days
