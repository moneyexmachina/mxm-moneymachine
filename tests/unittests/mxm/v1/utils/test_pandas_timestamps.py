from __future__ import annotations

from typing import cast

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


def test_is_pd_timestamp_for_ts_ns_accepts_utc_timestamp() -> None:
    ts = pd.Timestamp("2026-03-10T08:00:00Z")

    assert is_pd_timestamp_for_ts_ns(ts)


def test_is_pd_timestamp_for_ts_ns_rejects_naive_timestamp() -> None:
    ts = pd.Timestamp("2026-03-10T08:00:00")

    assert not is_pd_timestamp_for_ts_ns(ts)


def test_is_pd_timestamp_for_ts_ns_rejects_non_utc_timestamp() -> None:
    ts = pd.Timestamp("2026-03-10T09:00:00", tz="Europe/Amsterdam")

    assert not is_pd_timestamp_for_ts_ns(ts)


def test_is_pd_timestamp_for_ts_ns_rejects_non_timestamp() -> None:
    assert not is_pd_timestamp_for_ts_ns("2026-03-10T08:00:00Z")


def test_assert_pd_timestamp_for_ts_ns_returns_valid_timestamp() -> None:
    ts = pd.Timestamp("2026-03-10T08:00:00Z")

    assert assert_pd_timestamp_for_ts_ns(ts) is ts


def test_assert_pd_timestamp_for_ts_ns_raises_for_invalid_timestamp() -> None:
    with pytest.raises(TypeError, match=r"timezone-aware UTC pd.Timestamp"):
        assert_pd_timestamp_for_ts_ns(pd.Timestamp("2026-03-10T08:00:00"))


def test_ts_ns_from_pd_timestamp_returns_explicit_ns_unit() -> None:
    out = ts_ns_from_pd_timestamp(pd.Timestamp("2026-03-10T08:00:00Z"))

    assert out == np.datetime64("2026-03-10T08:00:00.000000000", "ns")
    assert out.dtype == np.dtype("datetime64[ns]")


def test_ts_ns_from_pd_timestamp_normalises_non_utc_timestamp() -> None:
    ts = pd.Timestamp("2026-03-10T09:00:00", tz="Europe/Amsterdam")

    out = ts_ns_from_pd_timestamp(ts)

    assert out == np.datetime64("2026-03-10T08:00:00.000000000", "ns")
    assert out.dtype == np.dtype("datetime64[ns]")


def test_ts_ns_from_pd_timestamp_rejects_naive_timestamp() -> None:
    with pytest.raises(TypeError, match="Naive pandas Timestamp"):
        ts_ns_from_pd_timestamp(pd.Timestamp("2026-03-10T08:00:00"))


def test_ts_ns_from_pd_timestamp_rejects_nat() -> None:
    with pytest.raises(ValueError, match="must not be NaT"):
        ts_ns_from_pd_timestamp(cast(pd.Timestamp, pd.NaT))


def test_ts_ns_to_pd_timestamp_returns_utc_timestamp() -> None:
    ts = np.datetime64("2026-03-10T08:00:00.000000000", "ns")

    out = ts_ns_to_pd_timestamp(ts)

    assert out == pd.Timestamp("2026-03-10T08:00:00Z")
    assert is_pd_timestamp_for_ts_ns(out)


def test_ts_ns_to_pd_timestamp_rejects_non_ns_scalar() -> None:
    with pytest.raises(TypeError, match="Expected canonical MXM timestamp scalar"):
        ts_ns_to_pd_timestamp(np.datetime64("2026-03-10", "D"))


def test_ts_ns_to_pd_timestamp_rejects_nat_scalar() -> None:
    with pytest.raises(ValueError, match="must not be NaT"):
        ts_ns_to_pd_timestamp(np.datetime64("NaT", "ns"))


def test_is_pd_datetimeindex_for_ts_ns_array_accepts_utc_index() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-10T08:00:00Z",
            "2026-03-10T09:00:00Z",
        ]
    )

    assert is_pd_datetimeindex_for_ts_ns_array(idx)


def test_is_pd_datetimeindex_for_ts_ns_array_rejects_naive_index() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-10T08:00:00",
            "2026-03-10T09:00:00",
        ]
    )

    assert not is_pd_datetimeindex_for_ts_ns_array(idx)


def test_is_pd_datetimeindex_for_ts_ns_array_rejects_non_utc_index() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-10T09:00:00",
            "2026-03-10T10:00:00",
        ],
        tz="Europe/Amsterdam",
    )

    assert not is_pd_datetimeindex_for_ts_ns_array(idx)


def test_is_pd_datetimeindex_for_ts_ns_array_rejects_non_index() -> None:
    assert not is_pd_datetimeindex_for_ts_ns_array(
        [pd.Timestamp("2026-03-10T08:00:00Z")]
    )


