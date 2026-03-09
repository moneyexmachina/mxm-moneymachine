# mxm/v1/synthetic_assets/rolling/bdays_to_ltd_series.py
from __future__ import annotations

"""
Session-aligned business-days-to-LTD surface for a ContractSeries.

This module derives the rolling anchor primitive:

    d[t] = bdays_to_ltd(asof=sessions[t], ltd=LTD(contract_id[t]))

Inputs:
- ContractSeries provides (sessions[t], contract_id[t]) aligned 1:1.
- TradingCalendarService resolves product_id -> TradingCalendar.
- RefDataAPI provides contract metadata (FuturesContract.last_trading_day).

Why RefDataAPI is injected
--------------------------
RefDataAPI maintains an internal cache; callers should construct it once and
pass it through runtime services to avoid repeated initialisation and to ensure
consistent cached behaviour across the process.

ContractSeries alignment
------------------------
MXM selector eligibility is defined (see ContractSeries tests):

    eligible iff last_trading_day > as_of_session

Therefore, for an expiring contract with last_trading_day == LTD:
- on as_of_session == LTD, the contract is ineligible and ContractSeries has advanced
- the final session on which the expiring contract appears is LTD - 1 (in session space),
  corresponding to d == 1

Determinism
-----------
Pure function of:
- ContractSeries.sessions
- ContractSeries.contract_ids
- RefDataAPI LTD values
- TradingCalendar.bdays_to_ltd
"""

from dataclasses import dataclass

import numpy as np
from mxm_refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)
from numpy.typing import NDArray

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.contract_series import ContractSeries
from mxm.v1.utils.date_utils import coerce_np_day


class UnknownContractId(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class BDaysToLTDSeries:
    product_id: str
    sessions: NDArray[np.datetime64]  # dtype datetime64[D]
    contract_ids: list[str]
    bdays_to_ltd: NDArray[np.int64]  # dtype int64


def build_bdays_to_ltd_series(
    *,
    series: ContractSeries,
    calendar_service: TradingCalendarService,
    refdata_api: RefDataAPI,
) -> BDaysToLTDSeries:
    sessions = series.sessions
    if sessions.dtype != np.dtype("datetime64[D]"):
        raise TypeError(
            f"ContractSeries.sessions must be datetime64[D], got {sessions.dtype}"
        )

    n = int(len(sessions))
    if len(series.contract_ids) != n:
        raise ValueError(
            "ContractSeries.sessions and contract_ids must have equal length"
        )

    cal = calendar_service.calendar_for_product(series.product_id)

    ltd: NDArray[np.datetime64] = np.empty(n, dtype="datetime64[D]")
    for i, cid in enumerate(series.contract_ids):
        c = refdata_api.get_contract_by_id(cid)
        if c is None:
            raise UnknownContractId(f"Unknown contract_id {cid!r} in ContractSeries")
        ltd[i] = coerce_np_day(c.last_trading_day)

    # Force ndarray-return mode (avoid tuple/int unions for pyright)
    d_raw = cal.bdays_to_ltd(
        sessions,
        ltd,
        strict=True,
        return_projected_flag=False,
    )

    d: NDArray[np.int64] = np.asarray(d_raw, dtype=np.int64)

    return BDaysToLTDSeries(
        product_id=series.product_id,
        sessions=sessions,
        contract_ids=series.contract_ids,
        bdays_to_ltd=d,
    )
