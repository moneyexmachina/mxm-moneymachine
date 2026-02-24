from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, cast

import numpy as np

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.contracts.selectors import SelectorRule
from mxm.v1.utils.date_utils import (
    coerce_np_day,
    ensure_1d_day_array,
    searchsorted_exact,
)


@dataclass(frozen=True)
class ContractSeriesSpec:
    product_id: str
    rule: "SelectorRule"
    start_session: np.datetime64
    end_session: np.datetime64

    def __post_init__(self) -> None:
        object.__setattr__(self, "start_session", coerce_np_day(self.start_session))
        object.__setattr__(self, "end_session", coerce_np_day(self.end_session))
        if self.end_session < self.start_session:
            raise ValueError("end_session must be >= start_session")


@dataclass(frozen=True)
class ContractSeries:
    product_id: str
    canonical_relative_id: str
    short_rel_id: str
    sessions: np.ndarray  # datetime64[D]
    contract_ids: list[str]
    period_ids: list[str]

    def __post_init__(self) -> None:
        sess = ensure_1d_day_array(self.sessions, name="sessions", allow_empty=False)
        object.__setattr__(self, "sessions", sess)

        n = int(sess.size)
        if len(self.contract_ids) != n or len(self.period_ids) != n:
            raise ValueError("sessions/contract_ids/period_ids length mismatch")
        if self.sessions.dtype != np.dtype("datetime64[D]"):
            raise TypeError("sessions must be dtype datetime64[D]")
        n = len(self.sessions)
        if len(self.contract_ids) != n or len(self.period_ids) != n:
            raise ValueError("sessions/contract_ids/period_ids length mismatch")
        if n == 0:
            raise ValueError("ContractSeries cannot be empty")
        if any((not c) for c in self.contract_ids):
            raise ValueError("contract_ids contains empty values")
        if any((not p) for p in self.period_ids):
            raise ValueError("period_ids contains empty values")

    def switch_mask(self) -> np.ndarray:
        n = len(self.sessions)
        if n <= 1:
            return np.zeros(n, dtype=bool)
        prev = np.asarray(self.contract_ids[:-1], dtype=object)
        curr = np.asarray(self.contract_ids[1:], dtype=object)
        m = np.zeros(n, dtype=bool)
        m[1:] = curr != prev
        return m

    def switch_sessions(self) -> np.ndarray:
        return self.sessions[self.switch_mask()]

    def switch_view(self, max_rows: int = 12) -> list[tuple[np.datetime64, str, str]]:
        idx = np.flatnonzero(self.switch_mask())
        rows: list[tuple[np.datetime64, str, str]] = []
        for raw_i in idx[:max_rows]:
            i = int(raw_i)  # <- critical: removes Unknown index type
            session_i = cast(np.datetime64, self.sessions[i])
            rows.append((session_i, self.contract_ids[i - 1], self.contract_ids[i]))
        return rows


