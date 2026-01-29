# mxm/v1/marketdata/time_utils.py
from __future__ import annotations

"""
MXM marketdata time utilities (UTC + canonical ISO8601Z + pandas-first).

Authority
---------
This module is the single source of truth for timestamp parsing, formatting, and
normalisation within `mxm.v1.marketdata`. All other marketdata code must use
these helpers rather than re-implementing local timestamp logic.

Canonical internal representation
---------------------------------
1) The canonical in-memory time type is `pandas.Timestamp` with tz-aware UTC.
2) All arithmetic and comparisons must occur on UTC-normalised `pd.Timestamp`.
3) `datetime.datetime` is permitted only at boundaries (e.g. CLI I/O) and must be
   normalised into `pd.Timestamp` immediately.

Canonical persisted string formats
----------------------------------
This codebase uses ISO8601 with a trailing 'Z' to denote UTC. We deliberately
separate two persistence formats:

A) Control-plane timestamps (run ordering / audit)
   - Format: ISO8601Z with microseconds:
       'YYYY-MM-DDTHH:MM:SS.ffffffZ'
   - Examples:
       '2026-01-27T10:54:09.082336Z'
   - Used for:
       - orchestrator `run_ts_utc`
       - watermarks / ordering fields where sub-second stability is beneficial

B) Day-aligned surfaces (domain windows)
   - Format: ISO8601Z at UTC midnight, second resolution:
       'YYYY-MM-DDT00:00:00Z'
   - Used for:
       - interest_start / interest_end
       - dataset_start / dataset_end
       - activation_floor / expiration_ceiling
       - expected_start / expected_end
   - Invariant:
       - these values must be UTC-midnight aligned

Vendor representations
----------------------
Databento may return ISO8601Z strings with nanosecond precision, e.g.
'2022-01-03T00:00:00.000000000Z'. This module shall accept such inputs and
normalise them to `pd.Timestamp` (UTC). Domain surfaces remain day-aligned and
are persisted at second precision; bar data timestamps remain high-fidelity in
parquet and are not degraded to strings.

Helper functions (transformers)
-------------------------------
The helpers in this module implement the following transformations:

- Coercion / normalisation:
    * `to_utc_ts(x)`        -> pd.Timestamp (tz-aware UTC)
    * `to_utc_day(ts)`      -> pd.Timestamp (UTC midnight)
    * `ensure_midnight(ts)` -> asserts UTC-midnight alignment

- Parsing / formatting:
    * `fmt_run_ts(ts)`      -> ISO8601Z microseconds string
    * `fmt_day_ts(ts)`      -> ISO8601Z midnight string ('...T00:00:00Z')
    * `parse_ts(s)`         -> pd.Timestamp (UTC) from ISO8601 string (any precision)

- Window stepping:
    * `add_days(ts, n)`     -> pd.Timestamp shifted by n days (preserves tz)
    * `parse_duration(s)`   -> datetime.timedelta for strict, small durations

Non-goals
---------
- This module does not define dataset-specific semantics such as trading
  calendars, daily-bar completeness rules, or contract lifecycle inference.
  Those remain in dataset modules (e.g. `datasets/ohlcv_1d/*`).
"""
import re
from datetime import datetime, timedelta, timezone
from typing import TypeAlias

import pandas as pd

# -------------------------
# Canonical input types
# -------------------------


ISO8601Z: TypeAlias = str
NsEpoch: TypeAlias = int

UtcTimestampInput: TypeAlias = pd.Timestamp | datetime | ISO8601Z | NsEpoch


# -------------------------
# Canonical format strings
# -------------------------

ISO_Z_MICROS = "%Y-%m-%dT%H:%M:%S.%fZ"
ISO_Z_SECONDS = "%Y-%m-%dT%H:%M:%SZ"
_DURATION_RE = re.compile(r"^\s*(?P<value>-?\d+)(?P<unit>ms|s|m|h|d)\s*$")


# Accept:
#   - trailing 'Z'
#   - or an explicit offset: +HH:MM, -HH:MM, +HHMM, -HHMM, +HH, -HH
# Disallow timezone-less ISO strings.
_TZ_SUFFIX_RE = re.compile(r"(Z|[+-]\d{2}:\d{2}|[+-]\d{2}\d{2}|[+-]\d{2})$")


def _require_timezone_in_string(value: str) -> None:
    """
    Raise ValueError unless the string has an explicit timezone designator.
    """
    v = value.strip()
    if _TZ_SUFFIX_RE.search(v) is None:
        raise ValueError(
            "Timestamp string must include an explicit timezone (trailing 'Z' or an offset like '+00:00'). "
            f"Got: {value!r}"
        )


# -------------------------
# Duration parsing (strict)
# -------------------------


def parse_duration(value: str) -> timedelta:
    """
    Parse a strict small duration string into a `datetime.timedelta`.

    Supported units:
      - 'ms' milliseconds
      - 's'  seconds
      - 'm'  minutes
      - 'h'  hours
      - 'd'  days

    The grammar is intentionally strict to prevent silent interpretation of
    ambiguous strings.

    Examples:
      - '0s'
      - '30s'
      - '15m'
      - '1h'
      - '1d'
      - '-5s'
    """
    m = _DURATION_RE.match(value)
    if m is None:
        raise ValueError(
            f"Invalid duration {value!r}. Expected formats like '30s', '15m', '1h', '1d'."
        )

    n = int(m.group("value"))
    unit = m.group("unit")

    if unit == "ms":
        return timedelta(milliseconds=n)
    if unit == "s":
        return timedelta(seconds=n)
    if unit == "m":
        return timedelta(minutes=n)
    if unit == "h":
        return timedelta(hours=n)
    if unit == "d":
        return timedelta(days=n)

    raise ValueError(f"Unsupported duration unit {unit!r} in {value!r}.")


