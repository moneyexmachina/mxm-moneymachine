from __future__ import annotations

"""
MXM V1 — MxMBusinessCalendar service.

This module constructs the authoritative MXM business calendar at runtime.

The MxMBusinessCalendar is a machine-level operating calendar:
- it defines the business-day labels on which MXM may
  - evaluate the system
  - form target holdings
  - change holdings
  - mark positions
  - construct daily PnL

V1 construction policy
----------------------
The first implementation constructs a single MXM business calendar by:

1) loading a base TradingCalendar
2) excluding minimal US full-closure holidays from that calendar

This is intentionally simple and conservative. It provides a first
machine-level calendar suitable for synthetic-asset backtesting, while
leaving room for later refinement (e.g. early closes, broader universe
constraints, or persisted business-calendar artifacts).

This is read-side runtime code:
- no persistence / mutation
- no registry writes
- optional in-memory cache
"""

import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from numpy.typing import NDArray

from mxm.v1.calendars.holiday_rules import us_full_closure_holidays_minimal
from mxm.v1.calendars.loader import load_calendar
from mxm.v1.calendars.models import TradingCalendar
from mxm.v1.calendars.mxm_business_calendar import MxMBusinessCalendar
from mxm.v1.utils.date_utils import coerce_np_day


class MxMBusinessCalendarError(RuntimeError):
    """Base error for MXM business calendar construction failures."""


class EmptyBusinessCalendar(MxMBusinessCalendarError):
    """Raised when business-calendar filtering removes all candidate sessions."""


class EmptyObservedBusinessRegion(MxMBusinessCalendarError):
    """Raised when no observed business days remain after filtering."""


def canonical_business_calendar_id(value: str) -> str:
    """
    Canonicalise MXM business calendar ids for runtime use.

    Policy:
      - strip whitespace
      - lower-case
    """
    return value.strip().lower()


@dataclass(slots=True)
class MxMBusinessCalendarService:
    """
    Runtime constructor/cache for the single MXM business calendar.

    Parameters
    ----------
    base_trading_calendar_id:
        Registry id of the base TradingCalendar used as the initial candidate
        session surface for MXM business-day construction.
    calendars_root:
        Optional alternate calendars root for loading TradingCalendar artifacts.
    business_calendar_id:
        Stable identifier for the resulting MXM business calendar.
    """

    base_trading_calendar_id: str
    calendars_root: Optional[Path] = None
    business_calendar_id: str = "mxm_v1_business"
    _cache: MxMBusinessCalendar | None = field(default=None, init=False)

    def get_calendar(self) -> MxMBusinessCalendar:
        """
        Return the authoritative MXM business calendar.

        The result is cached in-memory after first construction.
        """
        if self._cache is not None:
            return self._cache

        base_calendar = load_calendar(
            canonical_business_calendar_id(self.base_trading_calendar_id),
            root=self.calendars_root,
        )

        business_calendar = self._build_from_trading_calendar(base_calendar)
        self._cache = business_calendar
        return business_calendar

    def _build_from_trading_calendar(
        self,
        base_calendar: TradingCalendar,
    ) -> MxMBusinessCalendar:
        """
        Construct MxMBusinessCalendar from a base TradingCalendar by excluding
        minimal US full-closure holidays.
        """
        excluded_days = self._holiday_exclusions_for_calendar(base_calendar)
        business_days = self._filter_business_days(
            trading_days=base_calendar.trading_days,
            excluded_days=excluded_days,
        )

        if business_days.size == 0:
            raise EmptyBusinessCalendar(
                f"Business-calendar filtering removed all sessions from "
                f"base trading calendar {base_calendar.calendar_id!r}"
            )

        observed_end = self._derive_observed_end(
            business_days=business_days,
            base_observed_end=base_calendar.observed_end,
            base_calendar_id=base_calendar.calendar_id,
        )

        return MxMBusinessCalendar(
            calendar_id=canonical_business_calendar_id(self.business_calendar_id),
            business_days=business_days,
            observed_end=observed_end,
        )

    def _holiday_exclusions_for_calendar(
        self,
        calendar: TradingCalendar,
    ) -> NDArray[np.datetime64]:
        """
        Return the set of holiday session labels to exclude from the base calendar.

        Policy
        ------
        For V1, exclude the minimal US full-closure holiday set for all years
        covered by the base calendar.
        """
        start_day = coerce_np_day(calendar.trading_days[0])
        end_day = coerce_np_day(calendar.trading_days[-1])

        start_year = int(str(start_day)[:4])
        end_year = int(str(end_day)[:4])

        holidays: set[dt.date] = set()
        for year in range(start_year, end_year + 1):
            holidays |= us_full_closure_holidays_minimal(year)

        out = np.array(
            [np.datetime64(d, "D") for d in sorted(holidays)],
            dtype="datetime64[D]",
        )
        return out

    @staticmethod
    def _filter_business_days(
        *,
        trading_days: NDArray[np.datetime64],
        excluded_days: NDArray[np.datetime64],
    ) -> NDArray[np.datetime64]:
        """
        Remove excluded days from the candidate trading-day surface.

        Exclusions that are not present in the trading-day surface are ignored.
        """
        if excluded_days.size == 0:
            return trading_days.copy()

        mask = ~np.isin(trading_days, excluded_days)
        return trading_days[mask].copy()

    @staticmethod
    def _derive_observed_end(
        *,
        business_days: NDArray[np.datetime64],
        base_observed_end: np.datetime64,
        base_calendar_id: str,
    ) -> np.datetime64:
        """
        Derive observed_end for the filtered business-day surface.

        Policy
        ------
        Use the greatest retained business day that is <= base_observed_end.

        This preserves the meaning:
            last authoritative day in the observed region
        after holiday exclusions have been applied.
        """
        observed_mask = business_days <= base_observed_end
        if not np.any(observed_mask):
            raise EmptyObservedBusinessRegion(
                f"Holiday filtering removed all observed-region business days from "
                f"base trading calendar {base_calendar_id!r} through "
                f"observed_end={base_observed_end}"
            )

        return business_days[observed_mask][-1]
