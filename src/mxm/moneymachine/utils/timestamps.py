"""
mxm.v1.utils.timestamps

Canonical timestamp substrate for the MXM system.

This module defines the authoritative internal representation of timestamps in
MXM and provides the minimal set of constants, predicates, assertions, and
representation bridges required to work with that representation safely and
consistently.

-------------------------------------------------------------------------------
Core Policy
-------------------------------------------------------------------------------

MXM adopts a single canonical internal timestamp representation:

    np.datetime64[ns]

All canonical MXM timestamps:

- are timezone-naive NumPy datetime64 values
- are interpreted strictly as UTC
- represent instants on a POSIX-style linear time axis
- have nanosecond precision
- are anchored to the Unix epoch (1970-01-01T00:00:00)

This representation is the only valid timestamp type inside MXM kernel logic.

-------------------------------------------------------------------------------
Design Principles
-------------------------------------------------------------------------------

1. One Canonical Model

MXM does not maintain multiple competing internal timestamp models.
All kernel logic operates on np.datetime64[ns].

Other representations, such as pandas Timestamps, Python datetime objects,
Parquet timestamp columns, or SQLite timestamp strings, are boundary-layer
concerns and must be adapted explicitly in separate modules.

2. Canonical Representation Bridges

This module defines two canonical bridge representations alongside the core
np.datetime64[ns] object form:

- int64 epoch nanoseconds
- strict UTC ISO8601 strings with exactly 9 fractional digits and trailing Z

These bridges are treated as direct alternate representations of the same
canonical timestamp object.

3. Boundary vs Kernel Separation

- Boundary layers:
    - parsing
    - formatting
    - coercion from external systems
    - storage adaptation
    - pandas / SQLite / Parquet interop

- Kernel layers:
    - assume canonical np.datetime64[ns]
    - perform no repeated coercion
    - operate on validated inputs only

This module belongs to the canonical substrate layer, not the outer adapter
layer.

4. Explicit UTC Semantics

Although np.datetime64 values are timezone-naive, MXM enforces the rule that
all canonical timestamps are interpreted as UTC.

Canonical string representations therefore always use a trailing "Z" suffix,
and day-based operations elsewhere in the system must interpret these
timestamps under UTC semantics.

5. POSIX Time Semantics (No Leap Seconds)

Canonical MXM timestamps follow POSIX time semantics.

- Time is represented as a linear count of elapsed nanoseconds since the Unix epoch.
- Leap seconds are not represented.
- Each day is treated as exactly 86,400 seconds.

This matches the behavior of NumPy datetime64 and most financial data sources.

Consequences:

- Timestamps corresponding to leap seconds (e.g. 23:59:60) cannot be represented.
- UTC is treated as a uniform time scale without discontinuities.

This simplification is intentional and appropriate for MXM use cases.
-------------------------------------------------------------------------------
Scope of This Module
-------------------------------------------------------------------------------

This module provides:

- canonical dtype and sentinel constants
- predicates for canonical scalar and array timestamp checks
- assertions for canonical timestamp invariants
- NaT detection helpers
- monotonicity assertion for canonical timestamp arrays
- explicit conversion between canonical timestamps and:
    - int64 epoch nanoseconds
    - canonical UTC ISO8601 strings

This module intentionally excludes:

- pandas-specific adapters
- storage-specific adapters
- business-day or session semantics
- timezone conversion utilities
- generalized parsing of arbitrary timestamp formats

-------------------------------------------------------------------------------
Missing Values Policy
-------------------------------------------------------------------------------

The NumPy missing timestamp value (NaT) may appear at outer boundaries, but
must not appear inside validated kernel computations.

This module therefore distinguishes between:

- type-form assertions (canonical dtype / shape)
- value-form assertions (not NaT)

Kernel code is expected to operate on fully validated, non-NaT timestamps.

-------------------------------------------------------------------------------
Canonical String Format
-------------------------------------------------------------------------------

The canonical textual representation used by this module is:

    YYYY-MM-DDTHH:MM:SS.fffffffffZ

with:

- UTC semantics
- exactly 9 fractional digits
- mandatory trailing "Z"
- no offset forms such as +01:00
- no date-only forms
- no locale-specific variants

Example:

    2026-03-25T10:14:03.123456789Z

This format is intended to round-trip exactly to and from canonical
np.datetime64[ns] values.

-------------------------------------------------------------------------------
Summary
-------------------------------------------------------------------------------

This module establishes a single, explicit, and stable timestamp foundation
for MXM.

Higher-level temporal structures such as business calendars, sessions, and
market-data alignment should be built on top of this substrate rather than
redefining timestamp semantics locally.
"""

