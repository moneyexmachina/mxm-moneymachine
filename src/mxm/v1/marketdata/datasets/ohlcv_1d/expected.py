from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

import pandas as pd

from mxm.v1.utils.date_utils import utc_day_end_exclusive, utc_day_start
from mxm.v1.utils.time_utils import (
    ceil_to_utc_day,
    parse_ts,
    to_utc_day,
    to_utc_ts,
)

# -----------------------------
# Value object
# -----------------------------


@dataclass(frozen=True)
class ExpectedWindow:
    product_id: str
    contract_id: str

    # input surfaces
    interest_start: pd.Timestamp
    interest_end: pd.Timestamp
    dataset_start: pd.Timestamp
    dataset_end: pd.Timestamp
    activation_floor: pd.Timestamp | None
    expiration_ceiling: pd.Timestamp | None

    # derived interval (half-open)
    expected_start: pd.Timestamp
    expected_end: pd.Timestamp

    # derived flags
    is_empty: bool
    is_vendor_limited: bool
    is_lifecycle_limited: bool
    vendor_final: bool


# -----------------------------
# UTC / day-boundary helpers
# -----------------------------
def _extract_ns(value: Any) -> int | None:
    if value is None:
        return None
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return None
    except Exception:
        pass

    if isinstance(value, int):
        return int(value)

    if isinstance(value, pd.Timestamp):
        return int(to_utc_ts(value).value)

    if isinstance(value, datetime):
        return int(to_utc_ts(value).value)

    if isinstance(value, str):
        # strict: requires tz in timestamp strings unless it's a pure date handled elsewhere
        ts = parse_ts(value)
        return int(ts.value)

    try:
        return int(value)
    except Exception as e:
        raise TypeError(f"could not coerce to int nanoseconds: {value!r}") from e


# -----------------------------
# Public API
# -----------------------------


def derive_interest_window(
    *,
    first_day_of_interest: Any,
    last_trading_day: Any,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Interest window in half-open UTC form:
      [first_day_of_interest@00:00Z, (last_trading_day + 1d)@00:00Z)
    """
    start = utc_day_start(first_day_of_interest)
    end = utc_day_end_exclusive(last_trading_day)
    return start, end


def derive_lifecycle_bounds(
    *,
    activation_ns: int | None,
    expiration_ns: int | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    activation_floor = None
    expiration_ceiling = None

    if activation_ns is not None:
        activation_floor = to_utc_day(pd.Timestamp(activation_ns, unit="ns", tz="UTC"))

    if expiration_ns is not None:
        exp_ts = pd.Timestamp(expiration_ns, unit="ns", tz="UTC")
        expiration_ceiling = ceil_to_utc_day(exp_ts)

    return activation_floor, expiration_ceiling


def derive_expected_window(
    *,
    product_id: str,
    contract_id: str,
    first_day_of_interest: Any,
    last_trading_day: Any,
    dataset_start: pd.Timestamp,
    dataset_end: pd.Timestamp,  # end-exclusive
    activation: Any = None,
    expiration: Any = None,
) -> ExpectedWindow:
    """
    Derive the expected OHLCV-1D window for a contract.

    Inputs:
      - interest window from refdata (dates)
      - dataset availability window (timestamps; end-exclusive)
      - lifecycle activation/expiration from vendor instrument definitions
        (nanoseconds since epoch; may be None)

    Returns:
      - ExpectedWindow with tz-aware UTC pd.Timestamps
      - Interval may be empty; emptiness is represented by ew.is_empty.
    """
    # Interest (operator intent)
    interest_start, interest_end = derive_interest_window(
        first_day_of_interest=first_day_of_interest,
        last_trading_day=last_trading_day,
    )
    interest_start = to_utc_ts(interest_start)
    interest_end = to_utc_ts(interest_end)

    # Dataset range (capability)
    ds_start = to_utc_ts(dataset_start)
    ds_end = to_utc_ts(dataset_end)

    # Lifecycle (vendor)
    activation_ns = _extract_ns(activation)
    expiration_ns = _extract_ns(expiration)
    activation_floor, expiration_ceiling = derive_lifecycle_bounds(
        activation_ns=activation_ns,
        expiration_ns=expiration_ns,
    )

    # Compute intersection: interest ∩ dataset
    expected_start = max(interest_start, ds_start)
    expected_end = min(interest_end, ds_end)

    is_vendor_limited = (expected_start != interest_start) or (
        expected_end != interest_end
    )

    # Apply lifecycle clamps (if present)
    is_lifecycle_limited = False
    if activation_floor is not None and activation_floor > expected_start:
        expected_start = activation_floor
        is_lifecycle_limited = True

    if expiration_ceiling is not None and expiration_ceiling < expected_end:
        expected_end = expiration_ceiling
        is_lifecycle_limited = True

    # Half-open emptiness test
    is_empty = expected_end <= expected_start

    # Vendor finality (orthogonal to emptiness):
    # only when the dataset has advanced beyond the instrument's expiration ceiling
    vendor_final = (expiration_ceiling is not None) and (ds_end >= expiration_ceiling)

    return ExpectedWindow(
        product_id=product_id,
        contract_id=contract_id,
        interest_start=interest_start,
        interest_end=interest_end,
        dataset_start=ds_start,
        dataset_end=ds_end,
        activation_floor=activation_floor,
        expiration_ceiling=expiration_ceiling,
        expected_start=expected_start,
        expected_end=expected_end,
        is_empty=is_empty,
        is_vendor_limited=is_vendor_limited,
        is_lifecycle_limited=is_lifecycle_limited,
        vendor_final=vendor_final,
    )
