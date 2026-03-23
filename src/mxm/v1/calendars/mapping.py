from __future__ import annotations

"""
MXM V1 — Calendar Surface Mapping.

This module provides explicit mapping between different calendar surfaces.

Current V1 use case
-------------------
The primary use case is mapping the global MXM business-day calendar onto a
product-specific trading calendar.

This is required because:

- MXM business days define when the machine operates
- product trading calendars define when a product has trading sessions
- these two calendar surfaces are not assumed to be identical

In particular, a business session may:
- match a product trading session exactly
- fall on a day where the product has no trading session
- lie outside the product trading-calendar support entirely

This module makes the mapping policy explicit and testable.

Design intent
-------------
The mapping layer is intentionally read-only and policy-driven.

It does not:
- build calendars
- modify calendars
- infer business-day policies
- select contracts
- mark prices or construct PnL

Instead, it answers the narrower question:

    "Given a target business-session surface and a source trading-session
    surface, which trading session should be used for each business session?"

Supported alignment policies
----------------------------
- exact:
    Require exact same-day membership for every target business session.
- prev:
    Map each business session to the greatest trading session <= it.
- next:
    Map each business session to the smallest trading session >= it.

V1 recommendation
-----------------
For projecting product contract-identity state onto MXM business days, the
recommended default policy is:

    how="prev"

because it is causal, conservative, and does not look ahead.

Notes
-----
- Inputs are expected to be 1D strictly increasing datetime64[D] arrays.
- Output preserves business-session order exactly.
- Mapping failures raise explicit exceptions rather than silently skipping
  or fabricating support.
"""

from dataclasses import dataclass
from typing import Literal

import numpy as np
from numpy.typing import NDArray

from mxm.v1.utils.date_utils import ensure_1d_day_array

AlignmentHow = Literal["exact", "prev", "next"]


class CalendarMappingError(ValueError):
    """Base error for calendar-surface mapping failures."""


class MissingCalendarMapping(CalendarMappingError):
    """Raised when a target business session cannot be mapped under the chosen policy."""


@dataclass(frozen=True, slots=True)
class CalendarMapping:
    """
    Mapping from target business sessions onto source trading sessions.

    Parameters
    ----------
    business_sessions:
        Target business-day support to be expressed.
    mapped_sessions:
        Effective trading-session label used for each business session.
    is_exact:
        Boolean mask indicating whether each mapping was exact
        (business_session == mapped_session).
    how:
        Alignment policy used to construct the mapping.
    """

    business_sessions: NDArray[np.datetime64]
    mapped_sessions: NDArray[np.datetime64]
    is_exact: NDArray[np.bool_]
    how: AlignmentHow

    def __post_init__(self) -> None:
        bs = ensure_1d_day_array(
            self.business_sessions,
            name="business_sessions",
            allow_empty=False,
        )
        object.__setattr__(self, "business_sessions", bs)

        ms = np.asarray(self.mapped_sessions)
        if ms.ndim != 1:
            raise TypeError("mapped_sessions must be a 1D array")
        if ms.dtype != np.dtype("datetime64[D]"):
            raise TypeError("mapped_sessions must be dtype datetime64[D]")
        if len(ms) == 0:
            raise ValueError("mapped_sessions must not be empty")
        if len(ms) >= 2 and np.any(ms[1:] < ms[:-1]):
            raise ValueError("mapped_sessions must be monotonic non-decreasing")
        object.__setattr__(self, "mapped_sessions", ms)

        if self.is_exact.ndim != 1:
            raise TypeError("is_exact must be a 1D boolean array")
        if self.is_exact.dtype != np.dtype(bool):
            raise TypeError("is_exact must have dtype bool")

        n = len(bs)
        if len(ms) != n or len(self.is_exact) != n:
            raise ValueError(
                "business_sessions, mapped_sessions, and is_exact must have equal length"
            )

    def exact_count(self) -> int:
        """Return the number of exact business->trading session matches."""
        return int(self.is_exact.sum())

    def inexact_count(self) -> int:
        """Return the number of inexact business->trading session mappings."""
        return int((~self.is_exact).sum())


def map_business_to_trading_sessions(
    *,
    business_sessions: NDArray[np.datetime64],
    trading_sessions: NDArray[np.datetime64],
    how: AlignmentHow = "prev",
) -> CalendarMapping:
    """
    Map business sessions onto trading sessions using an explicit alignment policy.

    Parameters
    ----------
    business_sessions:
        Target MXM business-day support.
    trading_sessions:
        Source product trading-session support.
    how:
        Alignment policy:
        - "exact": require exact same-day membership
        - "prev": map to greatest trading session <= business session
        - "next": map to smallest trading session >= business session

    Returns
    -------
    CalendarMapping
        The business-session surface, mapped trading-session surface, and
        exact/inexact match diagnostics.

    Raises
    ------
    MissingCalendarMapping
        If any business session cannot be mapped under the chosen policy.
    ValueError
        If `how` is not a recognised alignment policy.
    """
    bs = ensure_1d_day_array(
        business_sessions,
        name="business_sessions",
        allow_empty=False,
    )
    ts = ensure_1d_day_array(
        trading_sessions,
        name="trading_sessions",
        allow_empty=False,
    )

    if how == "exact":
        idx = np.searchsorted(ts, bs, side="left")
        exact = np.zeros(len(bs), dtype=bool)

        ok = idx < len(ts)
        if np.any(ok):
            valid_idx = idx[ok]
            exact[ok] = ts[valid_idx] == bs[ok]

        if not np.all(exact):
            first_bad = int(np.flatnonzero(~exact)[0])
            raise MissingCalendarMapping(
                "Business session has no exact trading-session match: "
                f"business_session={bs[first_bad]}"
            )

        mapped = ts[idx]
        return CalendarMapping(
            business_sessions=bs,
            mapped_sessions=mapped,
            is_exact=np.ones(len(bs), dtype=bool),
            how=how,
        )

    if how == "prev":
        idx = np.searchsorted(ts, bs, side="right") - 1
        ok = idx >= 0

        if not np.all(ok):
            first_bad = int(np.flatnonzero(~ok)[0])
            raise MissingCalendarMapping(
                "Business session lies before first available trading session "
                f"under how='prev': business_session={bs[first_bad]}"
            )

        mapped = ts[idx]
        return CalendarMapping(
            business_sessions=bs,
            mapped_sessions=mapped,
            is_exact=(mapped == bs),
            how=how,
        )

    if how == "next":
        idx = np.searchsorted(ts, bs, side="left")
        ok = idx < len(ts)

        if not np.all(ok):
            first_bad = int(np.flatnonzero(~ok)[0])
            raise MissingCalendarMapping(
                "Business session lies after last available trading session "
                f"under how='next': business_session={bs[first_bad]}"
            )

        mapped = ts[idx]
        return CalendarMapping(
            business_sessions=bs,
            mapped_sessions=mapped,
            is_exact=(mapped == bs),
            how=how,
        )

    raise ValueError(f"Unknown alignment policy: {how!r}")