# -------------------------
# Core: coercion to UTC
# -------------------------


def to_utc_ts(value: UtcTimestampInput) -> pd.Timestamp:
    """
    Convert a supported timestamp representation into a tz-aware UTC pd.Timestamp.

    Accepted inputs:
      - pandas.Timestamp
      - datetime.datetime
      - ISO8601Z string (any sub-second precision, must include timezone or 'Z')
      - int nanoseconds since UNIX epoch

    Raises:
      - TypeError for unsupported input types
      - ValueError for invalid values
    """
    if isinstance(value, pd.Timestamp):
        return (
            value.tz_localize("UTC")
            if value.tzinfo is None
            else value.tz_convert("UTC")
        )

    if isinstance(value, datetime):
        return pd.Timestamp(
            value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        ).tz_convert("UTC")

    if isinstance(value, str):
        _require_timezone_in_string(value)
        ts = pd.Timestamp(value)
        return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")

    if value < 0:  # must be int then.
        raise ValueError(f"nanoseconds timestamp must be >= 0, got {value}")
    return pd.Timestamp(value, tz="UTC")


def ensure_midnight_utc(value: UtcTimestampInput) -> pd.Timestamp:
    """
    Require that the timestamp represents UTC midnight (00:00:00).
    """
    ts = to_utc_ts(value)
    if not (ts.hour == 0 and ts.minute == 0 and ts.second == 0 and ts.microsecond == 0):
        raise ValueError(f"Expected UTC-midnight timestamp, got {ts.isoformat()}")
    return ts


def to_utc_day(value: UtcTimestampInput) -> pd.Timestamp:
    """
    Convert input to UTC and floor to UTC midnight of the same day.
    """
    return to_utc_ts(value).normalize()


def parse_ts(value: str) -> pd.Timestamp:
    """
    Parse an ISO8601 timestamp string (any precision) into UTC `pd.Timestamp`.

    This accepts:
      - '...Z' with seconds/micros/nanos
      - offsets like '+00:00'
      - pandas-parseable ISO variants

    Returns tz-aware UTC `pd.Timestamp`.
    """
    # direct: value is already a supported UtcTimestampInput member (str)
    return to_utc_ts(value)


def fmt_run_ts(ts: UtcTimestampInput) -> str:
    """
    Format a UTC timestamp as ISO8601Z with microseconds.

    Intended for control-plane ordering/audit fields (e.g. run_ts_utc).

    Notes:
      - pandas stores ns; strftime truncates to micros, which is acceptable for control-plane.
    """
    t = to_utc_ts(ts)
    return t.strftime(ISO_Z_MICROS)


def utc_now_ts() -> pd.Timestamp:
    """
    Return current time as tz-aware UTC pd.Timestamp.

    This is the canonical "now" for in-memory logic.
    """
    return pd.Timestamp.now(tz="UTC")


def utc_now_run_ts() -> str:
    """
    Return the current UTC time formatted as canonical ISO8601Z with microseconds.

    This is the only approved way to generate control-plane run timestamps
    (e.g. orchestrator `run_ts_utc`).

    Format:
      'YYYY-MM-DDTHH:MM:SS.ffffffZ'
    """
    return fmt_run_ts(pd.Timestamp.now(tz="UTC"))


def fmt_second_ts(ts: UtcTimestampInput) -> str:
    """
    Format a UTC timestamp as ISO8601Z with second resolution.

    This is allowed only when precision beyond seconds is not meaningful.
    """
    t = to_utc_ts(ts)
    dt = t.to_pydatetime().astimezone(timezone.utc).replace(microsecond=0)
    return dt.strftime(ISO_Z_SECONDS)


def fmt_day_ts(ts: UtcTimestampInput) -> str:
    """
    Format a day-aligned UTC timestamp as 'YYYY-MM-DDT00:00:00Z'.

    The input must be UTC-midnight aligned.
    """
    t = ensure_midnight_utc(ts)
    return t.to_pydatetime().astimezone(timezone.utc).strftime(ISO_Z_SECONDS)


def add_days(ts: UtcTimestampInput, days: int) -> pd.Timestamp:
    """
    Add an integer number of days to `ts` (UTC-normalised).

    This is a pure timestamp shift; it does not enforce midnight alignment.
    """
    t = to_utc_ts(ts)
    return t + pd.Timedelta(days=int(days))


def ensure_utc_datetimeindex(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """
    Ensure a DatetimeIndex is tz-aware and in UTC.

    - If tz-naive: localize to UTC (no conversion)
    - If tz-aware: convert to UTC
    """
    if idx.tz is None:
        return idx.tz_localize("UTC")
    return idx.tz_convert("UTC")


def ensure_utc_datetime_series(s: pd.Series) -> pd.Series:
    """
    Ensure a Series is datetime64[ns, UTC].

    Uses pandas to_datetime with utc=True and errors='raise' to avoid silent coercions.
    """
    return pd.to_datetime(s, utc=True, errors="raise")


def ceil_to_utc_day(ts: pd.Timestamp) -> pd.Timestamp:
    t = to_utc_ts(ts)
    day = to_utc_day(t)
    return day if t == day else day + pd.Timedelta(days=1)
