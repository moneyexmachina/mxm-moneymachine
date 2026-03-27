"""
Tests for mxm.v1.utils.timestamps.

These tests lock down the canonical MXM timestamp substrate:

- scalar canonicality
- array canonicality
- NaT handling
- monotonicity
- int bridges
- string bridges
"""

from __future__ import annotations

import numpy as np
import pytest

from mxm.v1.utils.timestamps import (
    EPOCH_TS_NS,
    NAT_TS_NS,
    assert_monotonic_increasing_ts_ns_array,
    assert_no_nat,
    assert_not_nat,
    assert_ts_ns,
    assert_ts_ns_array,
    has_nat,
    is_nat,
    is_ts_ns,
    is_ts_ns_array,
    ts_ns_from_int,
    ts_ns_from_str,
    ts_ns_to_int,
    ts_ns_to_str,
)

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
# Scalar canonicality
# ---------------------------------------------------------------------------


def test_is_ts_ns_true_for_datetime64_ns_scalar() -> None:
    ts = _ts_ns("2026-03-25T10:14:03.123456789")
    assert is_ts_ns(ts)


def test_is_ts_ns_false_for_non_timestamp_object() -> None:
    assert not is_ts_ns("2026-03-25T10:14:03.123456789Z")
    assert not is_ts_ns(123)
    assert not is_ts_ns(None)


def test_is_ts_ns_false_for_wrong_datetime_unit() -> None:
    ts_day = np.datetime64("2026-03-25", "D")
    assert not is_ts_ns(ts_day)


def test_assert_ts_ns_returns_scalar_for_datetime64_ns() -> None:
    ts = _ts_ns("2026-03-25T10:14:03.123456789")
    result = assert_ts_ns(ts)
    assert result == ts


def test_assert_ts_ns_raises_for_non_timestamp_object() -> None:
    with pytest.raises(TypeError, match="Expected canonical MXM timestamp scalar"):
        assert_ts_ns("2026-03-25T10:14:03.123456789Z")


def test_assert_ts_ns_raises_for_wrong_datetime_unit() -> None:
    ts_day = np.datetime64("2026-03-25", "D")
    with pytest.raises(TypeError, match="Expected canonical MXM timestamp scalar"):
        assert_ts_ns(ts_day)


# ---------------------------------------------------------------------------
# Scalar NaT
# ---------------------------------------------------------------------------


def test_is_nat_true_for_nat_scalar() -> None:
    assert is_nat(NAT_TS_NS)


def test_is_nat_false_for_valid_scalar() -> None:
    ts = _ts_ns("2026-03-25T10:14:03.123456789")
    assert not is_nat(ts)


def test_assert_not_nat_returns_valid_scalar() -> None:
    ts = _ts_ns("2026-03-25T10:14:03.123456789")
    result = assert_not_nat(ts)
    assert result == ts


def test_assert_not_nat_raises_for_nat_scalar() -> None:
    with pytest.raises(ValueError, match="must not be NaT"):
        assert_not_nat(NAT_TS_NS)


# ---------------------------------------------------------------------------
# Array canonicality
# ---------------------------------------------------------------------------


def test_is_ts_ns_array_true_for_datetime64_ns_array() -> None:
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:04.123456789",
        ]
    )
    assert is_ts_ns_array(arr)


def test_is_ts_ns_array_false_for_non_array_object() -> None:
    assert not is_ts_ns_array("not-an-array")
    assert not is_ts_ns_array(123)
    assert not is_ts_ns_array(None)


def test_is_ts_ns_array_false_for_wrong_datetime_unit() -> None:
    arr = np.array(["2026-03-25", "2026-03-26"], dtype="datetime64[D]")
    assert not is_ts_ns_array(arr)


def test_assert_ts_ns_array_returns_array_for_datetime64_ns_array() -> None:
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:04.123456789",
        ]
    )
    result = assert_ts_ns_array(arr)
    assert result is arr


def test_assert_ts_ns_array_raises_for_non_array_object() -> None:
    with pytest.raises(TypeError, match="Expected canonical MXM timestamp array"):
        assert_ts_ns_array("not-an-array")


def test_assert_ts_ns_array_raises_for_wrong_datetime_unit() -> None:
    arr = np.array(["2026-03-25", "2026-03-26"], dtype="datetime64[D]")
    with pytest.raises(TypeError, match="Expected canonical MXM timestamp array"):
        assert_ts_ns_array(arr)


# ---------------------------------------------------------------------------
# Array NaT
# ---------------------------------------------------------------------------


def test_has_nat_false_for_clean_array() -> None:
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:04.123456789",
        ]
    )
    assert not has_nat(arr)


def test_has_nat_true_for_array_with_nat() -> None:
    arr = np.array(
        [
            np.datetime64("2026-03-25T10:14:03.123456789", "ns"),
            np.datetime64("NaT", "ns"),
        ],
        dtype="datetime64[ns]",
    )
    assert has_nat(arr)


def test_assert_no_nat_returns_clean_array() -> None:
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:04.123456789",
        ]
    )
    result = assert_no_nat(arr)
    assert result is arr


def test_assert_no_nat_raises_for_array_with_nat() -> None:
    arr = np.array(
        [
            np.datetime64("2026-03-25T10:14:03.123456789", "ns"),
            np.datetime64("NaT", "ns"),
        ],
        dtype="datetime64[ns]",
    )
    with pytest.raises(ValueError, match="must not contain NaT"):
        assert_no_nat(arr)


# ---------------------------------------------------------------------------
# Monotonicity
# ---------------------------------------------------------------------------


