"""
MXM V1 — Trading-calendar distance-to-LTD surface on MXM business-session support.

This module derives the canonical roll-clock primitive used in MXM V1:

    d[t] = trading_days_to_ltd(
        asof = prev_trading_session_on_or_before(business_session[t]),
        ltd  = LTD(contract_id[t]),
    )

Semantics
---------
This is a **trading-calendar** notion of distance to LTD, evaluated on an
MXM business-session surface.

Inputs:
- `sessions[t]` are MXM business-session labels
- `contract_id[t]` is aligned 1:1 with `sessions[t]`
- `TradingCalendarService` resolves `product_id -> TradingCalendar`
- `RefDataAPI` provides contract metadata (`last_trading_day`)

The output answers:

    "How many product trading sessions remain until LTD, as of the trading
     session aligned to this MXM business session?"

This defines the roll timing used by synthetic assets in V1.

Alignment policy
----------------
Each MXM business session is aligned to trading-session support via:

    how = "prev"

i.e. each business session maps to the greatest trading session less than
or equal to it.

This is consistent with:
- contract identity projection (trading → business)
- execution timing assumptions in V1

Counting convention
-------------------
Distance is defined in trading-session space:

    d = idx(ltd) - idx(asof)

where both indices are taken on the product trading calendar.

Determinism
-----------
Pure function of:
- input MXM business-session labels
- input contract_ids
- TradingCalendar.bdays_to_ltd semantics
- RefDataAPI LTD values
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from mxm.moneymachine.calendars.mapping import map_business_to_trading_sessions
from mxm.moneymachine.calendars.service import TradingCalendarService
from mxm.moneymachine.utils.date_utils import coerce_np_day, ensure_1d_day_array
from mxm.refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)


class UnknownContractId(ValueError):
    """Raised when a contract_id in the input series cannot be resolved."""


@dataclass(frozen=True, slots=True)
class TradingDaysToLTDOnBusinessSessions:
    """
    Trading-calendar distance-to-LTD surface aligned 1:1 to an MXM
    business-session series.
    """

    product_id: str
    sessions: NDArray[np.datetime64]  # dtype datetime64[D], MXM business sessions
    contract_ids: list[str]
    trading_days_to_ltd: NDArray[np.int64]  # dtype int64

    def __post_init__(self) -> None:
        sess = ensure_1d_day_array(self.sessions, name="sessions", allow_empty=False)
        object.__setattr__(self, "sessions", sess)

        if len(self.contract_ids) != len(self.sessions):
            raise ValueError("sessions and contract_ids must have equal length")

        d = np.asarray(self.trading_days_to_ltd)
        if d.ndim != 1:
            raise TypeError("trading_days_to_ltd must be a 1D array")
        if d.dtype != np.dtype("int64"):
            d = np.asarray(d, dtype=np.int64)
            object.__setattr__(self, "trading_days_to_ltd", d)

        if len(d) != len(self.sessions):
            raise ValueError("sessions and trading_days_to_ltd must have equal length")


def build_trading_days_to_ltd_on_business_sessions(
    *,
    product_id: str,
    sessions: NDArray[np.datetime64],
    contract_ids: list[str],
    calendar_service: TradingCalendarService,
    refdata_api: RefDataAPI,
) -> TradingDaysToLTDOnBusinessSessions:
    """
    Build a trading-calendar distance-to-LTD surface from an MXM
    business-session-aligned contract identity surface.

    Parameters
    ----------
    product_id:
        Product identifier carried through for provenance / alignment.
    sessions:
        MXM business sessions, dtype datetime64[D].
    contract_ids:
        Contract identity aligned 1:1 with `sessions`.
    calendar_service:
        Resolves product_id -> TradingCalendar.
    refdata_api:
        Resolves contract_id -> FuturesContract metadata, including LTD.

    Returns
    -------
    TradingDaysToLTDOnBusinessSessions
        MXM-business-session-aligned integer distance-to-LTD surface, where the
        values are counted in product trading-session space.

    Raises
    ------
    TypeError
        If `sessions` is not dtype datetime64[D].
    ValueError
        If sessions/contract_ids lengths differ.
    UnknownContractId
        If any contract_id cannot be resolved from refdata.
    """
    sess = ensure_1d_day_array(sessions, name="sessions", allow_empty=False)
    if len(contract_ids) != len(sess):
        raise ValueError("sessions and contract_ids must have equal length")

    cal = calendar_service.calendar_for_product(product_id)

    mapping = map_business_to_trading_sessions(
        business_sessions=sess,
        trading_sessions=cal.trading_days,
        how="prev",
    )
    mapped_sessions = mapping.mapped_sessions

    n = len(sess)

    ltd: NDArray[np.datetime64] = np.empty(n, dtype="datetime64[D]")
    for i, cid in enumerate(contract_ids):
        contract = refdata_api.get_contract_by_id(cid)
        ltd[i] = coerce_np_day(contract.last_trading_day)

    d_raw = cal.bdays_to_ltd(
        mapped_sessions,
        ltd,
        strict=True,
        return_projected_flag=False,
    )
    d: NDArray[np.int64] = np.asarray(d_raw, dtype=np.int64)

    return TradingDaysToLTDOnBusinessSessions(
        product_id=product_id,
        sessions=sess,
        contract_ids=contract_ids,
        trading_days_to_ltd=d,
    )
