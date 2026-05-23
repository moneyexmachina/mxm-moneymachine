"""
Pandas boundary adapters for the MXM canonical timestamp model.

This module defines explicit representation bridges between the canonical MXM
timestamp substrate in `mxm.moneymachine.utils.timestamps` and pandas timestamp
representations.

The canonical MXM model is:

    - scalar: np.datetime64[ns]
    - vector: ndarray[datetime64[ns]]

interpreted strictly as UTC under MXM policy.

This module maps those canonical representations to and from:

    - pd.Timestamp
    - pd.DatetimeIndex

-------------------------------------------------------------------------------
Core Policy
-------------------------------------------------------------------------------

1. Canonical MXM timestamps remain authoritative

This module does not define timestamp semantics. It only adapts between pandas
representations and the canonical timestamp model defined in `timestamps.py`.

2. Pandas timestamps must be timezone-aware

On the pandas side, timestamps and DatetimeIndex objects must be timezone-aware.

Naive pandas timestamps are rejected.

3. Pandas timestamps are normalized to UTC

If a pandas timestamp or DatetimeIndex is timezone-aware but not UTC, it is
explicitly converted to UTC before conversion into canonical MXM form.

4. NaT is allowed at the pandas boundary

This module permits missing timestamp values at the outer boundary and preserves
them faithfully across conversions.

Stricter "non-NaT" requirements belong to the canonical assertion layer in
`timestamps.py`.

5. No additional semantics are introduced

This module does not handle:

    - business-day logic
    - session logic
    - time arithmetic
    - resampling
    - durations or offsets

It is strictly a representation adapter layer.

-------------------------------------------------------------------------------
Boundary Mapping
-------------------------------------------------------------------------------

Canonical MXM scalar:

    np.datetime64[ns]   <->   pd.Timestamp(tz="UTC")

Canonical MXM vector:

    ndarray[datetime64[ns]]   <->   pd.DatetimeIndex(tz="UTC")

Duplicates are permitted.
Monotonicity is not required by this module.
Timezone-aware UTC normalization is required on the pandas side.

-------------------------------------------------------------------------------
Summary
-------------------------------------------------------------------------------

This module is the pandas-side boundary for the canonical MXM timestamp model.

It exists to ensure that pandas interoperability remains explicit, consistent,
and fully aligned with the canonical timestamp substrate.
"""

from __future__ import annotations

from typing import TypeGuard

import pandas as pd

from mxm.moneymachine.utils.timestamps import (
    TSNSArray,
    TSNSScalar,
    assert_not_nat,
    assert_ts_ns,
    assert_ts_ns_array,
)

# ---------------------------------------------------------------------------
# Pandas normal-form predicates and assertions
# ---------------------------------------------------------------------------


def is_pd_timestamp_for_ts_ns(x: object) -> TypeGuard[pd.Timestamp]:
    """
    Return True iff x is in the approved pandas normal form for a canonical
    MXM timestamp scalar.

    The approved pandas normal form is:

    - pd.Timestamp
    - timezone-aware
    - UTC

    Notes
    -----
    This predicate does not define canonical MXM timestamp semantics. Those are
    owned by `mxm.moneymachine.utils.timestamps`.

    It defines the authoritative pandas-side representation contract for
    canonical MXM timestamps.
    """
    if not isinstance(x, pd.Timestamp):
        return False

    if x.tzinfo is None:
        return False

    return str(x.tzinfo) == "UTC"


def assert_pd_timestamp_for_ts_ns(x: object) -> pd.Timestamp:
    """
    Assert that x is in the approved pandas normal form for a canonical MXM
    timestamp scalar and return it.

    Guarantees
    ----------
    - pd.Timestamp
    - timezone-aware
    - UTC
    """
    if not is_pd_timestamp_for_ts_ns(x):
        raise TypeError(
            "Expected pandas Timestamp in approved MXM normal form "
            "(timezone-aware UTC pd.Timestamp)."
        )

    return x


def is_pd_datetimeindex_for_ts_ns_array(x: object) -> TypeGuard[pd.DatetimeIndex]:
    """
    Return True iff x is in the approved pandas normal form for a canonical
    MXM timestamp array.

    The approved pandas normal form is:

    - pd.DatetimeIndex
    - timezone-aware
    - UTC

    Duplicates are permitted.
    Monotonicity is not required by this predicate.
    """
    if not isinstance(x, pd.DatetimeIndex):
        return False

    if x.tz is None:
        return False

    return str(x.tz) == "UTC"


