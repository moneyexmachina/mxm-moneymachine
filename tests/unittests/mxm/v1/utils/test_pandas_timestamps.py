"""
Tests for mxm.v1.utils.pandas_timestamps.

These tests lock down the pandas boundary adapter for the canonical MXM
timestamp model:

- pandas normal-form predicates and assertions
- scalar pandas <-> canonical timestamp bridges
- DatetimeIndex <-> canonical timestamp array bridges
- timezone normalization policy
- NaT preservation
- duplicate preservation
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mxm.v1.utils.pandas_timestamps import (
    assert_pd_datetimeindex_for_ts_ns_array,
    assert_pd_timestamp_for_ts_ns,
    is_pd_datetimeindex_for_ts_ns_array,
    is_pd_timestamp_for_ts_ns,
    ts_ns_array_from_pd_datetimeindex,
    ts_ns_array_to_pd_datetimeindex,
    ts_ns_from_pd_timestamp,
    ts_ns_to_pd_timestamp,
)
from mxm.v1.utils.timestamps import NAT_TS_NS

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ts_ns(text: str) -> np.datetime64:
    """Construct a canonical test timestamp directly."""
    return np.datetime64(text, "ns")


def _ts_ns_array(values: list[str]) -> np.ndarray:
    """Construct a canonical 1D timestamp array directly."""
    return np.array(values, dtype="datetime64[ns]")


# ---------------------------------------------------------------------------
# Pandas scalar normal-form predicates and assertions
# ---------------------------------------------------------------------------


def test_is_pd_timestamp_for_ts_ns_true_for_utc_aware_timestamp() -> None:
    ts = pd.Timestamp("2026-03-25 10:14:03.123456789", tz="UTC")
    assert is_pd_timestamp_for_ts_ns(ts)


def test_is_pd_timestamp_for_ts_ns_false_for_naive_timestamp() -> None:
    ts = pd.Timestamp("2026-03-25 10:14:03.123456789")
    assert not is_pd_timestamp_for_ts_ns(ts)


def test_is_pd_timestamp_for_ts_ns_false_for_non_utc_aware_timestamp() -> None:
    ts = pd.Timestamp("2026-03-25 11:14:03.123456789", tz="Europe/Amsterdam")
    assert not is_pd_timestamp_for_ts_ns(ts)


def test_is_pd_timestamp_for_ts_ns_false_for_non_timestamp_object() -> None:
    assert not is_pd_timestamp_for_ts_ns("2026-03-25T10:14:03.123456789Z")
    assert not is_pd_timestamp_for_ts_ns(123)
    assert not is_pd_timestamp_for_ts_ns(None)


def test_assert_pd_timestamp_for_ts_ns_returns_valid_utc_timestamp() -> None:
    ts = pd.Timestamp("2026-03-25 10:14:03.123456789", tz="UTC")
    result = assert_pd_timestamp_for_ts_ns(ts)
    assert result is ts


def test_assert_pd_timestamp_for_ts_ns_raises_for_naive_timestamp() -> None:
    ts = pd.Timestamp("2026-03-25 10:14:03.123456789")
    with pytest.raises(
        TypeError, match="Expected pandas Timestamp in approved MXM normal form"
    ):
        assert_pd_timestamp_for_ts_ns(ts)


def test_assert_pd_timestamp_for_ts_ns_raises_for_non_utc_timestamp() -> None:
    ts = pd.Timestamp("2026-03-25 11:14:03.123456789", tz="Europe/Amsterdam")
    with pytest.raises(
        TypeError, match="Expected pandas Timestamp in approved MXM normal form"
    ):
        assert_pd_timestamp_for_ts_ns(ts)


# ---------------------------------------------------------------------------
# Pandas index normal-form predicates and assertions
# ---------------------------------------------------------------------------


def test_is_pd_datetimeindex_for_ts_ns_array_true_for_utc_aware_datetimeindex() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:04.123456789",
        ],
        tz="UTC",
    )
    assert is_pd_datetimeindex_for_ts_ns_array(idx)


def test_is_pd_datetimeindex_for_ts_ns_array_false_for_naive_datetimeindex() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:04.123456789",
        ]
    )
    assert not is_pd_datetimeindex_for_ts_ns_array(idx)


def test_is_pd_datetimeindex_for_ts_ns_array_false_for_non_utc_datetimeindex() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 11:14:03.123456789",
            "2026-03-25 11:14:04.123456789",
        ],
        tz="Europe/Amsterdam",
    )
    assert not is_pd_datetimeindex_for_ts_ns_array(idx)


def test_is_pd_datetimeindex_for_ts_ns_array_false_for_non_datetimeindex_object() -> (
    None
):
    assert not is_pd_datetimeindex_for_ts_ns_array(["2026-03-25"])
    assert not is_pd_datetimeindex_for_ts_ns_array(None)


def test_is_pd_datetimeindex_for_ts_ns_array_allows_duplicates() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:03.123456789",
        ],
        tz="UTC",
    )
    assert is_pd_datetimeindex_for_ts_ns_array(idx)


def test_is_pd_datetimeindex_for_ts_ns_array_allows_nat() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            pd.NaT,
        ],
        tz="UTC",
    )
    assert is_pd_datetimeindex_for_ts_ns_array(idx)


def test_assert_pd_datetimeindex_for_ts_ns_array_returns_valid_index() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:04.123456789",
        ],
        tz="UTC",
    )
    result = assert_pd_datetimeindex_for_ts_ns_array(idx)
    assert result is idx


def test_assert_pd_datetimeindex_for_ts_ns_array_raises_for_naive_index() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:04.123456789",
        ]
    )
    with pytest.raises(
        TypeError, match="Expected pandas DatetimeIndex in approved MXM normal form"
    ):
        assert_pd_datetimeindex_for_ts_ns_array(idx)


def test_assert_pd_datetimeindex_for_ts_ns_array_raises_for_non_utc_index() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 11:14:03.123456789",
            "2026-03-25 11:14:04.123456789",
        ],
        tz="Europe/Amsterdam",
    )
    with pytest.raises(
        TypeError, match="Expected pandas DatetimeIndex in approved MXM normal form"
    ):
        assert_pd_datetimeindex_for_ts_ns_array(idx)


# ---------------------------------------------------------------------------
# Scalar bridge: canonical -> pandas
# ---------------------------------------------------------------------------


def test_ts_ns_to_pd_timestamp_returns_utc_aware_timestamp() -> None:
    ts = _ts_ns("2026-03-25T10:14:03.123456789")
    pd_ts = ts_ns_to_pd_timestamp(ts)

    assert isinstance(pd_ts, pd.Timestamp)
    assert is_pd_timestamp_for_ts_ns(pd_ts)
    assert pd_ts == pd.Timestamp("2026-03-25 10:14:03.123456789", tz="UTC")


def test_ts_ns_to_pd_timestamp_round_trip() -> None:
    ts = _ts_ns("2026-03-25T10:14:03.123456789")
    pd_ts = ts_ns_to_pd_timestamp(ts)
    ts_back = ts_ns_from_pd_timestamp(pd_ts)

    assert ts_back == ts


def test_ts_ns_to_pd_timestamp_raises_for_nat() -> None:
    with pytest.raises(ValueError, match="must not be NaT"):
        ts_ns_to_pd_timestamp(NAT_TS_NS)


def test_ts_ns_to_pd_timestamp_raises_for_wrong_datetime_unit() -> None:
    ts_day = np.datetime64("2026-03-25", "D")
    with pytest.raises(
        TypeError,
        match=r"Expected canonical MXM timestamp scalar|Expected np\.datetime64\[ns\]",
    ):
        ts_ns_to_pd_timestamp(ts_day)


# ---------------------------------------------------------------------------
# Scalar bridge: pandas -> canonical
# ---------------------------------------------------------------------------


def test_ts_ns_from_pd_timestamp_converts_utc_timestamp() -> None:
    pd_ts = pd.Timestamp("2026-03-25 10:14:03.123456789", tz="UTC")
    ts = ts_ns_from_pd_timestamp(pd_ts)

    assert ts == _ts_ns("2026-03-25T10:14:03.123456789")


def test_ts_ns_from_pd_timestamp_converts_non_utc_timestamp_via_utc_normalization() -> (
    None
):
    pd_ts = pd.Timestamp("2026-03-25 11:14:03.123456789", tz="Europe/Amsterdam")
    ts = ts_ns_from_pd_timestamp(pd_ts)

    assert ts == _ts_ns("2026-03-25T10:14:03.123456789")


def test_ts_ns_from_pd_timestamp_rejects_naive_timestamp() -> None:
    pd_ts = pd.Timestamp("2026-03-25 10:14:03.123456789")
    with pytest.raises(
        TypeError, match="Naive pandas Timestamp values are not allowed"
    ):
        ts_ns_from_pd_timestamp(pd_ts)


def test_ts_ns_from_pd_timestamp_raises_for_nat() -> None:
    with pytest.raises(ValueError, match="must not be NaT"):
        ts_ns_from_pd_timestamp(pd.NaT)


# ---------------------------------------------------------------------------
# Array bridge: canonical -> pandas
# ---------------------------------------------------------------------------


def test_ts_ns_array_to_pd_datetimeindex_returns_utc_aware_index() -> None:
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:04.123456789",
        ]
    )
    idx = ts_ns_array_to_pd_datetimeindex(arr)

    assert isinstance(idx, pd.DatetimeIndex)
    assert is_pd_datetimeindex_for_ts_ns_array(idx)
    expected = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:04.123456789",
        ],
        tz="UTC",
    )
    pd.testing.assert_index_equal(idx, expected)


def test_ts_ns_array_to_pd_datetimeindex_round_trip() -> None:
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:04.123456789",
        ]
    )
    idx = ts_ns_array_to_pd_datetimeindex(arr)
    arr_back = ts_ns_array_from_pd_datetimeindex(idx)

    assert np.array_equal(arr_back, arr)


def test_ts_ns_array_to_pd_datetimeindex_preserves_duplicates() -> None:
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:03.123456789",
        ]
    )
    idx = ts_ns_array_to_pd_datetimeindex(arr)

    expected = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:03.123456789",
        ],
        tz="UTC",
    )
    pd.testing.assert_index_equal(idx, expected)


def test_ts_ns_array_to_pd_datetimeindex_preserves_nat() -> None:
    arr = np.array(
        [
            np.datetime64("2026-03-25T10:14:03.123456789", "ns"),
            np.datetime64("NaT", "ns"),
        ],
        dtype="datetime64[ns]",
    )
    idx = ts_ns_array_to_pd_datetimeindex(arr)

    assert pd.isna(idx[1])


def test_ts_ns_array_to_pd_datetimeindex_raises_for_wrong_datetime_unit() -> None:
    arr = np.array(["2026-03-25", "2026-03-26"], dtype="datetime64[D]")
    with pytest.raises(TypeError, match="Expected canonical MXM timestamp array"):
        ts_ns_array_to_pd_datetimeindex(arr)


# ---------------------------------------------------------------------------
# Array bridge: pandas -> canonical
# ---------------------------------------------------------------------------


def test_ts_ns_array_from_pd_datetimeindex_converts_utc_index() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:04.123456789",
        ],
        tz="UTC",
    )
    arr = ts_ns_array_from_pd_datetimeindex(idx)

    expected = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:04.123456789",
        ]
    )
    assert np.array_equal(arr, expected)


def test_ts_ns_array_from_pd_datetimeindex_converts_non_utc_index_via_utc_normalization() -> (
    None
):
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 11:14:03.123456789",
            "2026-03-25 11:14:04.123456789",
        ],
        tz="Europe/Amsterdam",
    )
    arr = ts_ns_array_from_pd_datetimeindex(idx)

    expected = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:04.123456789",
        ]
    )
    assert np.array_equal(arr, expected)


def test_ts_ns_array_from_pd_datetimeindex_rejects_naive_index() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:04.123456789",
        ]
    )
    with pytest.raises(
        TypeError, match="Naive pandas DatetimeIndex values are not allowed"
    ):
        ts_ns_array_from_pd_datetimeindex(idx)


def test_ts_ns_array_from_pd_datetimeindex_preserves_duplicates() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:03.123456789",
        ],
        tz="UTC",
    )
    arr = ts_ns_array_from_pd_datetimeindex(idx)

    expected = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:03.123456789",
        ]
    )
    assert np.array_equal(arr, expected)


def test_ts_ns_array_from_pd_datetimeindex_preserves_nat() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            pd.NaT,
        ],
        tz="UTC",
    )
    arr = ts_ns_array_from_pd_datetimeindex(idx)

    assert np.isnat(arr[1])


# ---------------------------------------------------------------------------
# Round-trip tests for approved pandas normal form
# ---------------------------------------------------------------------------


def test_pd_timestamp_normal_form_round_trip() -> None:
    pd_ts = pd.Timestamp("2026-03-25 10:14:03.123456789", tz="UTC")
    ts = ts_ns_from_pd_timestamp(pd_ts)
    pd_ts_back = ts_ns_to_pd_timestamp(ts)

    assert is_pd_timestamp_for_ts_ns(pd_ts_back)
    assert pd_ts_back == pd_ts


def test_pd_datetimeindex_normal_form_round_trip() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-25 10:14:03.123456789",
            "2026-03-25 10:14:04.123456789",
        ],
        tz="UTC",
    )
    arr = ts_ns_array_from_pd_datetimeindex(idx)
    idx_back = ts_ns_array_to_pd_datetimeindex(arr)

    assert is_pd_datetimeindex_for_ts_ns_array(idx_back)
    pd.testing.assert_index_equal(idx_back, idx)
