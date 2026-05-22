from __future__ import annotations

import numpy as np
import pytest

from mxm.v1.utils.timestamps import (
    EPOCH_TS_NS,
    INT64_DTYPE,
    NAT_TS_NS,
    TS_NS_DTYPE,
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


def test_constants_have_expected_dtypes() -> None:
    assert TS_NS_DTYPE == np.dtype("datetime64[ns]")
    assert INT64_DTYPE == np.dtype("int64")
    assert is_ts_ns(EPOCH_TS_NS)
    assert is_ts_ns(NAT_TS_NS)
    assert is_nat(NAT_TS_NS)


def test_is_ts_ns_accepts_datetime64_ns_scalar() -> None:
    ts = np.datetime64("2026-03-10T08:00:00.000000000", "ns")

    assert is_ts_ns(ts)


def test_is_ts_ns_rejects_non_ns_datetime64_scalar() -> None:
    assert not is_ts_ns(np.datetime64("2026-03-10", "D"))


def test_is_ts_ns_rejects_non_datetime64_object() -> None:
    assert not is_ts_ns("2026-03-10T08:00:00.000000000Z")


def test_assert_ts_ns_returns_valid_scalar() -> None:
    ts = np.datetime64("2026-03-10T08:00:00.000000000", "ns")

    assert assert_ts_ns(ts) == ts


def test_assert_ts_ns_raises_for_invalid_scalar() -> None:
    with pytest.raises(TypeError, match="Expected canonical MXM timestamp scalar"):
        assert_ts_ns(np.datetime64("2026-03-10", "D"))


def test_is_nat_detects_nat_and_non_nat() -> None:
    assert is_nat(np.datetime64("NaT", "ns"))
    assert not is_nat(np.datetime64("2026-03-10T08:00:00.000000000", "ns"))


def test_assert_not_nat_returns_non_nat_scalar() -> None:
    ts = np.datetime64("2026-03-10T08:00:00.000000000", "ns")

    assert assert_not_nat(ts) == ts


def test_assert_not_nat_raises_for_nat_scalar() -> None:
    with pytest.raises(ValueError, match="must not be NaT"):
        assert_not_nat(np.datetime64("NaT", "ns"))


def test_is_ts_ns_array_accepts_datetime64_ns_array() -> None:
    arr = np.array(
        ["2026-03-10T08:00:00.000000000"],
        dtype="datetime64[ns]",
    )

    assert is_ts_ns_array(arr)


def test_is_ts_ns_array_rejects_non_ns_datetime64_array() -> None:
    arr = np.array(["2026-03-10"], dtype="datetime64[D]")

    assert not is_ts_ns_array(arr)


def test_is_ts_ns_array_rejects_non_array() -> None:
    assert not is_ts_ns_array([np.datetime64("2026-03-10T08:00:00", "ns")])


def test_assert_ts_ns_array_returns_valid_array() -> None:
    arr = np.array(
        ["2026-03-10T08:00:00.000000000"],
        dtype="datetime64[ns]",
    )

    assert assert_ts_ns_array(arr) is arr


def test_assert_ts_ns_array_raises_for_invalid_array() -> None:
    arr = np.array(["2026-03-10"], dtype="datetime64[D]")

    with pytest.raises(TypeError, match="Expected canonical MXM timestamp array"):
        assert_ts_ns_array(arr)


def test_has_nat_detects_nat_in_array() -> None:
    arr = np.array(
        [
            "2026-03-10T08:00:00.000000000",
            "NaT",
        ],
        dtype="datetime64[ns]",
    )

    assert has_nat(arr)


def test_has_nat_returns_false_when_array_has_no_nat() -> None:
    arr = np.array(
        [
            "2026-03-10T08:00:00.000000000",
            "2026-03-10T09:00:00.000000000",
        ],
        dtype="datetime64[ns]",
    )

    assert not has_nat(arr)


def test_assert_no_nat_returns_array_without_nat() -> None:
    arr = np.array(
        ["2026-03-10T08:00:00.000000000"],
        dtype="datetime64[ns]",
    )

    assert assert_no_nat(arr) is arr


def test_assert_no_nat_raises_when_array_contains_nat() -> None:
    arr = np.array(
        [
            "2026-03-10T08:00:00.000000000",
            "NaT",
        ],
        dtype="datetime64[ns]",
    )

    with pytest.raises(ValueError, match="must not contain NaT"):
        assert_no_nat(arr)


def test_assert_monotonic_increasing_accepts_empty_singleton_equal_and_increasing() -> (
    None
):
    empty = np.array([], dtype="datetime64[ns]")
    singleton = np.array(["2026-03-10T08:00:00.000000000"], dtype="datetime64[ns]")
    equal = np.array(
        [
            "2026-03-10T08:00:00.000000000",
            "2026-03-10T08:00:00.000000000",
        ],
        dtype="datetime64[ns]",
    )
    increasing = np.array(
        [
            "2026-03-10T08:00:00.000000000",
            "2026-03-10T09:00:00.000000000",
        ],
        dtype="datetime64[ns]",
    )

    assert assert_monotonic_increasing_ts_ns_array(empty) is empty
    assert assert_monotonic_increasing_ts_ns_array(singleton) is singleton
    assert assert_monotonic_increasing_ts_ns_array(equal) is equal
    assert assert_monotonic_increasing_ts_ns_array(increasing) is increasing


def test_assert_monotonic_increasing_rejects_non_1d_array() -> None:
    arr = np.array(
        [["2026-03-10T08:00:00.000000000"]],
        dtype="datetime64[ns]",
    )

    with pytest.raises(ValueError, match="Expected 1D timestamp array"):
        assert_monotonic_increasing_ts_ns_array(arr)


def test_assert_monotonic_increasing_rejects_nat() -> None:
    arr = np.array(
        [
            "2026-03-10T08:00:00.000000000",
            "NaT",
        ],
        dtype="datetime64[ns]",
    )

    with pytest.raises(ValueError, match="must not contain NaT"):
        assert_monotonic_increasing_ts_ns_array(arr)


def test_assert_monotonic_increasing_rejects_decreasing_array() -> None:
    arr = np.array(
        [
            "2026-03-10T09:00:00.000000000",
            "2026-03-10T08:00:00.000000000",
        ],
        dtype="datetime64[ns]",
    )

    with pytest.raises(ValueError, match="must be monotonic increasing"):
        assert_monotonic_increasing_ts_ns_array(arr)


def test_ts_ns_from_int_constructs_canonical_timestamp() -> None:
    out = ts_ns_from_int(1_000_000_000)

    assert out == np.datetime64("1970-01-01T00:00:01.000000000", "ns")
    assert out.dtype == np.dtype("datetime64[ns]")


def test_ts_ns_from_int_rejects_bool() -> None:
    with pytest.raises(TypeError, match="Boolean values"):
        ts_ns_from_int(True)


def test_ts_ns_to_int_converts_canonical_timestamp() -> None:
    ts = np.datetime64("1970-01-01T00:00:01.000000123", "ns")

    assert ts_ns_to_int(ts) == 1_000_000_123


def test_ts_ns_to_int_rejects_non_ns_scalar() -> None:
    with pytest.raises(TypeError, match=r"Expected np\.datetime64\[ns\]"):
        ts_ns_to_int(np.datetime64("2026-03-10", "D"))


def test_ts_ns_to_int_rejects_nat() -> None:
    with pytest.raises(ValueError, match="NaT cannot be converted"):
        ts_ns_to_int(np.datetime64("NaT", "ns"))


def test_ts_ns_int_roundtrip() -> None:
    value = 1_772_213_643_123_456_789

    assert ts_ns_to_int(ts_ns_from_int(value)) == value


def test_ts_ns_from_str_parses_canonical_string() -> None:
    out = ts_ns_from_str("2026-03-25T10:14:03.123456789Z")

    assert out == np.datetime64("2026-03-25T10:14:03.123456789", "ns")
    assert out.dtype == np.dtype("datetime64[ns]")


@pytest.mark.parametrize(
    "value",
    [
        "2026-03-25T10:14:03Z",
        "2026-03-25T10:14:03.123Z",
        "2026-03-25T10:14:03.123456Z",
        "2026-03-25T10:14:03.123456789",
        "2026-03-25 10:14:03.123456789Z",
        "2026-03-25T10:14:03.123456789+00:00",
        "2026-03-25",
    ],
)
def test_ts_ns_from_str_rejects_non_canonical_strings(value: str) -> None:
    with pytest.raises(ValueError, match="canonical format"):
        ts_ns_from_str(value)


def test_ts_ns_from_str_rejects_invalid_timestamp() -> None:
    with pytest.raises(ValueError, match="Invalid canonical timestamp string"):
        ts_ns_from_str("2026-02-30T10:14:03.123456789Z")


def test_ts_ns_to_str_formats_canonical_timestamp() -> None:
    ts = np.datetime64("2026-03-25T10:14:03.123456789", "ns")

    assert ts_ns_to_str(ts) == "2026-03-25T10:14:03.123456789Z"


def test_ts_ns_to_str_preserves_zero_fractional_digits() -> None:
    ts = np.datetime64("2026-03-25T10:14:03.000000000", "ns")

    assert ts_ns_to_str(ts) == "2026-03-25T10:14:03.000000000Z"


def test_ts_ns_to_str_rejects_non_ns_scalar() -> None:
    with pytest.raises(TypeError, match=r"Expected np\.datetime64\[ns\]"):
        ts_ns_to_str(np.datetime64("2026-03-25", "D"))


def test_ts_ns_to_str_rejects_nat() -> None:
    with pytest.raises(ValueError, match="NaT cannot be converted"):
        ts_ns_to_str(np.datetime64("NaT", "ns"))


def test_ts_ns_str_roundtrip() -> None:
    value = "2026-03-25T10:14:03.123456789Z"

    assert ts_ns_to_str(ts_ns_from_str(value)) == value