def assert_pd_datetimeindex_for_ts_ns_array(x: object) -> pd.DatetimeIndex:
    """
    Assert that x is in the approved pandas normal form for a canonical MXM
    timestamp array and return it.

    Guarantees
    ----------
    - pd.DatetimeIndex
    - timezone-aware
    - UTC

    Does not guarantee
    ------------------
    - absence of NaT
    - monotonicity
    - uniqueness
    """
    if not is_pd_datetimeindex_for_ts_ns_array(x):
        raise TypeError(
            "Expected pandas DatetimeIndex in approved MXM normal form "
            "(timezone-aware UTC pd.DatetimeIndex)."
        )

    return x


def _assert_pd_timestamp_tz_aware(ts: pd.Timestamp) -> pd.Timestamp:
    """
    Assert that a pandas Timestamp is timezone-aware and return it.

    Raises
    ------
    TypeError
        If the timestamp is naive.
    """
    if ts.tzinfo is None:
        raise TypeError("Naive pandas Timestamp values are not allowed.")
    return ts


def _assert_pd_datetimeindex_tz_aware(idx: pd.DatetimeIndex) -> pd.DatetimeIndex:
    """
    Assert that a pandas DatetimeIndex is timezone-aware and return it.

    Raises
    ------
    TypeError
        If the DatetimeIndex is naive.
    """
    if idx.tz is None:
        raise TypeError("Naive pandas DatetimeIndex values are not allowed.")
    return idx


def ts_ns_from_pd_timestamp(ts: pd.Timestamp) -> TSNSScalar:
    """
    Construct a canonical MXM timestamp scalar from a pandas Timestamp.

    Parameters
    ----------
    ts
        Pandas timestamp. It must be a concrete, timezone-aware Timestamp. If
        not already UTC, it is converted explicitly to UTC before conversion.

    Returns
    -------
    TSNSScalar
        Canonical MXM timestamp scalar in np.datetime64[ns] form.

    Raises
    ------
    ValueError
        If the pandas Timestamp is NaT.
    TypeError
        If the pandas Timestamp is naive.
    """
    if pd.isna(ts):
        raise ValueError("Pandas Timestamp must not be NaT.")

    ts_aware = _assert_pd_timestamp_tz_aware(ts)
    ts_utc = ts_aware.tz_convert("UTC")
    ts_ns = ts_utc.to_datetime64().astype("datetime64[ns]")
    return assert_not_nat(assert_ts_ns(ts_ns))


def ts_ns_to_pd_timestamp(ts: TSNSScalar) -> pd.Timestamp:
    """
    Convert a canonical MXM timestamp scalar to a pandas Timestamp.

    Parameters
    ----------
    ts
        Canonical MXM timestamp scalar in np.datetime64[ns] form.

    Returns
    -------
    pd.Timestamp
        Timezone-aware UTC pandas Timestamp.

    Notes
    -----
    Canonical NaT is preserved as pandas NaT.
    """
    ts_canonical = assert_ts_ns(ts)
    ts_valid = assert_not_nat(ts_canonical)
    pd_ts = pd.Timestamp(ts_valid, tz="UTC")
    return assert_pd_timestamp_for_ts_ns(pd_ts)


def ts_ns_array_from_pd_datetimeindex(idx: pd.DatetimeIndex) -> TSNSArray:
    """
    Construct a canonical MXM timestamp array from a pandas DatetimeIndex.

    Parameters
    ----------
    idx
        Pandas DatetimeIndex. It must be timezone-aware. If not already UTC, it
        is converted explicitly to UTC before conversion.

    Returns
    -------
    TSNSArray
        Canonical MXM timestamp array with dtype datetime64[ns].

    Notes
    -----
    pandas NaT values are preserved as canonical NaT values.
    Duplicates are permitted.
    """
    idx_aware = _assert_pd_datetimeindex_tz_aware(idx)
    idx_utc = idx_aware.tz_convert("UTC")
    arr = idx_utc.to_numpy(dtype="datetime64[ns]")
    return assert_ts_ns_array(arr)


def ts_ns_array_to_pd_datetimeindex(arr: TSNSArray) -> pd.DatetimeIndex:
    """
    Convert a canonical MXM timestamp array to a pandas DatetimeIndex.

    Parameters
    ----------
    arr
        Canonical MXM timestamp array with dtype datetime64[ns].

    Returns
    -------
    pd.DatetimeIndex
        Timezone-aware UTC pandas DatetimeIndex.

    Notes
    -----
    Canonical NaT values are preserved as pandas NaT values.
    Duplicates are permitted.
    """
    arr_canonical = assert_ts_ns_array(arr)
    idx = pd.DatetimeIndex(arr_canonical)
    if idx.tz is None:
        idx = idx.tz_localize("UTC")
    else:
        idx = idx.tz_convert("UTC")
    return assert_pd_datetimeindex_for_ts_ns_array(idx)
