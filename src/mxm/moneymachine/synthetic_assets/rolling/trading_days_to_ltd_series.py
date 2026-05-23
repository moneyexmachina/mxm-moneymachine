"""
MXM V1 — Trading-calendar days-to-LTD surface for a trading-session-aligned series.

This module derives the market-time roll-clock primitive:

    d[t] = trading_days_to_ltd(asof=sessions[t], ltd=LTD(contract_id[t]))

Semantics
---------
This is explicitly a **trading-calendar** notion of distance to LTD.

Inputs:
- `sessions[t]` are product trading sessions
- `contract_id[t]` is aligned 1:1 with `sessions[t]`
- `TradingCalendarService` resolves `product_id -> TradingCalendar`
- `RefDataAPI` provides contract metadata (`last_trading_day`)

Therefore the output answers:

    "How many product trading sessions remain until LTD?"

and not:

    "How many MXM business days remain until LTD?"

That latter machine-time notion belongs in a separate module.

Why RefDataAPI is injected
--------------------------
RefDataAPI maintains an internal cache; callers should construct it once and
pass it through runtime services to avoid repeated initialisation and to ensure
consistent cached behaviour across the process.

ContractSeries alignment
------------------------
MXM selector eligibility is defined (see ContractSeries tests):

    eligible iff last_trading_day > as_of_session

Therefore, for an expiring contract with `last_trading_day == LTD`:
- on `as_of_session == LTD`, the contract is ineligible and ContractSeries has advanced
- the final session on which the expiring contract appears is LTD - 1
  (in trading-session space), corresponding to `d == 1`

Determinism
-----------
Pure function of:
- ContractSeries.sessions
- ContractSeries.contract_ids
- RefDataAPI LTD values
- TradingCalendar.trading_days_to_ltd / bdays_to_ltd semantics
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from mxm.moneymachine.calendars.service import TradingCalendarService
from mxm.moneymachine.contracts.contract_series import ContractSeries
from mxm.moneymachine.utils.date_utils import coerce_np_day
from mxm.refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)


class UnknownContractId(ValueError):
    """Raised when a contract_id in the input series cannot be resolved."""


@dataclass(frozen=True, slots=True)
class TradingDaysToLTDSeries:
    """
    Trading-calendar days-to-LTD surface aligned 1:1 to a trading-session series.
    """

    product_id: str
    sessions: NDArray[np.datetime64]  # dtype datetime64[D], trading sessions
    contract_ids: list[str]
    trading_days_to_ltd: NDArray[np.int64]  # dtype int64


def build_trading_days_to_ltd_series(
    *,
    series: ContractSeries,
    calendar_service: TradingCalendarService,
    refdata_api: RefDataAPI,
) -> TradingDaysToLTDSeries:
    """
    Build a trading-calendar days-to-LTD surface from a trading-session-aligned
    ContractSeries.

    Parameters
    ----------
    series:
        Trading-session-aligned contract identity surface.
    calendar_service:
        Resolves product_id -> TradingCalendar.
    refdata_api:
        Resolves contract_id -> FuturesContract metadata, including LTD.

    Returns
    -------
    TradingDaysToLTDSeries
        Trading-session-aligned integer distance-to-LTD surface.

    Raises
    ------
    TypeError
        If `series.sessions` is not dtype datetime64[D].
    ValueError
        If sessions/contract_ids lengths differ.
    UnknownContractId
        If any contract_id cannot be resolved from refdata.
    """
    sessions = series.sessions
    if sessions.dtype != np.dtype("datetime64[D]"):
        raise TypeError(
            f"ContractSeries.sessions must be datetime64[D], got {sessions.dtype}"
        )

    n = len(sessions)
    if len(series.contract_ids) != n:
        raise ValueError(
            "ContractSeries.sessions and contract_ids must have equal length"
        )

    cal = calendar_service.calendar_for_product(series.product_id)

    ltd: NDArray[np.datetime64] = np.empty(n, dtype="datetime64[D]")
    for i, cid in enumerate(series.contract_ids):
        contract = refdata_api.get_contract_by_id(cid)
        ltd[i] = coerce_np_day(contract.last_trading_day)

    # Force ndarray-return mode to keep types stable.
    d_raw = cal.bdays_to_ltd(
        sessions,
        ltd,
        strict=True,
        return_projected_flag=False,
    )
    d: NDArray[np.int64] = np.asarray(d_raw, dtype=np.int64)

    return TradingDaysToLTDSeries(
        product_id=series.product_id,
        sessions=sessions,
        contract_ids=series.contract_ids,
        trading_days_to_ltd=d,
    )
