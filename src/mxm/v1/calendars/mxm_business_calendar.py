from __future__ import annotations

"""
MXM V1 — MxMBusinessCalendar model: authoritative MXM business-day surface.

This module defines the runtime business calendar used by MXM V1 strategy and
backtest components.

Calendar surface
----------------
MxMBusinessCalendar is a label-only calendar surface:

1) Business-day labels (required)
   - `business_days`: numpy datetime64[D]
   - These are the session identifiers on which MXM may:
       - evaluate the system
       - form target holdings
       - change holdings
       - mark positions
       - construct daily PnL

Authority & scope
-----------------
- This calendar is authoritative for MXM runtime operation.
- It may be derived from lower-layer calendar/reference inputs, but downstream
  runtime logic should treat it as the operative calendar.
- In V1 this is a label-only surface: no intraday schedule is stored here.

Non-goals
---------
- Venue open/close timestamp mapping
- Product-specific settlement calendars
- Execution-session microstructure
- Intraday routing or partial-session handling
"""

from dataclasses import dataclass
from typing import Literal, Union

import numpy as np
from numpy.typing import NDArray

from mxm.v1.utils.date_utils import (
    coerce_np_day,
    ensure_1d_day_array,
    searchsorted_exact,
)

NormalizeHow = Literal["raise", "next", "prev"]


@dataclass(frozen=True, slots=True)
class MxMBusinessCalendar:
    """
    Immutable MXM business calendar.

    Parameters
    ----------
    calendar_id:
        Stable identifier for the MXM business calendar.
    business_days:
        Strictly increasing ndarray of business-day labels, dtype datetime64[D].
        This is the effective business-day surface consumed at runtime
        (observed region plus any projected region beyond observed_end).
    observed_end:
        Last business-day label that is covered by the observed (authoritative)
        region. All labels strictly after this boundary are treated as projected.

    Notes
    -----
    - This is the authoritative runtime calendar for MXM strategy/backtest logic.
    - It defines the session labels on which MXM may:
        - make decisions
        - change holdings
        - mark positions
        - construct daily PnL
    - It may be derived from one or more lower-layer calendar/reference inputs,
      but downstream runtime logic should treat this object as authoritative.
    - This is a label-only surface in V1.
    """

    calendar_id: str
    business_days: NDArray[np.datetime64]
    observed_end: np.datetime64

    def __post_init__(self) -> None:
        bd = ensure_1d_day_array(self.business_days, "business_days")
        object.__setattr__(self, "business_days", bd)

        oe = coerce_np_day(self.observed_end)
        object.__setattr__(self, "observed_end", oe)

        if oe < bd[0] or oe > bd[-1]:
            raise ValueError(
                f"observed_end {oe} is outside business_days range [{bd[0]}, {bd[-1]}]"
            )

    def is_business_day(self, d: Union[str, np.datetime64]) -> bool:
        dd = coerce_np_day(d)
        return searchsorted_exact(self.business_days, dd) is not None

    def is_projected_day(self, d: Union[str, np.datetime64]) -> bool:
        """
        Return True iff `d` is a business day and lies in the projected region.
        """
        dd = coerce_np_day(d)
        if dd <= self.observed_end:
            return False
        return self.is_business_day(dd)

    def normalize(
        self,
        d: Union[str, np.datetime64],
        how: NormalizeHow = "raise",
    ) -> np.datetime64:
        """
        Normalize an arbitrary date to a business day.

        - how="raise": raise if not a business day.
        - how="next": return the next business day on/after d.
        - how="prev": return the previous business day on/before d.
        """
        if how not in ("raise", "next", "prev"):
            raise ValueError(f"Unknown normalize policy: {how!r}")

        dd = coerce_np_day(d)
        idx = searchsorted_exact(self.business_days, dd)
        if idx is not None:
            return dd

        if how == "raise":
            raise ValueError(
                f"{dd} is not a business day for calendar {self.calendar_id}"
            )

        if how == "next":
            i = int(np.searchsorted(self.business_days, dd, side="left"))
            if i >= self.business_days.size:
                raise ValueError(
                    f"{dd} is after last available business day {self.business_days[-1]}"
                )
            return self.business_days[i]

        if how == "prev":
            i = int(np.searchsorted(self.business_days, dd, side="right")) - 1
            if i < 0:
                raise ValueError(
                    f"{dd} is before first available business day {self.business_days[0]}"
                )
            return self.business_days[i]

    def next_business_day(
        self,
        d: Union[str, np.datetime64],
        *,
        strict: bool = True,
    ) -> np.datetime64:
        dd = coerce_np_day(d)
        if strict:
            i = searchsorted_exact(self.business_days, dd)
            if i is None:
                raise ValueError(f"{dd} is not a business day (strict=True)")
            j = i + 1
        else:
            j = int(np.searchsorted(self.business_days, dd, side="right"))

        if j >= self.business_days.size:
            raise ValueError(
                f"No next business day after {dd}; calendar ends at {self.business_days[-1]}"
            )
        return self.business_days[j]

    def prev_business_day(
        self,
        d: Union[str, np.datetime64],
        *,
        strict: bool = True,
    ) -> np.datetime64:
        dd = coerce_np_day(d)
        if strict:
            i = searchsorted_exact(self.business_days, dd)
            if i is None:
                raise ValueError(f"{dd} is not a business day (strict=True)")
            j = i - 1
        else:
            j = int(np.searchsorted(self.business_days, dd, side="left")) - 1

        if j < 0:
            raise ValueError(
                f"No previous business day before {dd}; calendar starts at {self.business_days[0]}"
            )
        return self.business_days[j]

    def add_business_days(
        self,
        d: Union[str, np.datetime64],
        n: int,
        *,
        strict: bool = True,
        normalize_how: NormalizeHow = "raise",
    ) -> np.datetime64:
        dd = coerce_np_day(d)
        if strict:
            i = searchsorted_exact(self.business_days, dd)
            if i is None:
                raise ValueError(f"{dd} is not a business day (strict=True)")
        else:
            dd = self.normalize(dd, how=normalize_how)
            i = searchsorted_exact(self.business_days, dd)
            assert i is not None

        j = i + n
        if j < 0 or j >= self.business_days.size:
            raise ValueError(
                f"Result out of range: idx {j} not in [0, {self.business_days.size - 1}] "
                f"for calendar {self.calendar_id}"
            )
        return self.business_days[j]

    def business_days_between(
        self,
        start: Union[str, np.datetime64],
        end: Union[str, np.datetime64],
        *,
        inclusive: Literal["both", "left", "right", "neither"] = "both",
        strict: bool = True,
        normalize_start: NormalizeHow = "raise",
        normalize_end: NormalizeHow = "raise",
    ) -> NDArray[np.datetime64]:
        s = coerce_np_day(start)
        e = coerce_np_day(end)

        if not strict:
            s = self.normalize(s, how=normalize_start)
            e = self.normalize(e, how=normalize_end)

        si = searchsorted_exact(self.business_days, s)
        ei = searchsorted_exact(self.business_days, e)
        if strict:
            if si is None:
                raise ValueError(f"start {s} is not a business day (strict=True)")
            if ei is None:
                raise ValueError(f"end {e} is not a business day (strict=True)")
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

        return self.business_days[lo : hi + 1].copy()
