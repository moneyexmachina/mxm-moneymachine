# mxm/v1/marketdata/inspect/models.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

import pandas as pd

from mxm.v1.marketdata.time_utils import ensure_midnight_utc, to_utc_day, to_utc_ts

# -------------------------
# Core range primitives
# -------------------------


@dataclass(frozen=True)
class DayRange:
    """
    Day-aligned, half-open UTC time window: [start, end)

    Invariants:
      - start and end are tz-aware UTC timestamps at 00:00:00
      - start < end
    """

    start: pd.Timestamp
    end: pd.Timestamp

    def __post_init__(self) -> None:
        s = ensure_midnight_utc(self.start)
        e = ensure_midnight_utc(self.end)
        object.__setattr__(self, "start", s)
        object.__setattr__(self, "end", e)

        if s > e:
            raise ValueError(f"DayRange invariant violated: start={s!r} end={e!r}")

    def contains(self, other: DayRange) -> bool:
        """Return True if self fully contains other."""
        return self.start <= other.start and self.end >= other.end

    def intersects(self, other: DayRange) -> bool:
        return self.start < other.end and other.start < self.end

    def intersection(self, other: DayRange) -> Optional[DayRange]:
        if not self.intersects(other):
            return None
        s = max(self.start, other.start)
        e = min(self.end, other.end)
        return DayRange(start=s, end=e)

    @property
    def days(self) -> int:
        """Number of 24h days in the half-open interval."""
        delta = self.end - self.start
        return int(delta / pd.Timedelta(days=1))

    @property
    def is_empty(self) -> bool:
        return self.start == self.end


@dataclass(frozen=True)
class ObservedRange:
    """
    Observed timestamp range from stored bars, based on min/max ts_event.

    Notes:
      - min_ts / max_ts are tz-aware UTC timestamps, not day-aligned.
      - This is descriptive; do not compare directly against DayRange.
    """

    min_ts: pd.Timestamp
    max_ts: pd.Timestamp

    def __post_init__(self) -> None:
        mn = to_utc_ts(self.min_ts)
        mx = to_utc_ts(self.max_ts)
        object.__setattr__(self, "min_ts", mn)
        object.__setattr__(self, "max_ts", mx)
        if mn > mx:
            raise ValueError(
                f"ObservedRange invariant violated: min_ts={mn!r} max_ts={mx!r}"
            )

    def to_day_window(self) -> DayRange:
        """
        Normalize observed bars to a day-aligned half-open window.

        For daily bars, if the last observed bar timestamp is during day D,
        we treat coverage as extending through the end of D:
          stored_end = floor_to_day(max_ts) + 1 day.
        """
        start_day = to_utc_day(self.min_ts)
        end_day_excl = to_utc_day(self.max_ts) + pd.Timedelta(days=1)
        return DayRange(start=start_day, end=end_day_excl)


# -------------------------
# Coverage synthesis
# -------------------------


@dataclass(frozen=True)
class CoverageSurfaces:
    """
    The "surfaces" used to define availability and expectations for a contract.

    All DayRange fields are day-aligned, half-open [start,end).
    """

    interest: DayRange  # MXM refdata "first_day_of_interest" .. "last_trading_day"
    dataset: DayRange  # vendor dataset range (metadata.get_dataset_range), clamped per attempt
    lifecycle: Optional[
        DayRange
    ]  # instrument activation/expiration constraints, if known


@dataclass(frozen=True)
class CoverageWindows:
    """
    Coverage windows derived from surfaces and local storage.

    - available: what vendor could provide for this contract within dataset + lifecycle
    - expected: what MXM expects to have, i.e. interest clamped by available surfaces
    - stored_observed: descriptive min/max ts_event from local store snapshots
    - stored_window: normalized day-aligned window derived from stored_observed
    """

    available: Optional[DayRange]
    expected: DayRange

    stored_observed: Optional[ObservedRange]
    stored_window: Optional[DayRange]

    row_count: int

    @property
    def is_empty_expected(self) -> bool:
        return self.expected.days == 0

    @property
    def has_data(self) -> bool:
        return self.row_count > 0 and self.stored_window is not None

    @property
    def complete(self) -> Optional[bool]:
        """
        Completeness relative to expected window, as-of last observed local storage.

        Returns:
          - True/False when we have a stored_window
          - None when we have no stored_window (no local bars)
        """
        if self.is_empty_expected:
            # vacuously complete (but callers may want to surface is_empty_expected separately)
            return True
        if self.stored_window is None:
            return False
        return self.stored_window.contains(self.expected)

    @property
    def vendor_final(self) -> Optional[bool]:
        """
        Vendor finality relative to available window.

        Returns:
          - None if available is unknown
          - True if expected equals available (i.e. nothing more should exist beyond expected)
          - False otherwise
        """
        if self.available is None:
            return None
        return (
            self.expected.start == self.available.start
            and self.expected.end == self.available.end
        )


# -------------------------
# Attempt / status representation
# -------------------------


class AttemptStatus(str, Enum):
    unmapped = "unmapped"
    skipped_empty_expected_window = "skipped_empty_expected_window"
    complete = "complete"
    dry_run = "dry_run"
    skipped_cost_cap = "skipped_cost_cap"
    ingested = "ingested"
    incomplete = "incomplete"
    error = "error"  # not in your comment list, but observed in the sample row


@dataclass(frozen=True)
class AttemptSummary:
    attempt_uid: str
    run_ts_utc: pd.Timestamp
    mode: str
    dry_run: bool

    status: str
    status_detail: Optional[str]

    cost_cap_usd: Optional[float]
    cost_estimated_usd: Optional[float]
    cost_charged_usd: Optional[float]
    cost_used_usd: Optional[float]

    error_type: Optional[str]
    error_message: Optional[str]
    is_empty: bool
    vendor_final: bool


# -------------------------
# Contract / product coverage models
# -------------------------


@dataclass(frozen=True)
class ContractCoverage:
    product_id: str
    contract_id: str
    contract_key: str

    dataset: str
    publisher_id: Optional[int]
    instrument_id: Optional[int]
    raw_symbol: Optional[str]

    surfaces: CoverageSurfaces
    windows: CoverageWindows

    last_attempt: AttemptSummary


@dataclass(frozen=True)
class ProductCoverage:
    product_id: str
    contracts_total: int
    contracts_complete: int
    contracts_incomplete: int
    contracts_unmapped: int
    contracts_error: int
    contracts_empty_expected: int

    # Optional rollups
    stored_earliest: Optional[pd.Timestamp]
    stored_latest: Optional[pd.Timestamp]
    expected_earliest: Optional[pd.Timestamp]
    expected_latest: Optional[pd.Timestamp]

    last_run_ts_utc: Optional[pd.Timestamp]

    @property
    def complete(self) -> bool:
        return (
            self.contracts_total > 0
            and self.contracts_incomplete == 0
            and self.contracts_unmapped == 0
            and self.contracts_error == 0
        )


@dataclass(frozen=True)
class SystemSummary:
    products_total: int
    products_never_run: int
    products_complete: int
    products_partial: int
    products_error_only: int
