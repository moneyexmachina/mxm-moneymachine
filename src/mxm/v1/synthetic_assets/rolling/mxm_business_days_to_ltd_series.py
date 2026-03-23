from __future__ import annotations

"""
MXM V1 — MXM business-day distance-to-LTD surface.

This module derives the machine-time roll-clock primitive:

    d[t] = mxm_business_days_to_ltd(
        asof=sessions[t],
        ltd=LTD(contract_id[t]),
    )

Semantics
---------
This is explicitly an **MXM business-calendar** notion of distance to LTD.

Inputs:
- `sessions[t]` are MXM business sessions
- `contract_id[t]` is aligned 1:1 with `sessions[t]`
- `MxMBusinessCalendar` defines the operative machine-time session surface
- `RefDataAPI` provides contract metadata (`last_trading_day`)

Therefore the output answers:

    "How many MXM business sessions remain until LTD?"

and not:

    "How many product trading sessions remain until LTD?"

That latter market-time notion belongs in
`trading_days_to_ltd_series.py`.

Counting convention
-------------------
Distance is defined as the count of MXM business days strictly after
`asof_session` and less than or equal to LTD.

Equivalently, if:
- `i_s` is the exact index of `asof_session` in the MXM business calendar
- `i_l` is the index of the greatest business day <= LTD

then:

    d = i_l - i_s

This preserves the desired contract-selection semantics:
- if `last_trading_day == LTD`
- and a contract is eligible iff `LTD > as_of_session`
- then on the final eligible business session before LTD, `d == 1`

Determinism
-----------
Pure function of:
- input business-session labels
- input contract_ids
- RefDataAPI LTD values
- MxMBusinessCalendar.business_days
"""

from dataclasses import dataclass

import numpy as np
from mxm_refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)
from numpy.typing import NDArray

from mxm.v1.calendars.mxm_business_calendar import MxMBusinessCalendar
from mxm.v1.utils.date_utils import (
    coerce_np_day,
    ensure_1d_day_array,
    searchsorted_exact,
)


class UnknownContractId(ValueError):
    """Raised when a contract_id in the input series cannot be resolved."""


class SessionNotInMXMBusinessCalendar(ValueError):
    """Raised when an input session is not an exact MXM business day."""


class LTDPrecedesSession(ValueError):
    """Raised when LTD maps to a business day strictly before the input session."""


class NoBusinessDayOnOrBeforeLTD(ValueError):
    """Raised when LTD lies before the first available MXM business day."""


@dataclass(frozen=True, slots=True)
class MXMBusinessDaysToLTDSeries:
    """
    MXM business-day distance-to-LTD surface aligned 1:1 to a business-session series.
    """

    product_id: str
    sessions: NDArray[np.datetime64]  # dtype datetime64[D], MXM business sessions
    contract_ids: list[str]
    mxm_business_days_to_ltd: NDArray[np.int64]  # dtype int64

    def __post_init__(self) -> None:
        sess = ensure_1d_day_array(self.sessions, name="sessions", allow_empty=False)
        object.__setattr__(self, "sessions", sess)

        if len(self.contract_ids) != len(self.sessions):
            raise ValueError("sessions and contract_ids must have equal length")

        d = np.asarray(self.mxm_business_days_to_ltd)
        if d.ndim != 1:
            raise TypeError("mxm_business_days_to_ltd must be a 1D array")
        if d.dtype != np.dtype("int64"):
            d = np.asarray(d, dtype=np.int64)
            object.__setattr__(self, "mxm_business_days_to_ltd", d)

        if len(d) != len(self.sessions):
            raise ValueError(
                "sessions and mxm_business_days_to_ltd must have equal length"
            )


def build_mxm_business_days_to_ltd_series(
    *,
    product_id: str,
    sessions: NDArray[np.datetime64],
    contract_ids: list[str],
    mxm_business_calendar: MxMBusinessCalendar,
    refdata_api: RefDataAPI,
) -> MXMBusinessDaysToLTDSeries:
    """
    Build an MXM business-day distance-to-LTD surface from a business-session-aligned
    contract identity surface.

    Parameters
    ----------
    product_id:
        Product identifier carried through for provenance / alignment.
    sessions:
        MXM business sessions, dtype datetime64[D].
    contract_ids:
        Contract identity aligned 1:1 with `sessions`.
    mxm_business_calendar:
        Authoritative MXM business calendar.
    refdata_api:
        Resolves contract_id -> FuturesContract metadata, including LTD.

    Returns
    -------
    MXMBusinessDaysToLTDSeries
        MXM-business-session-aligned integer distance-to-LTD surface.

    Raises
    ------
    TypeError
        If `sessions` is not dtype datetime64[D].
    ValueError
        If sessions/contract_ids lengths differ.
    SessionNotInMXMBusinessCalendar
        If any session is not an exact member of the MXM business calendar.
    UnknownContractId
        If any contract_id cannot be resolved from refdata.
    NoBusinessDayOnOrBeforeLTD
        If LTD lies before the first MXM business day.
    LTDPrecedesSession
        If LTD maps to a business day strictly before the input session.
    """
    sess = ensure_1d_day_array(sessions, name="sessions", allow_empty=False)
    if len(contract_ids) != len(sess):
        raise ValueError("sessions and contract_ids must have equal length")

    cal_days = mxm_business_calendar.business_days
    n = len(sess)

    out = np.empty(n, dtype=np.int64)

    for i, (s_raw, cid) in enumerate(zip(sess, contract_ids)):
        session = coerce_np_day(s_raw)

        session_idx = searchsorted_exact(cal_days, session)
        if session_idx is None:
            raise SessionNotInMXMBusinessCalendar(
                f"session {session} is not an exact MXM business day"
            )

        contract = refdata_api.get_contract_by_id(cid)
        if contract is None:
            raise UnknownContractId(f"Unknown contract_id {cid!r}")

        ltd = coerce_np_day(contract.last_trading_day)

        # Greatest business day <= LTD
        ltd_idx = int(np.searchsorted(cal_days, ltd, side="right")) - 1
        if ltd_idx < 0:
            raise NoBusinessDayOnOrBeforeLTD(
                "No MXM business day exists on or before LTD: "
                f"contract_id={cid!r} ltd={ltd}"
            )

        if ltd_idx < session_idx:
            raise LTDPrecedesSession(
                "LTD maps to a business day before the input session: "
                f"contract_id={cid!r} session={session} ltd={ltd}"
            )

        out[i] = np.int64(ltd_idx - session_idx)

    return MXMBusinessDaysToLTDSeries(
        product_id=product_id,
        sessions=sess,
        contract_ids=contract_ids,
        mxm_business_days_to_ltd=out,
    )
