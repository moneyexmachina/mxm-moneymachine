from __future__ import annotations

from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest

from mxm.v1.utils.date_utils import (
    coerce_date,
    coerce_np_day,
    day_in_set,
    ensure_1d_day_array,
    fmt_iso_day,
    searchsorted_exact,
    utc_day_end_exclusive,
    utc_day_start,
)

# ---------------------------------------------------------------------
# ensure_1d_day_array
# ---------------------------------------------------------------------


def test_ensure_1d_day_array_casts_to_day_dtype() -> None:
    arr = np.array(
        ["2026-01-01T12:00:00", "2026-01-02T00:00:00"],
        dtype="datetime64[ns]",
    )
    out = ensure_1d_day_array(arr, name="x")
    assert out.dtype == np.dtype("datetime64[D]")
    assert out.tolist() == [np.datetime64("2026-01-01"), np.datetime64("2026-01-02")]


def test_ensure_1d_day_array_requires_1d() -> None:
    arr = np.array([["2026-01-01"], ["2026-01-02"]], dtype="datetime64[D]")
    with pytest.raises(ValueError, match="must be 1D"):
        ensure_1d_day_array(arr, name="x")


def test_ensure_1d_day_array_requires_datetime64_dtype() -> None:
    arr = np.array([1, 2, 3], dtype=int)
    with pytest.raises(TypeError, match="must be datetime64"):
        ensure_1d_day_array(arr, name="x")


def test_ensure_1d_day_array_rejects_empty_by_default() -> None:
    arr = np.array([], dtype="datetime64[D]")
    with pytest.raises(ValueError, match="must be non-empty"):
        ensure_1d_day_array(arr, name="x")


def test_ensure_1d_day_array_allows_empty_if_flag_set() -> None:
    arr = np.array([], dtype="datetime64[D]")
    out = ensure_1d_day_array(arr, name="x", allow_empty=True)
    assert out.dtype == np.dtype("datetime64[D]")
    assert out.size == 0


def test_ensure_1d_day_array_requires_strictly_increasing() -> None:
    arr = np.array(
        ["2026-01-02", "2026-01-02"],  # duplicate
        dtype="datetime64[D]",
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        ensure_1d_day_array(arr, name="x")

    arr2 = np.array(
        ["2026-01-03", "2026-01-02"],  # decreasing
        dtype="datetime64[D]",
    )
    with pytest.raises(ValueError, match="strictly increasing"):
        ensure_1d_day_array(arr2, name="x")


# ---------------------------------------------------------------------
# coerce_np_day
# ---------------------------------------------------------------------


def test_coerce_np_day_accepts_date_and_datetime() -> None:
    assert coerce_np_day(date(2026, 1, 2)) == np.datetime64("2026-01-02")
    assert coerce_np_day(datetime(2026, 1, 2, 12, 0, 0)) == np.datetime64("2026-01-02")


def test_coerce_np_day_accepts_np_datetime64_any_unit() -> None:
    assert coerce_np_day(np.datetime64("2026-01-02")) == np.datetime64("2026-01-02")
    assert coerce_np_day(np.datetime64("2026-01-02T12:34:56")) == np.datetime64(
        "2026-01-02"
    )


def test_coerce_np_day_accepts_date_string() -> None:
    assert coerce_np_day("2026-01-02") == np.datetime64("2026-01-02")


def test_coerce_np_day_accepts_tz_aware_timestamp_string_and_uses_utc_date() -> None:
    # 2026-01-02 00:30 in +01:00 is 2026-01-01 23:30Z => UTC date is 2026-01-01
    assert coerce_np_day("2026-01-02T00:30:00+01:00") == np.datetime64("2026-01-01")


def test_coerce_np_day_rejects_none_and_unknown_type() -> None:
    with pytest.raises(TypeError, match="is None"):
        coerce_np_day(None)

    with pytest.raises(TypeError, match="unsupported day type"):
        coerce_np_day(123)


# ---------------------------------------------------------------------
# coerce_date
# ---------------------------------------------------------------------


def test_coerce_date_accepts_date_datetime_timestamp() -> None:
    assert coerce_date(date(2026, 1, 2)) == date(2026, 1, 2)
    assert coerce_date(datetime(2026, 1, 2, 12, 0, 0)) == date(2026, 1, 2)
    assert coerce_date(pd.Timestamp("2026-01-02T12:00:00Z")) == date(2026, 1, 2)


def test_coerce_date_accepts_np_datetime64_any_unit() -> None:
    assert coerce_date(np.datetime64("2026-01-02")) == date(2026, 1, 2)
    assert coerce_date(np.datetime64("2026-01-02T23:59:59")) == date(2026, 1, 2)


def test_coerce_date_accepts_date_string() -> None:
    assert coerce_date("2026-01-02") == date(2026, 1, 2)


def test_coerce_date_accepts_tz_aware_timestamp_string_and_uses_utc_date() -> None:
    # Same UTC-date semantics as coerce_np_day via parse_ts
    assert coerce_date("2026-01-02T00:30:00+01:00") == date(2026, 1, 1)


def test_coerce_date_rejects_none_and_unknown_type() -> None:
    with pytest.raises(TypeError, match="is None"):
        coerce_date(None)

    with pytest.raises(TypeError, match="unsupported date type"):
        coerce_date(123)


# ---------------------------------------------------------------------
# searchsorted_exact
# ---------------------------------------------------------------------


def test_searchsorted_exact_finds_present_and_returns_none_if_missing() -> None:
    days = np.array(
        ["2026-01-01", "2026-01-02", "2026-01-03"],
        dtype="datetime64[D]",
    )
    assert searchsorted_exact(days, "2026-01-01") == 0
    assert searchsorted_exact(days, np.datetime64("2026-01-02")) == 1
    assert searchsorted_exact(days, date(2026, 1, 3)) == 2
    assert searchsorted_exact(days, "2026-01-04") is None


# ---------------------------------------------------------------------
# utc_day_start / utc_day_end_exclusive
# ---------------------------------------------------------------------


def test_utc_day_start_returns_utc_midnight() -> None:
    ts = utc_day_start("2026-01-02")
    assert isinstance(ts, pd.Timestamp)
    assert ts.isoformat() == "2026-01-02T00:00:00+00:00"


def test_utc_day_start_accepts_np_datetime64() -> None:
    ts = utc_day_start(np.datetime64("2026-01-02"))
    assert ts.isoformat() == "2026-01-02T00:00:00+00:00"


def test_utc_day_end_exclusive_is_next_midnight() -> None:
    end = utc_day_end_exclusive("2026-01-02")
    assert end.isoformat() == "2026-01-03T00:00:00+00:00"


# ---------------------------------------------------------------------
# fmt_iso_day
# ---------------------------------------------------------------------


def test_fmt_iso_day_formats_day_like_values() -> None:
    assert fmt_iso_day("2026-01-02") == "2026-01-02"
    assert fmt_iso_day(datetime(2026, 1, 2, 12, 0, 0, tzinfo=UTC)) == "2026-01-02"
    assert fmt_iso_day(np.datetime64("2026-01-02T23:59:59")) == "2026-01-02"


# ---------------------------------------------------------------------
# day_in_set
# ---------------------------------------------------------------------


def test_day_in_set_coerces_and_tests_membership() -> None:
    days = {np.datetime64("2026-01-02"), np.datetime64("2026-01-03")}
    assert day_in_set("2026-01-02", days) is True
    assert day_in_set(date(2026, 1, 3), days) is True
    assert day_in_set(np.datetime64("2026-01-04"), days) is False
