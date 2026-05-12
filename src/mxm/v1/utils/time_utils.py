"""
MXM V1 time utilities (UTC-normalised, tz-aware, pandas-first).

Authority
---------
This module defines the **authoritative, MXM V1-wide semantics** for timestamp
parsing, coercion, normalisation, and formatting.

All MXM V1 code that handles timestamps or dates **must** use these helpers
rather than re-implementing local time logic. This includes (but is not limited
to) marketdata ingestion, trading calendars, contract selection, synthetic
assets, backtests, and reporting.

The purpose of this module is to make time handling:
- explicit,
- deterministic,
- testable,
- and free of implicit local-timezone or naïve-datetime assumptions.

Canonical internal representation
---------------------------------
1) The canonical in-memory time type is `pandas.Timestamp`, **tz-aware and in UTC**.
2) All arithmetic and comparisons must occur on UTC-normalised `pd.Timestamp`.
3) `datetime.datetime` is permitted only at system boundaries (CLI I/O, config,
   external APIs) and must be normalised immediately.

Timezone semantics
------------------
- All timestamps handled by MXM V1 are **timezone-aware**.
- All internal timestamps are **normalised to UTC**.
- Timezone-less ISO8601 strings are rejected by default.
- Any conversion or coercion is explicit and visible in code.

Canonical persisted string formats
----------------------------------
MXM V1 uses ISO8601 with a trailing 'Z' to denote UTC. Two persistence formats
are supported:

A) Control-plane timestamps (ordering / audit)
   - Format: ISO8601Z with microseconds:
       'YYYY-MM-DDTHH:MM:SS.ffffffZ'
   - Intended for:
       - run ordering
       - audit trails
       - watermarks where sub-second stability is useful

B) Day-aligned domain surfaces
   - Format: ISO8601Z at UTC midnight, second resolution:
       'YYYY-MM-DDT00:00:00Z'
   - Intended for:
       - lifecycle boundaries
       - interest / expected windows
       - activation / expiration surfaces
   - Invariant:
       - these timestamps must be UTC-midnight aligned

Parsing & accepted inputs
-------------------------
The coercion helpers in this module accept:

- `pandas.Timestamp`
- `datetime.datetime`
- ISO8601 strings with an explicit timezone designator
  (e.g. trailing 'Z' or '+00:00')
- integer nanoseconds since UNIX epoch

All accepted inputs are normalised to tz-aware UTC `pd.Timestamp`.

Helper functions (time primitives)
----------------------------------
This module provides **time primitives**, not domain semantics.

Included helpers cover:

- Coercion / normalisation:
    * `to_utc_ts(x)`          → pd.Timestamp (tz-aware UTC)
    * `to_utc_day(ts)`        → pd.Timestamp (UTC midnight)
    * `ensure_midnight_utc`   → assert UTC-midnight alignment

- Parsing / formatting:
    * `parse_ts(s)`           → pd.Timestamp (UTC)
    * `fmt_run_ts(ts)`        → ISO8601Z microseconds string
    * `fmt_day_ts(ts)`        → ISO8601Z midnight string

- Time arithmetic:
    * `add_days(ts, n)`       → pd.Timestamp shifted by n days
    * `ceil_to_utc_day(ts)`   → next UTC-midnight if not already aligned

- Pandas helpers:
    * `ensure_utc_datetimeindex(idx)`
    * `ensure_utc_datetime_series(s)`

- Small, explicit durations:
    * `parse_duration(s)`     → datetime.timedelta

Non-goals
---------
This module deliberately does **not** define:

- trading calendars or session logic
- exchange-specific cutoffs or intraday semantics
- dataset completeness rules
- contract lifecycle inference

Those concepts belong in their respective domain modules and are built on top
of the primitives defined here.
"""

from __future__ import annotations

# mxm/v1/utils/time_utils.py

import re
from datetime import UTC, datetime, timedelta
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
            value if value.tzinfo is not None else value.replace(tzinfo=UTC)
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
    dt = t.to_pydatetime().astimezone(UTC).replace(microsecond=0)
    return dt.strftime(ISO_Z_SECONDS)


def fmt_day_ts(ts: UtcTimestampInput) -> str:
    """
    Format a day-aligned UTC timestamp as 'YYYY-MM-DDT00:00:00Z'.

    The input must be UTC-midnight aligned.
    """
    t = ensure_midnight_utc(ts)
    return t.to_pydatetime().astimezone(UTC).strftime(ISO_Z_SECONDS)


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
