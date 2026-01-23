from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any

import pandas as pd

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


def _ts_utc(ts: pd.Timestamp) -> pd.Timestamp:
    """Ensure tz-aware UTC pandas Timestamp."""
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _day_start_utc(d: date) -> pd.Timestamp:
    return pd.Timestamp(datetime(d.year, d.month, d.day, tzinfo=timezone.utc))


def _ceil_to_next_utc_day(dt_utc: datetime) -> pd.Timestamp:
    """
    For half-open windows, ceil to the next 00:00Z boundary.

    If dt_utc is exactly at 00:00Z, this returns the same boundary (not +1 day).
    Otherwise, returns next day's 00:00Z.
    """
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(timezone.utc)

    day_start = datetime(dt_utc.year, dt_utc.month, dt_utc.day, tzinfo=timezone.utc)
    if dt_utc == day_start:
        return pd.Timestamp(day_start)
    return pd.Timestamp(day_start + timedelta(days=1))


def _floor_to_utc_day(dt_utc: datetime) -> pd.Timestamp:
    """Floor to 00:00Z of dt_utc's day."""
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    else:
        dt_utc = dt_utc.astimezone(timezone.utc)
    return pd.Timestamp(
        datetime(dt_utc.year, dt_utc.month, dt_utc.day, tzinfo=timezone.utc)
    )


def _dt_from_ns_utc(ns: int) -> datetime:
    """
    Convert an integer nanoseconds-since-epoch to UTC datetime.
    (Python datetime has microsecond resolution; we truncate nanos to micros.)
    """
    if ns < 0:
        raise ValueError(f"nanoseconds timestamp must be >= 0, got {ns}")
    us = ns // 1_000  # truncate nanos -> micros
    return datetime.fromtimestamp(us / 1_000_000, tz=timezone.utc)


def _extract_ns(value: Any) -> int | None:
    """
    Extract a nanoseconds-since-epoch integer from likely input shapes.

    Expected sources:
      - instrument_definitions fields often arrive as int-like, possibly numpy scalars.
      - allow None / NaN.
    """
    if value is None:
        return None
    # pandas / numpy NaN handling
    try:
        if pd.isna(value):  # type: ignore[arg-type]
            return None
    except Exception:
        pass
    # numpy scalar -> python int
    try:
        return int(value)
    except Exception as e:
        raise TypeError(f"could not coerce to int nanoseconds: {value!r}") from e


# -----------------------------
# Public API
# -----------------------------


def derive_interest_window(
    *,
    first_day_of_interest: date,
    last_trading_day: date,
) -> tuple[pd.Timestamp, pd.Timestamp]:
    """
    Interest window in half-open UTC form:
      [first_day_of_interest@00:00Z, (last_trading_day + 1d)@00:00Z)
    """
    start = _day_start_utc(first_day_of_interest)
    end = _day_start_utc(last_trading_day + timedelta(days=1))
    return start, end


def derive_lifecycle_bounds(
    *,
    activation_ns: int | None,
    expiration_ns: int | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """
    Lifecycle bounds as day-aligned OHLCV-1D half-open constraints:
      activation_floor:  floor_to_utc_day(activation)
      expiration_ceiling: ceil_to_next_utc_day(expiration)

    Either may be None if the vendor field is missing.
    """
    activation_floor: pd.Timestamp | None = None
    expiration_ceiling: pd.Timestamp | None = None

    if activation_ns is not None:
        activation_floor = _floor_to_utc_day(_dt_from_ns_utc(activation_ns))
        activation_floor = _ts_utc(activation_floor)

    if expiration_ns is not None:
        expiration_ceiling = _ceil_to_next_utc_day(_dt_from_ns_utc(expiration_ns))
        expiration_ceiling = _ts_utc(expiration_ceiling)

    return activation_floor, expiration_ceiling


def derive_expected_window(
    *,
    product_id: str,
    contract_id: str,
    first_day_of_interest: date,
    last_trading_day: date,
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
    interest_start = _ts_utc(interest_start)
    interest_end = _ts_utc(interest_end)

    # Dataset range (capability)
    ds_start = _ts_utc(pd.Timestamp(dataset_start))
    ds_end = _ts_utc(pd.Timestamp(dataset_end))

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
