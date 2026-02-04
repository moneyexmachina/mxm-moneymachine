"""
MXM V1 — TradingCalendar model and trading-day arithmetic.

This module defines the runtime calendar object used throughout MXM V1.
It operates exclusively on pre-materialised trading-day arrays loaded from
refdata artifacts. No upstream calendar packages are used here.

All dates are represented as numpy datetime64[D] (day precision).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, Sequence, Union

import numpy as np

NormalizeHow = Literal["raise", "next", "prev"]


def _as_day(x: Union[str, np.datetime64]) -> np.datetime64:
    """
    Convert input to numpy datetime64[D].

    Accepts:
      - ISO date string (YYYY-MM-DD)
      - numpy datetime64 with any unit

    Raises:
      - ValueError on invalid date string
    """
    if isinstance(x, np.datetime64):
        return x.astype("datetime64[D]")
    # string-like
    return np.datetime64(x, "D")


def _ensure_1d_days(arr: np.ndarray, name: str) -> np.ndarray:
    """
    Ensure `arr` is a 1D numpy array of dtype datetime64[D] and monotonically increasing.
    """
    if arr.ndim != 1:
        raise ValueError(f"{name} must be 1D, got shape {arr.shape}")
    if arr.dtype.kind != "M":
        raise TypeError(f"{name} must be datetime64 dtype, got {arr.dtype!r}")

    out = arr.astype("datetime64[D]")
    if out.size == 0:
        raise ValueError(f"{name} must be non-empty")

    # Monotonic strictly increasing
    if np.any(out[1:] <= out[:-1]):
        raise ValueError(f"{name} must be strictly increasing (sorted, unique)")
    return out


def _searchsorted_exact(days: np.ndarray, d: np.datetime64) -> Optional[int]:
    """
    Return index of date `d` in sorted unique `days`, else None.
    """
    i = int(np.searchsorted(days, d, side="left"))
    if i < days.size and days[i] == d:
        return i
    return None


@dataclass(frozen=True, slots=True)
class TradingCalendar:
    """
    Immutable trading-day calendar for MXM V1.

    Parameters
    ----------
    calendar_id:
        Registry identifier (e.g. "cmes").
    trading_days:
        Strictly increasing ndarray of trading days, dtype datetime64[D].
        This is the *effective* trading-day surface consumed at runtime
        (observed region plus projected region beyond observed_end).
    observed_end:
        Last trading day that is covered by the observed (authoritative) calendar.
        All trading days strictly after this boundary are treated as projected.
    """

    calendar_id: str
    trading_days: np.ndarray
    observed_end: np.datetime64

    def __post_init__(self) -> None:
        td = _ensure_1d_days(self.trading_days, "trading_days")
        object.__setattr__(self, "trading_days", td)

        oe = _as_day(self.observed_end)
        object.__setattr__(self, "observed_end", oe)

        # observed_end must be within the effective calendar range
        if oe < td[0] or oe > td[-1]:
            raise ValueError(
                f"observed_end {oe} is outside trading_days range [{td[0]}, {td[-1]}]"
            )

    # ---------- basic predicates ----------

    def is_trading_day(self, d: Union[str, np.datetime64]) -> bool:
        dd = _as_day(d)
        return _searchsorted_exact(self.trading_days, dd) is not None

    def is_projected_day(self, d: Union[str, np.datetime64]) -> bool:
        """
        Return True iff `d` is a trading day and lies in the projected region.
        """
        dd = _as_day(d)
        if dd <= self.observed_end:
            return False
        return self.is_trading_day(dd)

    def normalize(
        self, d: Union[str, np.datetime64], how: NormalizeHow = "raise"
    ) -> np.datetime64:
        """
        Normalize an arbitrary date to a trading day.

        - how="raise": raise if not a trading day.
        - how="next": return the next trading day on/after d.
        - how="prev": return the previous trading day on/before d.

        Notes
        -----
        This is the *only* operation that may intentionally coerce a non-trading
        day into a trading day. Consumers must choose the coercion policy.
        """
        dd = _as_day(d)
        idx = _searchsorted_exact(self.trading_days, dd)
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

    # ---------- neighborhood operations ----------

    def next_trading_day(
        self, d: Union[str, np.datetime64], *, strict: bool = True
    ) -> np.datetime64:
        """
        Return the next trading day after `d`.

        If strict=True, `d` must be a trading day.
        If strict=False, `d` is treated as a calendar day and the next trading day
        strictly after it is returned.
        """
        dd = _as_day(d)
        if strict:
            i = _searchsorted_exact(self.trading_days, dd)
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
        self, d: Union[str, np.datetime64], *, strict: bool = True
    ) -> np.datetime64:
        """
        Return the previous trading day before `d`.

        If strict=True, `d` must be a trading day.
        If strict=False, `d` is treated as a calendar day and the previous trading day
        strictly before it is returned.
        """
        dd = _as_day(d)
        if strict:
            i = _searchsorted_exact(self.trading_days, dd)
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

    # ---------- arithmetic ----------

    def add_trading_days(
        self,
        d: Union[str, np.datetime64],
        n: int,
        *,
        strict: bool = True,
        normalize_how: NormalizeHow = "raise",
    ) -> np.datetime64:
        """
        Add `n` trading days to `d`.

        If strict=True, `d` must be a trading day.
        If strict=False, `d` is first normalized using `normalize_how`.

        Examples
        --------
        - add_trading_days("2026-02-04", 0) returns the same day (if trading day)
        - add_trading_days("2026-02-07", 0, strict=False, normalize_how="next") returns next trading day
        """

        dd = _as_day(d)
        if strict:
            i = _searchsorted_exact(self.trading_days, dd)
            if i is None:
                raise ValueError(f"{dd} is not a trading day (strict=True)")
        else:
            dd = self.normalize(dd, how=normalize_how)
            i = _searchsorted_exact(self.trading_days, dd)
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
        start: Union[str, np.datetime64],
        end: Union[str, np.datetime64],
        *,
        inclusive: Literal["both", "left", "right", "neither"] = "both",
        strict: bool = True,
        normalize_start: NormalizeHow = "raise",
        normalize_end: NormalizeHow = "raise",
    ) -> np.ndarray:
        """
        Return the trading days between start and end.

        If strict=True, start and end must be trading days (unless excluded by inclusive).
        If strict=False, boundaries may be normalized according to normalize_start/end.

        inclusive:
          - "both": include start and end
          - "left": include start, exclude end
          - "right": exclude start, include end
          - "neither": exclude both
        """
        s = _as_day(start)
        e = _as_day(end)

        if not strict:
            s = self.normalize(s, how=normalize_start)
            e = self.normalize(e, how=normalize_end)

        si = _searchsorted_exact(self.trading_days, s)
        ei = _searchsorted_exact(self.trading_days, e)
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

    # ---------- bdays_to_ltd ----------

    def bdays_to_ltd(
        self,
        asof: Union[
            str, np.datetime64, np.ndarray, Sequence[Union[str, np.datetime64]]
        ],
        ltd: Union[str, np.datetime64, np.ndarray, Sequence[Union[str, np.datetime64]]],
        *,
        strict: bool = True,
        normalize_asof: NormalizeHow = "raise",
        normalize_ltd: NormalizeHow = "raise",
        return_projected_flag: bool = False,
    ):
        """
        Compute business-days (trading-days) from asof to last-trading-day.

        Semantics
        ---------
        Returns an integer count:
          bdays = idx(ltd) - idx(asof)

        If strict=True, asof and ltd must be trading days.
        If strict=False, they are normalized first.

        If return_projected_flag=True, also returns a boolean flag indicating
        whether either endpoint lies in the projected region.
        """
        # Normalize input to arrays for unified implementation.
        asof_arr = np.asarray(asof)
        ltd_arr = np.asarray(ltd)

        # Detect scalar vs vector
        scalar = asof_arr.shape == () and ltd_arr.shape == ()

        def _to_days_array(x: np.ndarray) -> np.ndarray:
            if x.shape == ():
                return np.array([_as_day(x.item())], dtype="datetime64[D]")
            # elementwise conversion; support strings
            out = np.empty(x.size, dtype="datetime64[D]")
            for k, v in enumerate(x.ravel()):
                out[k] = _as_day(v)
            return out.reshape(x.shape)

        a = _to_days_array(asof_arr)
        l = _to_days_array(ltd_arr)

        if a.shape != l.shape:
            raise ValueError(
                f"asof and ltd must have same shape, got {a.shape} vs {l.shape}"
            )

        if not strict:
            # normalize elementwise (explicit, not vectorised for clarity in V1)
            a2 = np.empty_like(a)
            l2 = np.empty_like(l)
            it = np.nditer(a, flags=["multi_index", "refs_ok"])
            for _ in it:
                idx = it.multi_index
                a2[idx] = self.normalize(a[idx], how=normalize_asof)
                l2[idx] = self.normalize(l[idx], how=normalize_ltd)
            a, l = a2, l2

        # Map to indices (elementwise). V1 simplicity > micro-optimisation.
        out = np.empty_like(a, dtype=np.int64)
        projected_flag = np.zeros_like(a, dtype=bool)

        it2 = np.nditer(a, flags=["multi_index", "refs_ok"])
        for _ in it2:
            idx = it2.multi_index
            ai = _searchsorted_exact(self.trading_days, a[idx])
            li = _searchsorted_exact(self.trading_days, l[idx])
            if strict:
                if ai is None:
                    raise ValueError(
                        f"asof {a[idx]} is not a trading day (strict=True)"
                    )
                if li is None:
                    raise ValueError(f"ltd {l[idx]} is not a trading day (strict=True)")
            else:
                assert ai is not None and li is not None
            out[idx] = int(li - ai)
            if return_projected_flag:
                projected_flag[idx] = (a[idx] > self.observed_end) or (
                    l[idx] > self.observed_end
                )

        if scalar:
            out_val = int(out.reshape(-1)[0])
            if return_projected_flag:
                flag_val = bool(projected_flag.reshape(-1)[0])
                return out_val, flag_val
            return out_val

        if return_projected_flag:
            return out, projected_flag
        return out