def build_contract_series(
    *,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    spec: "ContractSeriesSpec",
    canonical_id_fn: Callable[[Any], str] | None = None,
    short_id_fn: Callable[[Any], str] | None = None,
) -> "ContractSeries":
    """
    Build a time-indexed contract-identity series by realising `spec.rule` over a product's
    trading-session calendar.

    V1 semantics:
      - start/end must be trading sessions (exact, inclusive)
      - selection must succeed at every session in-range (hard fail)
      - no storage/caching here (pure builder)

    Assumptions about dependencies:
      - calendar_service.calendar_for_product(product_id) returns an object exposing either:
          * .sessions (np.ndarray / list-like of day labels), OR
          * .schedule.index (pandas DatetimeIndex)
      - engine.explain(product_id, session_day, rule) returns either:
          * an object with attrs: outcome, contract_id, period_id
          * OR a dict-like with keys: "outcome", "contract_id", "period_id"
    """
    product_id = spec.product_id
    rule = spec.rule

    # --- label extraction (Session 19) ---
    if canonical_id_fn is None:
        canonical_relative_id = getattr(rule, "canonical_relative_id", None)
        if callable(canonical_relative_id):
            canonical_relative_id = canonical_relative_id()
        if canonical_relative_id is None:
            canonical_relative_id = getattr(rule, "canonical_id", None)
        if canonical_relative_id is None:
            raise AttributeError(
                "Cannot derive canonical_relative_id from rule. "
                "Provide canonical_id_fn=... or expose rule.canonical_relative_id."
            )
        canonical_relative_id = cast(str, canonical_relative_id)
    else:
        canonical_relative_id = canonical_id_fn(rule)

    if short_id_fn is None:
        short_rel_id = getattr(rule, "short_rel_id", None)
        if callable(short_rel_id):
            short_rel_id = short_rel_id()
        if short_rel_id is None:
            short_rel_id = getattr(rule, "short_id", None)
        if short_rel_id is None:
            raise AttributeError(
                "Cannot derive short_rel_id from rule. "
                "Provide short_id_fn=... or expose rule.short_rel_id."
            )
        short_rel_id = cast(str, short_rel_id)
    else:
        short_rel_id = short_id_fn(rule)

    # --- calendar extraction ---
    cal = calendar_service.calendar_for_product(product_id)

    if hasattr(cal, "sessions"):
        cal_sessions = np.asarray(getattr(cal, "sessions"))
    elif hasattr(cal, "schedule") and hasattr(cal.schedule, "index"):
        # e.g. exchange_calendars schedule index is datetime64[s]/ns; normalise to days
        cal_sessions = np.asarray(cal.schedule.index.values)
    else:
        raise AttributeError(
            "Trading calendar object must expose .sessions or .schedule.index"
        )

    cal_days = ensure_1d_day_array(cal_sessions, name=f"{product_id} calendar sessions")

    # --- exact inclusive range slice ---
    start_d = coerce_np_day(spec.start_session)
    end_d = coerce_np_day(spec.end_session)

    i0 = searchsorted_exact(cal_days, start_d)
    i1 = searchsorted_exact(cal_days, end_d)
    if i0 is None:
        raise ValueError(f"start_session not in trading calendar: {start_d}")
    if i1 is None:
        raise ValueError(f"end_session not in trading calendar: {end_d}")
    if i1 < i0:
        raise ValueError("end_session must be >= start_session")

    sessions = cal_days[i0 : i1 + 1]

    # --- helper to read explain outputs robustly ---
    def _get_field(obj: Any, name: str) -> Any:
        if isinstance(obj, dict):
            return obj.get(name)
        return getattr(obj, name, None)

    contract_ids: list[str] = []
    period_ids: list[str] = []

    for d in sessions:
        day = cast(np.datetime64, d)  # keep Pyright happy
        out = engine.explain(product_id, day, rule)

        outcome = _get_field(out, "outcome")
        if outcome != "selected":
            # Be explicit: no partial series in V1
            raise RuntimeError(
                f"Selection failed in ContractSeries build: product={product_id} "
                f"rule={canonical_relative_id} session={day} outcome={outcome!r}"
            )

        cid = _get_field(out, "contract_id")
        pid = _get_field(out, "period_id")
        if not isinstance(cid, str) or not cid:
            raise RuntimeError(
                f"engine.explain returned invalid contract_id at {day}: {cid!r}"
            )
        if not isinstance(pid, str) or not pid:
            raise RuntimeError(
                f"engine.explain returned invalid period_id at {day}: {pid!r}"
            )

        contract_ids.append(cid)
        period_ids.append(pid)

    return ContractSeries(
        product_id=product_id,
        canonical_relative_id=canonical_relative_id,
        short_rel_id=short_rel_id,
        sessions=sessions,
        contract_ids=contract_ids,
        period_ids=period_ids,
    )
