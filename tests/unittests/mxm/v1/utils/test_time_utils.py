# tests/unittests/mxm/v1/utils/test_time_utils.py
from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from mxm.v1.utils.time_utils import (
    ISO_Z_MICROS,
    ISO_Z_SECONDS,
    add_days,
    ensure_midnight_utc,
    fmt_day_ts,
    fmt_run_ts,
    fmt_second_ts,
    parse_duration,
    parse_ts,
    to_utc_day,
    to_utc_ts,
)

# -------------------------
# parse_duration
# -------------------------


@pytest.mark.parametrize(
    ("s", "expected"),
    [
        ("0s", 0),
        ("30s", 30),
        ("15m", 15 * 60),
        ("1h", 60 * 60),
        ("1d", 24 * 60 * 60),
        ("-5s", -5),
        ("  10s ", 10),
    ],
)
def test_parse_duration_seconds_equivalence(s: str, expected: int) -> None:
    td = parse_duration(s)
    assert int(td.total_seconds()) == expected


@pytest.mark.parametrize("s", ["", "10", "10sec", "1w", "1.5h", "ms", "s", "1 h"])
def test_parse_duration_rejects_invalid(s: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(s)


# -------------------------
# to_utc_ts
# -------------------------


def test_to_utc_ts_from_timestamp_naive_localizes_utc() -> None:
    t = pd.Timestamp("2026-01-01 12:00:00")  # naive
    out = to_utc_ts(t)
    assert isinstance(out, pd.Timestamp)
    assert out.tzinfo is not None
    assert out.tz_convert("UTC") == out
    assert out.isoformat() == "2026-01-01T12:00:00+00:00"


def test_to_utc_ts_from_timestamp_aware_converts_to_utc() -> None:
    # CET winter is +01:00
    t = pd.Timestamp("2026-01-01 12:00:00+01:00")
    out = to_utc_ts(t)
    assert out.isoformat() == "2026-01-01T11:00:00+00:00"


def test_to_utc_ts_from_datetime_naive_interprets_as_utc() -> None:
    dt = datetime(2026, 1, 1, 12, 0, 0)  # naive
    out = to_utc_ts(dt)
    assert out.isoformat() == "2026-01-01T12:00:00+00:00"


def test_to_utc_ts_from_datetime_aware_converts_to_utc() -> None:
    dt = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    out = to_utc_ts(dt)
    assert out.isoformat() == "2026-01-01T12:00:00+00:00"


def test_to_utc_ts_rejects_timezone_less_string() -> None:
    with pytest.raises(ValueError):
        to_utc_ts("2026-01-01T12:00:00")


def test_parse_ts_rejects_timezone_less_string() -> None:
    with pytest.raises(ValueError):
        parse_ts("2026-01-01T12:00:00")


@pytest.mark.parametrize(
    "s",
    [
        "2026-01-01T12:00:00Z",
        "2026-01-01T12:00:00.123456Z",
        "2026-01-01T12:00:00.123456789Z",  # nanos
        "2026-01-01T12:00:00+00:00",
    ],
)
def test_to_utc_ts_from_string_accepts_iso_variants(s: str) -> None:
    out = to_utc_ts(s)
    assert out.tzinfo is not None
    assert out.tz_convert("UTC") == out


def test_to_utc_ts_from_ns_epoch_is_utc() -> None:
    # 1970-01-01T00:00:01Z in ns
    out = to_utc_ts(1_000_000_000)
    assert out.isoformat() == "1970-01-01T00:00:01+00:00"


def test_to_utc_ts_rejects_negative_ns_epoch() -> None:
    with pytest.raises(ValueError):
        to_utc_ts(-1)


# -------------------------
# ensure_midnight_utc / to_utc_day
# -------------------------


def test_ensure_midnight_utc_accepts_midnight() -> None:
    out = ensure_midnight_utc("2026-01-01T00:00:00Z")
    assert out.isoformat() == "2026-01-01T00:00:00+00:00"


def test_ensure_midnight_utc_rejects_non_midnight() -> None:
    with pytest.raises(ValueError):
        ensure_midnight_utc("2026-01-01T00:00:01Z")


def test_to_utc_day_floors_to_midnight() -> None:
    out = to_utc_day("2026-01-01T12:34:56Z")
    assert out.isoformat() == "2026-01-01T00:00:00+00:00"


# -------------------------
# parse_ts
# -------------------------


def test_parse_ts_returns_utc_timestamp() -> None:
    out = parse_ts("2026-01-01T12:00:00Z")
    assert isinstance(out, pd.Timestamp)
    assert out.isoformat() == "2026-01-01T12:00:00+00:00"


# -------------------------
# formatting helpers
# -------------------------


def test_fmt_run_ts_microseconds_format() -> None:
    ts = pd.Timestamp("2026-01-01T12:00:00.123456789Z")
    s = fmt_run_ts(ts)
    # microsecond precision, ends in Z
    assert s.endswith("Z")
    assert "." in s
    # round-trip parse should succeed
    dt = datetime.strptime(s, ISO_Z_MICROS)
    assert (
        dt.tzinfo is None
    )  # strptime produces naive; module doc defines as UTC by convention


def test_fmt_second_ts_truncates_to_seconds() -> None:
    ts = pd.Timestamp("2026-01-01T12:00:00.987654Z")
    s = fmt_second_ts(ts)
    assert s == "2026-01-01T12:00:00Z"
    # strict format
    datetime.strptime(s, ISO_Z_SECONDS)


def test_fmt_day_ts_requires_midnight() -> None:
    with pytest.raises(ValueError):
        fmt_day_ts("2026-01-01T00:00:01Z")


def test_fmt_day_ts_outputs_midnight_seconds_format() -> None:
    s = fmt_day_ts("2026-01-01T00:00:00Z")
    assert s == "2026-01-01T00:00:00Z"
    datetime.strptime(s, ISO_Z_SECONDS)


# -------------------------
# add_days
# -------------------------


def test_add_days_preserves_utc_and_shifts() -> None:
    ts = pd.Timestamp("2026-01-01T12:00:00Z")
    out = add_days(ts, 2)
    assert out.isoformat() == "2026-01-03T12:00:00+00:00"
    assert out.tz_convert("UTC") == out
