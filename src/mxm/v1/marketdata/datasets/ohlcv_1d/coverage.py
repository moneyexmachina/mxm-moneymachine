"""
Coverage semantics for the OHLCV-1D dataset.

This module defines the *canonical* meaning of coverage and completeness for
daily bar data at the contract level. It implements the normative semantics
agreed for MXM V1 and is the single source of truth used by both orchestration
and inspection.

─────────────────────────────────────────────────────────────────────────────
Conceptual model
─────────────────────────────────────────────────────────────────────────────

Coverage is evaluated by relating four distinct notions of time:

1. Surfaces (constraints)
   - interest: the MXM-defined horizon of interest for a contract
   - dataset: the vendor dataset availability window
   - lifecycle: the contract activation / expiration window (if known)

2. Available window
   - The time window in which data *could* exist for this contract,
     derived as dataset ∩ lifecycle (if lifecycle is known).

3. Expected window
   - The time window MXM *expects* to have locally.
   - This window is authoritative and is persisted in the attempts ledger.
   - Empty expected windows (start == end) are first-class and valid.

4. Stored coverage
   - ObservedRange: descriptive min/max timestamps of locally stored bars
     (based on ts_event), not day-aligned.
   - Stored day window: a normalized, day-aligned, half-open window derived
     deterministically from the observed range.

Completeness is defined *only* in terms of window containment:

    stored_window contains expected_window

with the convention that an empty expected window is vacuously complete.

─────────────────────────────────────────────────────────────────────────────
Responsibilities
─────────────────────────────────────────────────────────────────────────────

This module:
- Defines the core range primitives (ObservedRange, DayRange).
- Defines how observed timestamps are normalized into day-aligned windows.
- Defines the canonical completeness predicate.
- Contains no I/O, persistence, or orchestration logic.
- Uses time_utils as the sole authority for timestamp normalization.

This module does NOT:
- Read from or write to Parquet or SQLite.
- Decide ingestion policy or retry behaviour.
- Derive alternative notions of completeness.
- Perform reporting or presentation logic.

─────────────────────────────────────────────────────────────────────────────
Dependency discipline
─────────────────────────────────────────────────────────────────────────────

coverage.py is a pure semantic layer.

- Stores (Parquet, SQLite) provide factual inputs
  (observed ranges, expected windows, row counts).
- Orchestration and inspection import this module to evaluate coverage.
- No other module should re-implement coverage or completeness logic.

Any deviation from these semantics elsewhere in the codebase is a bug.

─────────────────────────────────────────────────────────────────────────────
Design intent
─────────────────────────────────────────────────────────────────────────────

The purpose of this module is to eliminate split-brain interpretations of
coverage (heuristics vs inspection views) and to make correctness explicit,
testable, and shared across all consumers.

Once this module is correct, changes elsewhere should not alter the meaning
of “complete”.
"""

from __future__ import annotations

from dataclasses import dataclass
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
      - start <= end (empty windows with start == end are allowed)
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
    Constraint "surfaces" used to define availability and expectations for a contract.

    All DayRange fields are day-aligned, half-open [start, end).
    """

    interest: DayRange  # MXM refdata "first_day_of_interest" .. "last_trading_day"
    dataset: DayRange  # vendor dataset range (metadata.get_dataset_range), clamped per attempt
    lifecycle: Optional[DayRange]  # activation/expiration constraints, if known


@dataclass(frozen=True)
class CoverageWindows:
    """
    Coverage windows derived from surfaces and local storage.

    - available: what vendor could provide for this contract within dataset + lifecycle
    - expected: what MXM expects to have (authoritative, persisted per attempt)
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
        return self.expected.is_empty

    @property
    def has_data(self) -> bool:
        return self.row_count > 0 and self.stored_window is not None

    @property
    def complete(self) -> bool:
        """
        Canonical completeness predicate relative to the expected window.

        Rules:
          - Empty expected windows are vacuously complete.
          - If there is no stored_window, we are incomplete (unless expected is empty).
          - Otherwise, complete iff stored_window contains expected.
        """
        if self.is_empty_expected:
            return True
        if self.stored_window is None:
            return False
        return self.stored_window.contains(self.expected)

    @property
    def expected_equals_available(self) -> Optional[bool]:
        """
        Diagnostic only (non-authoritative): whether expected equals available.

        This is intentionally NOT called "vendor_final" to avoid semantic collision
        with the authoritative vendor_final flag persisted in the attempts ledger.

        Returns:
          - None if available is unknown
          - True if expected equals available
          - False otherwise
        """
        if self.available is None:
            return None
        return (
            self.expected.start == self.available.start
            and self.expected.end == self.available.end
        )