def test_assert_pd_datetimeindex_for_ts_ns_array_returns_valid_index() -> None:
    idx = pd.DatetimeIndex(["2026-03-10T08:00:00Z"])

    assert assert_pd_datetimeindex_for_ts_ns_array(idx) is idx


def test_assert_pd_datetimeindex_for_ts_ns_array_raises_for_invalid_index() -> None:
    idx = pd.DatetimeIndex(["2026-03-10T08:00:00"])

    with pytest.raises(TypeError, match=r"timezone-aware UTC pd.DatetimeIndex"):
        assert_pd_datetimeindex_for_ts_ns_array(idx)


def test_ts_ns_array_from_pd_datetimeindex_returns_ns_array() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-10T08:00:00Z",
            "2026-03-10T09:30:00Z",
        ]
    )

    out = ts_ns_array_from_pd_datetimeindex(idx)

    expected = np.array(
        [
            "2026-03-10T08:00:00.000000000",
            "2026-03-10T09:30:00.000000000",
        ],
        dtype="datetime64[ns]",
    )
    np.testing.assert_array_equal(out, expected)
    assert out.dtype == np.dtype("datetime64[ns]")


def test_ts_ns_array_from_pd_datetimeindex_normalises_non_utc_index() -> None:
    idx = pd.DatetimeIndex(
        [
            "2026-03-10T09:00:00",
            "2026-03-10T10:30:00",
        ],
        tz="Europe/Amsterdam",
    )

    out = ts_ns_array_from_pd_datetimeindex(idx)

    expected = np.array(
        [
            "2026-03-10T08:00:00.000000000",
            "2026-03-10T09:30:00.000000000",
        ],
        dtype="datetime64[ns]",
    )
    np.testing.assert_array_equal(out, expected)
    assert out.dtype == np.dtype("datetime64[ns]")


def test_ts_ns_array_from_pd_datetimeindex_preserves_nat_duplicates_and_order() -> None:
    idx = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-03-10T09:00:00Z"),
            pd.NaT,
            pd.Timestamp("2026-03-10T08:00:00Z"),
            pd.Timestamp("2026-03-10T08:00:00Z"),
        ]
    )

    out = ts_ns_array_from_pd_datetimeindex(idx)

    expected = np.array(
        [
            "2026-03-10T09:00:00.000000000",
            "NaT",
            "2026-03-10T08:00:00.000000000",
            "2026-03-10T08:00:00.000000000",
        ],
        dtype="datetime64[ns]",
    )
    np.testing.assert_array_equal(out, expected)
    assert out.dtype == np.dtype("datetime64[ns]")


def test_ts_ns_array_from_pd_datetimeindex_rejects_naive_index() -> None:
    idx = pd.DatetimeIndex(["2026-03-10T08:00:00"])

    with pytest.raises(TypeError, match="Naive pandas DatetimeIndex"):
        ts_ns_array_from_pd_datetimeindex(idx)


def test_ts_ns_array_to_pd_datetimeindex_returns_utc_index() -> None:
    arr = np.array(
        [
            "2026-03-10T08:00:00.000000000",
            "2026-03-10T09:30:00.000000000",
        ],
        dtype="datetime64[ns]",
    )

    out = ts_ns_array_to_pd_datetimeindex(arr)

    expected = pd.DatetimeIndex(
        [
            "2026-03-10T08:00:00Z",
            "2026-03-10T09:30:00Z",
        ]
    )
    pd.testing.assert_index_equal(out, expected)
    assert is_pd_datetimeindex_for_ts_ns_array(out)


def test_ts_ns_array_to_pd_datetimeindex_preserves_nat_duplicates_and_order() -> None:
    arr = np.array(
        [
            "2026-03-10T09:00:00.000000000",
            "NaT",
            "2026-03-10T08:00:00.000000000",
            "2026-03-10T08:00:00.000000000",
        ],
        dtype="datetime64[ns]",
    )

    out = ts_ns_array_to_pd_datetimeindex(arr)

    expected = pd.DatetimeIndex(
        [
            pd.Timestamp("2026-03-10T09:00:00Z"),
            pd.NaT,
            pd.Timestamp("2026-03-10T08:00:00Z"),
            pd.Timestamp("2026-03-10T08:00:00Z"),
        ]
    )
    pd.testing.assert_index_equal(out, expected)


def test_ts_ns_array_to_pd_datetimeindex_rejects_non_ns_array() -> None:
    arr = np.array(["2026-03-10", "2026-03-11"], dtype="datetime64[D]")

    with pytest.raises(TypeError, match="Expected canonical MXM timestamp array"):
        ts_ns_array_to_pd_datetimeindex(arr)
