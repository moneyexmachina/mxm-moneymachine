from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np

from mxm.moneymachine.calendars.service import TradingCalendarService
from mxm.moneymachine.contracts.engine import ContractSelectorEngine
from mxm.moneymachine.contracts.relative_ids import canonical_relative_id, short_rel_id
from mxm.moneymachine.contracts.selectors import SelectorRule
from mxm.moneymachine.utils.date_utils import (
    coerce_np_day,
    ensure_1d_day_array,
    searchsorted_exact,
    utc_day_start,
)


@dataclass(frozen=True)
class ContractSeriesSpec:
    """
    Spec for building a ContractSeries.

    Semantics:
      - start_session/end_session are trading sessions (exact membership, inclusive)
      - empty range is forbidden
      - end_session >= start_session
      - rule is a single SelectorRule (one rule per ContractSeries)
    """

    product_id: str
    rule: SelectorRule
    start_session: np.datetime64
    end_session: np.datetime64

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_session", coerce_np_day(self.start_session))
        object.__setattr__(self, "end_session", coerce_np_day(self.end_session))
        if self.end_session < self.start_session:
            raise ValueError("end_session must be >= start_session")


@dataclass(frozen=True)
class ContractSeries:
    """
    Time-indexed realisation of the selector mapping:

        (product_id, as_of_session, rule) -> contract_id

    This is a pure identity surface:
      - one session index
      - one contract_id per session
      - no weights, no roll logic, no holdings, no trades, no P&L
    """

    product_id: str
    canonical_relative_id: str
    short_rel_id: str
    sessions: np.ndarray  # datetime64[D]
    contract_ids: list[str]

    def __post_init__(self) -> None:
        sess = ensure_1d_day_array(self.sessions, name="sessions", allow_empty=False)
        object.__setattr__(self, "sessions", sess)

        if self.sessions.dtype != np.dtype("datetime64[D]"):
            raise TypeError("sessions must be dtype datetime64[D]")

        n = len(self.sessions)
        if len(self.contract_ids) != n:
            raise ValueError("sessions/contract_ids length mismatch")

        if any((not c) for c in self.contract_ids):
            raise ValueError("contract_ids contains empty values")

    # ------------------------------------------------------------------ #
    # Switch helpers (identity-level only; NOT roll events)
    # ------------------------------------------------------------------ #

    def switch_mask(self) -> np.ndarray:
        """
        Boolean mask of sessions where contract_id differs from previous session.

        Requirements (Session 23):
          - switch_mask()[0] == False
          - len(mask) == len(sessions)
          - switch iff contract_ids[t] != contract_ids[t-1]
        """
        n = len(self.sessions)
        if n <= 1:
            return np.zeros(n, dtype=bool)

        prev = np.asarray(self.contract_ids[:-1], dtype=object)
        curr = np.asarray(self.contract_ids[1:], dtype=object)

        m = np.zeros(n, dtype=bool)
        m[1:] = curr != prev
        return m

    def switch_sessions(self) -> np.ndarray:
        """Return the session labels where a switch occurs."""
        return self.sessions[self.switch_mask()]

    def switch_view(self, max_rows: int = 12) -> list[tuple[np.datetime64, str, str]]:
        """
        Return a human-friendly view of switches as (session, from, to) rows.
        """
        idx = np.flatnonzero(self.switch_mask())
        rows: list[tuple[np.datetime64, str, str]] = []
        for raw_i in idx[:max_rows]:
            i = int(raw_i)  # ensure concrete int index for type-checkers
            session_i = cast(np.datetime64, self.sessions[i])
            rows.append((session_i, self.contract_ids[i - 1], self.contract_ids[i]))
        return rows


def build_contract_series(
    *,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    spec: ContractSeriesSpec,
) -> ContractSeries:
    """
    Build a time-indexed contract-identity series by realising `spec.rule` over a
    product's trading-session calendar.

    Locked V1 semantics (Session 23):
      - start/end must be trading sessions (exact membership, inclusive)
      - selection must succeed at every session in-range (hard fail)
      - no partial builds, no skipping, no caching/storage here (pure builder)
    """
    product_id = spec.product_id
    rule = spec.rule

    canon = canonical_relative_id(rule)
    short = short_rel_id(rule)

    # ------------------------------------------------------------------ #
    # Calendar slice: exact, inclusive
    # ------------------------------------------------------------------ #
    cal = calendar_service.calendar_for_product(product_id)
    cal_days = ensure_1d_day_array(
        cal.trading_days, name=f"{product_id} calendar sessions", allow_empty=False
    )

    start_d = coerce_np_day(spec.start_session)
    end_d = coerce_np_day(spec.end_session)

    i0 = searchsorted_exact(cal_days, start_d)
    i1 = searchsorted_exact(cal_days, end_d)
    if i0 is None:
        raise ValueError(f"start_session not in trading calendar: {start_d}")
    if i1 is None:
        raise ValueError(f"end_session not in trading calendar: {end_d}")
    if i1 < i0:
        # Defensive; spec already validates, but keep calendar-index sanity.
        raise ValueError("end_session must be >= start_session")

    sessions = cal_days[i0 : i1 + 1]
    if len(sessions) == 0:
        raise ValueError(
            "ContractSeries cannot be empty (calendar slice produced no sessions)"
        )

    # ------------------------------------------------------------------ #
    # Realise rule over sessions (hard-fail on any failed selection)
    # ------------------------------------------------------------------ #
    contract_ids: list[str] = []

    for d in sessions:
        day = cast(np.datetime64, d)
        as_of_ts = utc_day_start(str(day))
        exp = engine.explain(product_id=product_id, as_of_ts=as_of_ts, rule=rule)

        if exp.outcome != "selected" or exp.selected_contract_id is None:
            raise RuntimeError(
                "Selection failed in ContractSeries build: "
                f"product_id={product_id} "
                f"rule={canon} "
                f"session={day} "
                f"outcome={exp.outcome!r} "
                f"failure_type={exp.failure_type!r} "
                f"message={exp.message!r}"
            )

        contract_ids.append(exp.selected_contract_id)

    return ContractSeries(
        product_id=product_id,
        canonical_relative_id=canon,
        short_rel_id=short,
        sessions=sessions,
        contract_ids=contract_ids,
    )