from __future__ import annotations

import re
from typing import Final, TypeGuard, cast

import numpy as np
import numpy.typing as npt

TSNSScalar = np.datetime64
TSNSArray = npt.NDArray[np.datetime64]
Int64Array = npt.NDArray[np.int64]

TS_NS_DTYPE: Final = np.dtype("datetime64[ns]")
INT64_DTYPE: Final = np.dtype("int64")

EPOCH_TS_NS: Final[TSNSScalar] = np.datetime64("1970-01-01T00:00:00", "ns")
NAT_TS_NS: Final[TSNSScalar] = np.datetime64("NaT", "ns")

_CANONICAL_TS_STR_RE: Final[re.Pattern[str]] = re.compile(
    r"^"
    r"(?P<year>\d{4})-"
    r"(?P<month>\d{2})-"
    r"(?P<day>\d{2})T"
    r"(?P<hour>\d{2}):"
    r"(?P<minute>\d{2}):"
    r"(?P<second>\d{2})\."
    r"(?P<fraction>\d{9})"
    r"Z"
    r"$"
)


def is_ts_ns(x: object) -> TypeGuard[TSNSScalar]:
    """
    Return True iff x is a canonical MXM timestamp scalar.

    A canonical scalar timestamp is a NumPy datetime64 scalar with unit [ns].

    Notes
    -----
    UTC is an MXM interpretation convention, not a runtime-inspectable property
    of np.datetime64 itself.
    """
    if not isinstance(x, np.datetime64):
        return False
    ts = cast(TSNSScalar, x)
    ts_arr = np.array(ts)
    return str(ts_arr.dtype) == "datetime64[ns]"


def assert_ts_ns(x: object) -> TSNSScalar:
    """
    Assert that x is a canonical MXM timestamp scalar and return it.

    Guarantees
    ----------
    - scalar np.datetime64
    - unit [ns]
    """
    if not is_ts_ns(x):
        raise TypeError(
            "Expected canonical MXM timestamp scalar "
            "(np.datetime64 with dtype datetime64[ns])."
        )

    return x


def is_nat(x: TSNSScalar) -> bool:
    """
    Return True iff the canonical timestamp scalar is NaT.

    Parameters
    ----------
    x
        Canonical MXM timestamp scalar with dtype datetime64[ns].
    """
    return bool(np.isnat(x))


def assert_not_nat(x: TSNSScalar) -> TSNSScalar:
    """
    Assert that the canonical timestamp scalar is not NaT and return it.

    Parameters
    ----------
    x
        Canonical MXM timestamp scalar with dtype datetime64[ns].

    Raises
    ------
    ValueError
        If the scalar is NaT.
    """
    if is_nat(x):
        raise ValueError("Canonical MXM timestamp scalar must not be NaT.")
    return x


def is_ts_ns_array(x: object) -> TypeGuard[TSNSArray]:
    """
    Return True iff x is a canonical MXM timestamp array.

    A canonical timestamp array is a NumPy ndarray with dtype datetime64[ns].

    Notes
    -----
    UTC is an MXM interpretation convention, not a runtime-inspectable property
    of np.datetime64 itself.
    """
    if not isinstance(x, np.ndarray):
        return False

    arr = cast(TSNSArray, x)
    return str(arr.dtype) == "datetime64[ns]"


def assert_ts_ns_array(x: object) -> TSNSArray:
    """
    Assert that x is a canonical MXM timestamp array and return it.

    Guarantees
    ----------
    - np.ndarray
    - dtype datetime64[ns]

    Does not guarantee
    ------------------
    - absence of NaT
    - monotonicity
    """
    if not is_ts_ns_array(x):
        raise TypeError(
            "Expected canonical MXM timestamp array "
            "(np.ndarray with dtype datetime64[ns])."
        )
    return x


def has_nat(x: TSNSArray) -> bool:
    """
    Return True iff the canonical timestamp array contains one or more NaT values.

    Parameters
    ----------
    x
        Canonical MXM timestamp array with dtype datetime64[ns].
    """
    return bool(np.isnat(x).any())


def assert_no_nat(x: TSNSArray) -> TSNSArray:
    """
    Assert that the canonical timestamp array contains no NaT values and return it.

    Parameters
    ----------
    x
        Canonical MXM timestamp array with dtype datetime64[ns].

    Raises
    ------
    ValueError
        If the array contains one or more NaT values.
    """
    if has_nat(x):
        raise ValueError("Canonical MXM timestamp array must not contain NaT values.")
    return x