def test_assert_monotonic_increasing_ts_ns_array_accepts_empty_array() -> None:
    arr = np.array([], dtype="datetime64[ns]")
    result = assert_monotonic_increasing_ts_ns_array(arr)
    assert result is arr


def test_assert_monotonic_increasing_ts_ns_array_accepts_size_one_array() -> None:
    arr = _ts_ns_array(["2026-03-25T10:14:03.123456789"])
    result = assert_monotonic_increasing_ts_ns_array(arr)
    assert result is arr


def test_assert_monotonic_increasing_ts_ns_array_accepts_increasing_array() -> None:
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:04.123456789",
            "2026-03-25T10:14:05.123456789",
        ]
    )
    result = assert_monotonic_increasing_ts_ns_array(arr)
    assert result is arr


def test_assert_monotonic_increasing_ts_ns_array_accepts_equal_adjacent_values() -> (
    None
):
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:05.123456789",
        ]
    )
    result = assert_monotonic_increasing_ts_ns_array(arr)
    assert result is arr


def test_assert_monotonic_increasing_ts_ns_array_raises_for_decreasing_array() -> None:
    arr = _ts_ns_array(
        [
            "2026-03-25T10:14:03.123456789",
            "2026-03-25T10:14:05.123456789",
            "2026-03-25T10:14:04.123456789",
        ]
    )
    with pytest.raises(ValueError, match="must be monotonic increasing"):
        assert_monotonic_increasing_ts_ns_array(arr)


def test_assert_monotonic_increasing_ts_ns_array_raises_for_non_1d_array() -> None:
    arr = np.array(
        [
            [
                np.datetime64("2026-03-25T10:14:03.123456789", "ns"),
                np.datetime64("2026-03-25T10:14:04.123456789", "ns"),
            ]
        ],
        dtype="datetime64[ns]",
    )
    with pytest.raises(ValueError, match="Expected 1D timestamp array"):
        assert_monotonic_increasing_ts_ns_array(arr)


def test_assert_monotonic_increasing_ts_ns_array_raises_for_nat_array() -> None:
    arr = np.array(
        [
            np.datetime64("2026-03-25T10:14:03.123456789", "ns"),
            np.datetime64("NaT", "ns"),
        ],
        dtype="datetime64[ns]",
    )
    with pytest.raises(ValueError, match="must not contain NaT"):
        assert_monotonic_increasing_ts_ns_array(arr)


# ---------------------------------------------------------------------------
# Integer bridges
# ---------------------------------------------------------------------------


def test_ts_ns_from_int_zero_is_epoch() -> None:
    assert ts_ns_from_int(0) == EPOCH_TS_NS


@pytest.mark.parametrize(
    "epoch_ns",
    [
        0,
        1,
        -1,
        1_234_567_890,
        1_743_165_243_123_456_789,
        -1_234_567_890_123_456_789,
    ],
)
def test_int_bridge_round_trip(epoch_ns: int) -> None:
    ts = ts_ns_from_int(epoch_ns)
    assert ts_ns_to_int(ts) == epoch_ns


def test_ts_ns_from_int_rejects_bool() -> None:
    with pytest.raises(
        TypeError, match="Boolean values are not valid epoch nanoseconds"
    ):
        ts_ns_from_int(True)


def test_ts_ns_to_int_raises_for_nat() -> None:
    with pytest.raises(
        ValueError, match="NaT cannot be converted to integer epoch nanoseconds"
    ):
        ts_ns_to_int(NAT_TS_NS)


def test_ts_ns_to_int_raises_for_wrong_datetime_unit() -> None:
    ts_day = np.datetime64("2026-03-25", "D")
    with pytest.raises(TypeError, match=r"Expected np\.datetime64\[ns\]"):
        ts_ns_to_int(ts_day)


# ---------------------------------------------------------------------------
# String bridges
# ---------------------------------------------------------------------------


def test_str_bridge_round_trip() -> None:
    text = "2026-03-25T10:14:03.123456789Z"
    ts = ts_ns_from_str(text)
    assert ts_ns_to_str(ts) == text


def test_ts_ns_from_str_rejects_missing_z() -> None:
    with pytest.raises(ValueError, match="must match canonical format"):
        ts_ns_from_str("2026-03-25T10:14:03.123456789")


def test_ts_ns_from_str_rejects_non_nine_fractional_digits() -> None:
    with pytest.raises(ValueError, match="must match canonical format"):
        ts_ns_from_str("2026-03-25T10:14:03.123Z")

    with pytest.raises(ValueError, match="must match canonical format"):
        ts_ns_from_str("2026-03-25T10:14:03.12345678Z")


def test_ts_ns_from_str_rejects_offset_string() -> None:
    with pytest.raises(ValueError, match="must match canonical format"):
        ts_ns_from_str("2026-03-25T10:14:03.123456789+01:00")


def test_ts_ns_from_str_rejects_date_only_string() -> None:
    with pytest.raises(ValueError, match="must match canonical format"):
        ts_ns_from_str("2026-03-25")


def test_ts_ns_from_str_rejects_invalid_timestamp_string() -> None:
    with pytest.raises(ValueError, match="Invalid canonical timestamp string"):
        ts_ns_from_str("2026-02-30T10:14:03.123456789Z")


def test_ts_ns_to_str_raises_for_nat() -> None:
    with pytest.raises(
        ValueError, match="NaT cannot be converted to canonical timestamp string"
    ):
        ts_ns_to_str(NAT_TS_NS)


def test_ts_ns_to_str_raises_for_wrong_datetime_unit() -> None:
    ts_day = np.datetime64("2026-03-25", "D")
    with pytest.raises(TypeError, match=r"Expected np\.datetime64\[ns\]"):
        ts_ns_to_str(ts_day)
