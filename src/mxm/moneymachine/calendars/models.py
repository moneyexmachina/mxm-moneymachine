"""
MXM — TradingCalendar model: session labels, optional UTC schedule, and trading-day arithmetic.

This module defines the runtime calendar object used throughout MXM.

Calendar surfaces
-----------------
MXM calendar logic distinguishes two related but separate surfaces:

1) Session labels (required)
   - `trading_days`: numpy datetime64[D]
   - These are *session identifiers*, not UTC day-intervals.
   - They exist over an observed region (authoritative) and optionally a projected region.

2) Session schedule (optional, boundary-aware)
   - `schedule`: pandas.DataFrame indexed by session label, with tz-aware UTC columns:
       - open_utc, close_utc
       - optional: break_start_utc, break_end_utc
   - This surface enables mapping an arbitrary UTC timestamp to:
       - current session label (if in-session)
       - most recent completed session label
       - next session label

Authority & scope
-----------------
- This module does not call upstream calendar packages at runtime.
- Calendars are loaded from pre-materialised artifacts (labels and optionally schedule).
- Time coercion/normalisation is delegated to `mxm.moneymachine.utils.time_utils`.

Non-goals
---------
- Exchange-specific intraday semantics beyond open/close (e.g. auctions, settlement cutovers)
- Contract selection logic (Session 17 proper)
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, NamedTuple, cast

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from mxm.moneymachine.utils.date_utils import (
    coerce_np_day,
    ensure_1d_day_array,
    searchsorted_exact,
)
from mxm.moneymachine.utils.time_utils import UtcTimestampInput, to_utc_ts

NormalizeHow = Literal["raise", "next", "prev"]


class CalendarOutOfRange(ValueError):
    """
    Raised when a timestamp or label cannot be mapped within the calendar coverage.
    """


class ScheduleUnavailable(ValueError):
    """
    Raised when schedule-dependent methods are called but no schedule is present.
    """


class _ScheduleCache(NamedTuple):
    labels: NDArray[np.datetime64]
    opens: NDArray[np.datetime64]
    closes: NDArray[np.datetime64]


@dataclass(frozen=True, slots=True)
class TradingCalendar:
    """
    Immutable trading calendar for MXM.

    Parameters
    ----------
    calendar_id:
        Registry identifier (e.g. "cmes").
    trading_days:
        Strictly increasing ndarray of session labels, dtype datetime64[D].
        This is the effective session-label surface consumed at runtime
        (observed region plus any projected region beyond observed_end).
    observed_end:
        Last session label that is covered by the observed (authoritative) calendar.
        All labels strictly after this boundary are treated as projected.
    schedule:
        Optional session schedule as a pandas DataFrame indexed by session label
        (date-like index), containing tz-aware UTC boundary columns:
          - open_utc (required if schedule is provided)
          - close_utc (required if schedule is provided)
          - break_start_utc (optional)
          - break_end_utc (optional)

        If provided, schedule enables mapping UTC timestamps to session labels via
        boundary-aware logic. If omitted, timestamp→session mapping is unavailable
        (label-only mode).
    """

    calendar_id: str
    trading_days: np.ndarray
    observed_end: np.datetime64
    schedule: pd.DataFrame | None = None

    # Cached derived arrays for fast searchsorted operations (schedule mode).
    _schedule_labels: NDArray[np.datetime64] | None = None
    _schedule_open_utc: NDArray[np.datetime64] | None = None
    _schedule_close_utc: NDArray[np.datetime64] | None = None

    def __post_init__(self) -> None:
        td = ensure_1d_day_array(self.trading_days, "trading_days")
        object.__setattr__(self, "trading_days", td)

        oe = coerce_np_day(self.observed_end)
        object.__setattr__(self, "observed_end", oe)

        # observed_end must be within the effective calendar range
        if oe < td[0] or oe > td[-1]:
            raise ValueError(
                f"observed_end {oe} is outside trading_days range [{td[0]}, {td[-1]}]"
            )

        if self.schedule is not None:
            self._init_schedule_cache(self.schedule)

    def _init_schedule_cache(self, schedule: pd.DataFrame) -> None:
        """
        Validate and cache schedule arrays for fast timestamp->session mapping.

        Invariants (V1)
        --------------
        - Schedule is authoritative only over the observed region.
        - Schedule session labels must match the observed region exactly:
            [trading_days[0], observed_end] inclusive.
        - Schedule labels must be a subset of `trading_days`.
        - open_utc/close_utc are treated as UTC instants; tz-awareness is normalised away
          when converted to numpy datetime64[ns], but the instants remain UTC.
        """

        required = {"open_utc", "close_utc"}
        missing = required.difference(schedule.columns)
        if missing:
            raise ValueError(f"schedule missing required columns: {sorted(missing)}")

        # Coerce index to session labels (datetime64[D]).
        idx_days = np.array(
            [coerce_np_day(x) for x in schedule.index], dtype="datetime64[D]"
        )
        idx_days = ensure_1d_day_array(idx_days, "schedule.index", allow_empty=False)

        # Schedule must cover exactly the observed label range.
        expected_start = self.trading_days[0]
        expected_end = self.observed_end
        if idx_days[0] != expected_start or idx_days[-1] != expected_end:
            raise ValueError(
                f"schedule coverage [{idx_days[0]}, {idx_days[-1]}] must match observed range "
                f"[{expected_start}, {expected_end}] for calendar {self.calendar_id}"
            )

        # Schedule labels must be present in trading_days (defensive; loader should ensure).
        # This is O(n) and fine for V1 sizes.
        for d in idx_days:
            if searchsorted_exact(self.trading_days, d) is None:
                raise ValueError(
                    f"schedule label {d} is not present in trading_days for calendar {self.calendar_id}"
                )

        # Align schedule to the coerced index order (defensive).
        schedule2 = schedule.copy()
        schedule2.index = idx_days

        # Coerce open/close to tz-aware UTC pandas Timestamps, then to numpy datetime64[ns].
        open_idx = pd.DatetimeIndex(
            pd.to_datetime(schedule2["open_utc"], utc=True, errors="raise")
        )
        close_idx = pd.DatetimeIndex(
            pd.to_datetime(schedule2["close_utc"], utc=True, errors="raise")
        )

        open_utc = (
            open_idx.tz_convert("UTC")
            .tz_localize(None)
            .to_numpy(dtype="datetime64[ns]")
        )
        close_utc = (
            close_idx.tz_convert("UTC")
            .tz_localize(None)
            .to_numpy(dtype="datetime64[ns]")
        )

        if open_utc.shape != close_utc.shape:
            raise ValueError("schedule open_utc/close_utc shape mismatch")

        if np.any(open_utc >= close_utc):
            bad = np.where(open_utc >= close_utc)[0][:5]
            raise ValueError(
                f"schedule has non-positive intervals at rows {bad.tolist()}"
            )
        open_utc_arr = cast(NDArray[np.datetime64], open_utc)
        close_utc_arr = cast(NDArray[np.datetime64], close_utc)
        idx_days_arr = cast(NDArray[np.datetime64], idx_days)

        object.__setattr__(self, "_schedule_labels", idx_days_arr)
        object.__setattr__(self, "_schedule_open_utc", open_utc_arr)
        object.__setattr__(self, "_schedule_close_utc", close_utc_arr)
        object.__setattr__(self, "schedule", schedule2)

    # ---------- schedule predicates ----------

    @property
    def has_schedule(self) -> bool:
        return self.schedule is not None

    def _schedule_cache(self) -> _ScheduleCache:
        """
        Return non-optional cached schedule arrays (type-narrowing helper).

        Raises ScheduleUnavailable if schedule/caches are missing.
        """
        if (
            self._schedule_labels is None
            or self._schedule_open_utc is None
            or self._schedule_close_utc is None
        ):
            raise ScheduleUnavailable(
                f"Calendar {self.calendar_id} has no schedule; timestamp→session mapping is unavailable."
            )

        # Cast for pyright: after the None checks, these are concrete ndarrays.
        labels = self._schedule_labels
        opens = self._schedule_open_utc
        closes = self._schedule_close_utc
        return _ScheduleCache(labels=labels, opens=opens, closes=closes)

    # ---------- basic predicates (labels) ----------

    def is_trading_day(self, d: str | np.datetime64) -> bool:
        dd = coerce_np_day(d)
        return searchsorted_exact(self.trading_days, dd) is not None

    def is_projected_day(self, d: str | np.datetime64) -> bool:
        """
        Return True iff `d` is a trading day and lies in the projected region.
        """
        dd = coerce_np_day(d)
        if dd <= self.observed_end:
            return False
        return self.is_trading_day(dd)

    def normalize(
        self, d: str | np.datetime64, how: NormalizeHow = "raise"
    ) -> np.datetime64:
        """
        Normalize an arbitrary date to a trading day.

        - how="raise": raise if not a trading day.
        - how="next": return the next trading day on/after d.
        - how="prev": return the previous trading day on/before d.
        """
        dd = coerce_np_day(d)
        idx = searchsorted_exact(self.trading_days, dd)
        if idx is not None:
            return dd

        if how == "raise":
            raise ValueError(
                f"{dd} is not a trading day for calendar {self.calendar_id}"
            )

        if how == "next":
            i = int(np.searchsorted(self.trading_days, dd, side="left"))
            if i >= self.trading_days.size:
                raise ValueError(
                    f"{dd} is after last available trading day {self.trading_days[-1]}"
                )
            return self.trading_days[i]

        if how == "prev":
            i = int(np.searchsorted(self.trading_days, dd, side="right")) - 1
            if i < 0:
                raise ValueError(
                    f"{dd} is before first available trading day {self.trading_days[0]}"
                )
            return self.trading_days[i]

        raise ValueError(f"Unknown normalize policy: {how!r}")

    # ---------- timestamp -> session mapping (schedule mode) ----------

    def current_session(self, as_of_ts: UtcTimestampInput) -> np.datetime64 | None:
        """
        Return the session label that contains `as_of_ts` (UTC), else None.

        Semantics
        ---------
        A session is active iff:
          open_utc[label] <= as_of_ts_utc < close_utc[label]

        Coverage (V1)
        -------------
        This method is defined only over the observed schedule coverage. If `as_of_ts`
        is outside schedule coverage, CalendarOutOfRange is raised.
        """
        cache = self._schedule_cache()
        t = to_utc_ts(as_of_ts).to_datetime64()
        labels, opens, closes = cache.labels, cache.opens, cache.closes

        # Out of schedule coverage
        if t < opens[0]:
            raise CalendarOutOfRange(
                f"{t} is before first scheduled open for calendar {self.calendar_id}"
            )
        if t >= closes[-1]:
            raise CalendarOutOfRange(
                f"{t} is on/after last scheduled close for calendar {self.calendar_id}"
            )

        i = int(np.searchsorted(opens, t, side="right")) - 1
        if i < 0:
            return None
        if t < closes[i]:
            return labels[i]
        return None

    def current_sessions(
        self,
        ts: pd.Series,
        *,
        out_of_range: Literal["raise", "null"] = "raise",
    ) -> pd.Series:
        """
        Vectorised version of `current_session` over a Series of UTC timestamps.

        Parameters
        ----------
        ts:
            Series of timestamps (tz-aware UTC preferred). Values are coerced via
            `pd.to_datetime(..., utc=True, errors="coerce")`. NaT maps to None.
        out_of_range:
            - "raise": raise CalendarOutOfRange if ANY non-null timestamp lies outside
              observed schedule coverage (same semantics as scalar).
            - "null": map out-of-range timestamps to None.

        Returns
        -------
        pd.Series[object]
            Each element is:
              - np.datetime64 session label if open <= t < close for some session
              - None if not in session (or NaT input, or out-of-range when out_of_range="null")

        Notes
        -----
        - Coverage is the observed schedule only.
        - This method is schedule-dependent; raises ScheduleUnavailable if absent.
        - Deterministic: selection is based on cached schedule arrays and searchsorted.
        """
        cache = self._schedule_cache()
        labels, opens, closes = cache.labels, cache.opens, cache.closes

        # Coerce to UTC timestamps; preserve missing as NaT
        s = pd.to_datetime(ts, utc=True, errors="coerce")
        if s.empty:
            return pd.Series([], index=ts.index, dtype="object")

        # Convert to numpy datetime64[ns] UTC-naive instants for fast comparison
        t = s.dt.tz_convert("UTC").dt.tz_localize(None).to_numpy(dtype="datetime64[ns]")

        # Identify NaT positions (numpy uses NaT sentinel)
        is_nat = np.isnat(t)

        # Out-of-range checks on non-NaT entries
        if not np.all(is_nat):
            t_valid = t[~is_nat]

            below = t_valid < opens[0]
            above = t_valid >= closes[-1]
            if (below | above).any():
                if out_of_range == "raise":
                    # Match scalar messaging style (first offending is enough)
                    first = t_valid[np.where(below | above)[0][0]]
                    if first < opens[0]:
                        raise CalendarOutOfRange(
                            f"{first} is before first scheduled open for calendar {self.calendar_id}"
                        )
                    raise CalendarOutOfRange(
                        f"{first} is on/after last scheduled close for calendar {self.calendar_id}"
                    )
                # else: "null" => treat as unmappable
        else:
            # all NaT -> all None
            return pd.Series([None] * len(ts), index=ts.index, dtype="object")

        # Compute candidate session index for each timestamp:
        # i = rightmost open <= t, i.e. searchsorted(opens, t, side="right") - 1
        idx = np.searchsorted(opens, t, side="right").astype(np.int64) - 1

        # Valid index range and in-session predicate
        in_range_idx = (idx >= 0) & (idx < closes.shape[0])
        in_session = np.zeros_like(in_range_idx, dtype=bool)
        in_session[in_range_idx] = t[in_range_idx] < closes[idx[in_range_idx]]

        # Start with all None
        out: list[object] = [None] * t.shape[0]

        # Assign labels for those in session
        # (labels are dtype datetime64[D] in your cache)
        for pos in np.where(in_session & ~is_nat)[0]:
            out[int(pos)] = labels[int(idx[int(pos)])]

        # If out_of_range="null", ensure out-of-range values are None (already)
        # If out_of_range="raise", we already raised above.

        return pd.Series(out, index=ts.index, dtype="object")

    def most_recent_session(self, as_of_ts: UtcTimestampInput) -> np.datetime64:
        """
        Return the most recent *completed* session label as of `as_of_ts` (UTC).

        Semantics
        ---------
        Returns the last label with:
          close_utc[label] <= as_of_ts_utc

        Coverage (V1)
        -------------
        Defined only over observed schedule coverage. If `as_of_ts` is outside
        schedule coverage, CalendarOutOfRange is raised.
        """
        cache = self._schedule_cache()
        t = to_utc_ts(as_of_ts).to_datetime64()
        labels, opens, closes = cache.labels, cache.opens, cache.closes

        # Out of schedule coverage
        if t < opens[0]:
            raise CalendarOutOfRange(
                f"{t} is before first scheduled open for calendar {self.calendar_id}"
            )
        if t >= closes[-1]:
            raise CalendarOutOfRange(
                f"{t} is on/after last scheduled close for calendar {self.calendar_id}"
            )

        i = int(np.searchsorted(closes, t, side="right")) - 1
        if i < 0:
            # We are before the first close (i.e. during first session); no completed session yet.
            raise CalendarOutOfRange(
                f"{t} is before first scheduled close for calendar {self.calendar_id}"
            )
        return labels[i]

    def next_session(self, as_of_ts: UtcTimestampInput) -> np.datetime64:
        """
        Return the next session label strictly after `as_of_ts` (UTC).

        Semantics
        ---------
        Returns the first label with:
          open_utc[label] > as_of_ts_utc

        Coverage (V1)
        -------------
        Defined only over observed schedule coverage. If `as_of_ts` is outside
        schedule coverage, CalendarOutOfRange is raised.
        """
        cache = self._schedule_cache()

        t = to_utc_ts(as_of_ts).to_datetime64()

        labels, opens, closes = cache.labels, cache.opens, cache.closes

        # Out of schedule coverage
        if t < opens[0]:
            raise CalendarOutOfRange(
                f"{t} is before first scheduled open for calendar {self.calendar_id}"
            )
        if t >= closes[-1]:
            raise CalendarOutOfRange(
                f"{t} is on/after last scheduled close for calendar {self.calendar_id}"
            )

        i = int(np.searchsorted(opens, t, side="right"))
        if i >= opens.size:
            raise CalendarOutOfRange(
                f"{t} is after last scheduled open for calendar {self.calendar_id}"
            )
        return labels[i]

    def as_of_session(self, as_of_ts: UtcTimestampInput) -> np.datetime64:
        """
        Alias for `most_recent_session`.

        This is the MXM "processing anchor" session label: the latest session
        that is complete as of the given UTC timestamp.
        """
        return self.most_recent_session(as_of_ts)

    # ---------- neighborhood operations (labels) ----------

    def next_trading_day(
        self, d: str | np.datetime64, *, strict: bool = True
    ) -> np.datetime64:
        dd = coerce_np_day(d)
        if strict:
            i = searchsorted_exact(self.trading_days, dd)
            if i is None:
                raise ValueError(f"{dd} is not a trading day (strict=True)")
            j = i + 1
        else:
            j = int(np.searchsorted(self.trading_days, dd, side="right"))

        if j >= self.trading_days.size:
            raise ValueError(
                f"No next trading day after {dd}; calendar ends at {self.trading_days[-1]}"
            )
        return self.trading_days[j]

    def prev_trading_day(
        self, d: str | np.datetime64, *, strict: bool = True
    ) -> np.datetime64:
        dd = coerce_np_day(d)
        if strict:
            i = searchsorted_exact(self.trading_days, dd)
            if i is None:
                raise ValueError(f"{dd} is not a trading day (strict=True)")
            j = i - 1
        else:
            j = int(np.searchsorted(self.trading_days, dd, side="left")) - 1

        if j < 0:
            raise ValueError(
                f"No previous trading day before {dd}; calendar starts at {self.trading_days[0]}"
            )
        return self.trading_days[j]

    # ---------- arithmetic (labels) ----------

    def add_trading_days(
        self,
        d: str | np.datetime64,
        n: int,
        *,
        strict: bool = True,
        normalize_how: NormalizeHow = "raise",
    ) -> np.datetime64:
        dd = coerce_np_day(d)
        if strict:
            i = searchsorted_exact(self.trading_days, dd)
            if i is None:
                raise ValueError(f"{dd} is not a trading day (strict=True)")
        else:
            dd = self.normalize(dd, how=normalize_how)
            i = searchsorted_exact(self.trading_days, dd)
            assert i is not None  # by construction

        j = i + n
        if j < 0 or j >= self.trading_days.size:
            raise ValueError(
                f"Result out of range: idx {j} not in [0, {self.trading_days.size - 1}] "
                f"for calendar {self.calendar_id}"
            )
        return self.trading_days[j]

    def trading_days_between(
        self,
        start: str | np.datetime64,
        end: str | np.datetime64,
        *,
        inclusive: Literal["both", "left", "right", "neither"] = "both",
        strict: bool = True,
        normalize_start: NormalizeHow = "raise",
        normalize_end: NormalizeHow = "raise",
    ) -> np.ndarray:
        s = coerce_np_day(start)
        e = coerce_np_day(end)

        if not strict:
            s = self.normalize(s, how=normalize_start)
            e = self.normalize(e, how=normalize_end)

        si = searchsorted_exact(self.trading_days, s)
        ei = searchsorted_exact(self.trading_days, e)
        if strict:
            if si is None:
                raise ValueError(f"start {s} is not a trading day (strict=True)")
            if ei is None:
                raise ValueError(f"end {e} is not a trading day (strict=True)")
        else:
            assert si is not None and ei is not None

        if s > e:
            raise ValueError(f"start {s} is after end {e}")

        lo = si
        hi = ei

        if inclusive in ("neither", "right"):
            lo = lo + 1
        if inclusive in ("neither", "left"):
            hi = hi - 1

        if lo > hi:
            return np.array([], dtype="datetime64[D]")

        return self.trading_days[lo : hi + 1].copy()

    def bdays_to_ltd(
        self,
        asof: str | np.datetime64 | np.ndarray | Sequence[str | np.datetime64],
        ltd: str | np.datetime64 | np.ndarray | Sequence[str | np.datetime64],
        *,
        strict: bool = True,
        normalize_asof: NormalizeHow = "raise",
        normalize_ltd: NormalizeHow = "raise",
        return_projected_flag: bool = False,
    ):
        asof_arr = np.asarray(asof)
        ltd_arr = np.asarray(ltd)
        scalar = asof_arr.shape == () and ltd_arr.shape == ()

        asof_days = _to_days_array(asof_arr)
        ltd_days = _to_days_array(ltd_arr)
        _validate_matching_shapes(asof_days, ltd_days)

        if not strict:
            asof_days, ltd_days = self._normalize_bdays_to_ltd_inputs(
                asof_days=asof_days,
                ltd_days=ltd_days,
                normalize_asof=normalize_asof,
                normalize_ltd=normalize_ltd,
            )

        out, projected_flag = self._compute_bdays_to_ltd_arrays(
            asof_days=asof_days,
            ltd_days=ltd_days,
            strict=strict,
            return_projected_flag=return_projected_flag,
        )

        return _format_bdays_to_ltd_result(
            out=out,
            projected_flag=projected_flag,
            scalar=scalar,
            return_projected_flag=return_projected_flag,
        )

    def _normalize_bdays_to_ltd_inputs(
        self,
        *,
        asof_days: np.ndarray,
        ltd_days: np.ndarray,
        normalize_asof: NormalizeHow,
        normalize_ltd: NormalizeHow,
    ) -> tuple[np.ndarray, np.ndarray]:
        asof_days_normalized = np.empty_like(asof_days)
        ltd_days_normalized = np.empty_like(ltd_days)

        iterator = np.nditer(asof_days, flags=["multi_index", "refs_ok"])
        for _ in iterator:
            index = iterator.multi_index
            asof_days_normalized[index] = self.normalize(
                asof_days[index],
                how=normalize_asof,
            )
            ltd_days_normalized[index] = self.normalize(
                ltd_days[index],
                how=normalize_ltd,
            )

        return asof_days_normalized, ltd_days_normalized

    def _compute_bdays_to_ltd_arrays(
        self,
        *,
        asof_days: np.ndarray,
        ltd_days: np.ndarray,
        strict: bool,
        return_projected_flag: bool,
    ) -> tuple[np.ndarray, np.ndarray]:
        out = np.empty_like(asof_days, dtype=np.int64)
        projected_flag = np.zeros_like(asof_days, dtype=bool)

        iterator = np.nditer(asof_days, flags=["multi_index", "refs_ok"])
        for _ in iterator:
            index = iterator.multi_index
            self._compute_bdays_to_ltd_at_index(
                asof_days=asof_days,
                ltd_days=ltd_days,
                out=out,
                projected_flag=projected_flag,
                index=index,
                strict=strict,
                return_projected_flag=return_projected_flag,
            )

        return out, projected_flag

    def _compute_bdays_to_ltd_at_index(
        self,
        *,
        asof_days: np.ndarray,
        ltd_days: np.ndarray,
        out: np.ndarray,
        projected_flag: np.ndarray,
        index: tuple[int, ...],
        strict: bool,
        return_projected_flag: bool,
    ) -> None:
        asof_index = searchsorted_exact(self.trading_days, asof_days[index])
        ltd_index = searchsorted_exact(self.trading_days, ltd_days[index])

        if strict:
            self._validate_bdays_to_ltd_strict_index(
                asof_days=asof_days,
                ltd_days=ltd_days,
                index=index,
                asof_index=asof_index,
                ltd_index=ltd_index,
            )
        else:
            assert asof_index is not None and ltd_index is not None

        if asof_index is None or ltd_index is None:
            raise AssertionError("validated trading-day indices must not be None")
        out[index] = int(ltd_index - asof_index)

        if return_projected_flag:
            projected_flag[index] = (asof_days[index] > self.observed_end) or (
                ltd_days[index] > self.observed_end
            )

    def _validate_bdays_to_ltd_strict_index(
        self,
        *,
        asof_days: np.ndarray,
        ltd_days: np.ndarray,
        index: tuple[int, ...],
        asof_index: int | None,
        ltd_index: int | None,
    ) -> None:
        if asof_index is None:
            raise ValueError(
                f"asof {asof_days[index]} is not a trading day (strict=True)"
            )

        if ltd_index is None:
            raise ValueError(
                f"ltd {ltd_days[index]} is not a trading day (strict=True)"
            )

    # ---------- session label -> schedule boundary mapping (schedule mode) ----------

    def session_open(self, session: str | np.datetime64) -> pd.Timestamp:
        """
        Return the UTC open timestamp for a given session label.

        Parameters
        ----------
        session:
            Trading session label. Must be coercible to `np.datetime64[D]`.

        Returns
        -------
        pd.Timestamp
            TZ-aware UTC timestamp for the session open.

        Raises
        ------
        ScheduleUnavailable
            If this calendar has no schedule.

        CalendarOutOfRange
            If the requested session lies outside the observed schedule coverage.

        ValueError
            If the session label is not a trading day for this calendar.
        """
        cache = self._schedule_cache()
        session_day = coerce_np_day(session)

        idx = searchsorted_exact(cache.labels, session_day)
        if idx is None:
            if not self.is_trading_day(session_day):
                raise ValueError(
                    f"{session_day} is not a trading day for calendar {self.calendar_id}"
                )

            raise CalendarOutOfRange(
                f"{session_day} is outside observed schedule coverage for calendar "
                f"{self.calendar_id}; schedule is only available through {self.observed_end}"
            )

        return to_utc_ts(pd.Timestamp(cache.opens[idx]))

    def session_close(self, session: str | np.datetime64) -> pd.Timestamp:
        """
        Return the UTC close timestamp for a given session label.

        Parameters
        ----------
        session:
            Trading session label. Must be coercible to `np.datetime64[D]`.

        Returns
        -------
        pd.Timestamp
            TZ-aware UTC timestamp for the session close.

        Raises
        ------
        ScheduleUnavailable
            If this calendar has no schedule.

        CalendarOutOfRange
            If the requested session lies outside the observed schedule coverage.

        ValueError
            If the session label is not a trading day for this calendar.
        """
        cache = self._schedule_cache()
        session_day = coerce_np_day(session)

        idx = searchsorted_exact(cache.labels, session_day)
        if idx is None:
            if not self.is_trading_day(session_day):
                raise ValueError(
                    f"{session_day} is not a trading day for calendar {self.calendar_id}"
                )

            raise CalendarOutOfRange(
                f"{session_day} is outside observed schedule coverage for calendar "
                f"{self.calendar_id}; schedule is only available through {self.observed_end}"
            )

        return to_utc_ts(pd.Timestamp(cache.closes[idx]))

    def session_bounds(
        self,
        session: str | np.datetime64,
    ) -> tuple[pd.Timestamp, pd.Timestamp]:
        """
        Return the UTC (open, close) timestamps for a given session label.

        Parameters
        ----------
        session:
            Trading session label. Must be coercible to `np.datetime64[D]`.

        Returns
        -------
        tuple[pd.Timestamp, pd.Timestamp]
            `(open_utc, close_utc)` as tz-aware UTC timestamps.

        Raises
        ------
        ScheduleUnavailable
            If this calendar has no schedule.

        CalendarOutOfRange
            If the requested session lies outside the observed schedule coverage.

        ValueError
            If the session label is not a trading day for this calendar.
        """
        cache = self._schedule_cache()
        session_day = coerce_np_day(session)

        idx = searchsorted_exact(cache.labels, session_day)
        if idx is None:
            if not self.is_trading_day(session_day):
                raise ValueError(
                    f"{session_day} is not a trading day for calendar {self.calendar_id}"
                )

            raise CalendarOutOfRange(
                f"{session_day} is outside observed schedule coverage for calendar "
                f"{self.calendar_id}; schedule is only available through {self.observed_end}"
            )

        open_ts = to_utc_ts(pd.Timestamp(cache.opens[idx]))
        close_ts = to_utc_ts(pd.Timestamp(cache.closes[idx]))
        return open_ts, close_ts


def _to_days_array(x: np.ndarray) -> np.ndarray:
    if x.shape == ():
        return np.array([coerce_np_day(x.item())], dtype="datetime64[D]")

    out = np.empty(x.size, dtype="datetime64[D]")
    for index, value in enumerate(x.ravel()):
        out[index] = coerce_np_day(value)
    return out.reshape(x.shape)


def _validate_matching_shapes(
    asof_days: np.ndarray,
    ltd_days: np.ndarray,
) -> None:
    if asof_days.shape != ltd_days.shape:
        raise ValueError(
            "asof and ltd must have same shape, "
            f"got {asof_days.shape} vs {ltd_days.shape}"
        )


def _format_bdays_to_ltd_result(
    *,
    out: np.ndarray,
    projected_flag: np.ndarray,
    scalar: bool,
    return_projected_flag: bool,
):
    if scalar:
        out_val = int(out.reshape(-1)[0])
        if return_projected_flag:
            flag_val = bool(projected_flag.reshape(-1)[0])
            return out_val, flag_val
        return out_val

    if return_projected_flag:
        return out, projected_flag
    return out