def assert_monotonic_increasing_ts_ns_array(x: TSNSArray) -> TSNSArray:
    """
    Assert that the canonical timestamp array is one-dimensional, contains no
    NaT values, and is monotonic increasing.

    Monotonic increasing means:

        x[i] <= x[i + 1]

    for all valid i. Equal adjacent values are therefore allowed.

    Parameters
    ----------
    x
        Canonical MXM timestamp array with dtype datetime64[ns].

    Raises
    ------
    ValueError
        If the array is not one-dimensional, contains one or more NaT values,
        or is not monotonic increasing.
    """
    if x.ndim != 1:
        raise ValueError(
            f"Expected 1D timestamp array for monotonicity check, got ndim={x.ndim}."
        )

    assert_no_nat(x)

    if x.size <= 1:
        return x

    if bool(np.any(x[1:] < x[:-1])):
        raise ValueError("Canonical MXM timestamp array must be monotonic increasing.")

    return x


def ts_ns_from_int(value: int) -> TSNSScalar:
    """
    Construct a canonical timestamp from integer epoch nanoseconds.

    Parameters
    ----------
    value
        Nanoseconds since the Unix epoch.

    Returns
    -------
    np.datetime64
        Canonical timestamp with dtype datetime64[ns].

    Raises
    ------
    TypeError
        If value is not a plain Python int.
    """
    if isinstance(value, bool):
        raise TypeError("Boolean values are not valid epoch nanoseconds.")

    return np.datetime64(value, "ns")


def ts_ns_to_int(value: TSNSScalar) -> int:
    """
    Convert a canonical timestamp to integer epoch nanoseconds.

    Parameters
    ----------
    value
        Canonical timestamp with dtype datetime64[ns].

    Returns
    -------
    int
        Nanoseconds since the Unix epoch.

    Raises
    ------
    TypeError
        If value is not an np.datetime64 scalar with dtype datetime64[ns].
    ValueError
        If value is NaT.
    """
    value_arr = np.array(value)

    if str(value_arr.dtype) != "datetime64[ns]":
        raise TypeError(
            f"Expected np.datetime64[ns], got dtype={value_arr.dtype!s}, value={value!r}."
        )

    if bool(np.isnat(value)):
        raise ValueError("NaT cannot be converted to integer epoch nanoseconds.")

    int_arr = value_arr.view(INT64_DTYPE)
    return int(int_arr.item())


def ts_ns_from_str(value: str) -> TSNSScalar:
    """
    Construct a canonical timestamp from the canonical MXM UTC string format.

    Accepted format:

        YYYY-MM-DDTHH:MM:SS.fffffffffZ

    with exactly 9 fractional digits and mandatory trailing Z.

    Parameters
    ----------
    value
        Canonical UTC timestamp string.

    Returns
    -------
    np.datetime64
        Canonical timestamp with dtype datetime64[ns].

    Raises
    ------
    TypeError
        If value is not a string.
    ValueError
        If value does not match the canonical format or is not a valid
        timestamp.
    """
    if _CANONICAL_TS_STR_RE.fullmatch(value) is None:
        raise ValueError(
            "Timestamp string must match canonical format "
            "'YYYY-MM-DDTHH:MM:SS.fffffffffZ'."
        )

    ts_text = value[:-1]

    try:
        ts = np.datetime64(ts_text, "ns")
    except ValueError as exc:
        raise ValueError(f"Invalid canonical timestamp string: {value!r}.") from exc

    if bool(np.isnat(ts)):
        raise ValueError(f"Invalid canonical timestamp string: {value!r}.")

    return ts


def ts_ns_to_str(value: TSNSScalar) -> str:
    """
    Convert a canonical timestamp to the canonical MXM UTC string format.

    Output format:

        YYYY-MM-DDTHH:MM:SS.fffffffffZ

    with exactly 9 fractional digits and mandatory trailing Z.

    Parameters
    ----------
    value
        Canonical timestamp with dtype datetime64[ns].

    Returns
    -------
    str
        Canonical UTC timestamp string.

    Raises
    ------
    TypeError
        If value is not an np.datetime64 scalar with dtype datetime64[ns].
    ValueError
        If value is NaT.
    """
    value_arr = np.array(value)

    if str(value_arr.dtype) != "datetime64[ns]":
        raise TypeError(
            f"Expected np.datetime64[ns], got dtype={value_arr.dtype!s}, value={value!r}."
        )

    if bool(np.isnat(value)):
        raise ValueError("NaT cannot be converted to canonical timestamp string.")

    text = np.datetime_as_string(value, unit="ns")
    return f"{text}Z"
