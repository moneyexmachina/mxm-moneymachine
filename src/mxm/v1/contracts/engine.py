"""
MXM V1 — Contract selection engine (Session 18).

This module implements deterministic, inspectable futures contract selection as a
pure function of:

    (product_id, as_of_timestamp, selector_rule) -> contract_id

Scope and intent
----------------
Session 18 resolves contract *identity* only. It does not assign human labels
(e.g. M1, Dec1), does not emit canonical relative identifiers, and does not
implement roll logic or synthetic assets. Those concerns are explicitly deferred
to Session 19+.

Locked semantics (Session 18)
-----------------------------
Two-layer selection model:

1) PeriodFilter
   Defines the admissible delivery periods.

   PeriodFilter(
       period_type: PeriodType,
       cycle_id: str | None,
       cycle_elements: frozenset[int] | None
   )

   Semantics:
   - cycle_elements is None  -> no subset filtering (cycle_id may be None)
   - otherwise               -> require cycle_id and keep only contracts whose
                                period_id maps to a cycle element contained in
                                cycle_elements (via refdata PeriodCycle membership)

2) SelectorRule
   Defines selection depth within the admissible set.

   SelectorRule(
       period_filter: PeriodFilter,
       n: int
   )

Engine semantics:

1) Resolve as_of_timestamp -> as_of_session via TradingCalendar.as_of_session()
2) Retrieve the authoritative chain from refdata for (product_id, period_type)
3) Apply PeriodFilter subset (optional, via PeriodCycle membership lookup)
4) Apply eligibility: last_trading_day(contract) > as_of_session
5) Rank eligible contracts by:
       (last_trading_day ASC, Period ASC, contract_id ASC)
   where Period ordering is Period.__lt__ (refdata-defined)
6) Select the n-th eligible contract (1-indexed)

Determinism
-----------
Ordering is deterministic. Tie-break is fully specified.

Failure semantics
-----------------
Selection failures are typed and never silent:
- NoEligibleContracts
- RelativeContractUnavailable

The engine also returns structured explanations via `explain(...)` suitable for
audit logs and CLI inspection.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.refdata.models.contracts.futures_contract import FuturesContract
from mxm.refdata.models.periods import Period
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.utils.date_utils import coerce_np_day, fmt_iso_day
from mxm.v1.utils.time_utils import UtcTimestampInput, fmt_run_ts

from .exceptions import NoEligibleContracts, RelativeContractUnavailable
from .relative_ids import canonical_relative_id, short_rel_id
from .selectors import PeriodFilter, SelectionExplanation, SelectorRule


@dataclass(frozen=True, slots=True)
class PeriodIndex:
    """
    Cheap lookup surface for Period ordering and validation.

    We rely on Period.__lt__ (refdata-defined ordering).
    """

    by_id: dict[str, Period]

    @staticmethod
    def from_periods(periods: Iterable[Period]) -> PeriodIndex:
        return PeriodIndex(by_id={p.period_id: p for p in periods})

    def get(self, period_id: str) -> Period:
        try:
            return self.by_id[period_id]
        except KeyError as e:
            raise KeyError(
                f"Unknown period_id {period_id!r} (missing from RefDataAPI.get_periods())"
            ) from e


@dataclass(frozen=True, slots=True)
class ContractSelectorEngine:
    """
    Deterministic contract-selection engine for MXM V1 (Session 18).
    """

    refdata: RefDataAPI
    calendars: TradingCalendarService
    period_index: PeriodIndex

    @staticmethod
    def build(
        refdata: RefDataAPI, calendars: TradingCalendarService
    ) -> ContractSelectorEngine:
        periods = refdata.get_periods()
        return ContractSelectorEngine(
            refdata=refdata,
            calendars=calendars,
            period_index=PeriodIndex.from_periods(periods),
        )

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def select(
        self,
        product_id: str,
        as_of_ts: UtcTimestampInput,
        rule: SelectorRule,
    ) -> str:
        """
        Resolve and return the selected contract_id.

        Raises:
            NoEligibleContracts
            RelativeContractUnavailable
        """
        exp = self.explain(product_id=product_id, as_of_ts=as_of_ts, rule=rule)
        if exp.outcome != "selected" or exp.selected_contract_id is None:
            if exp.failure_type == "NoEligibleContracts":
                raise NoEligibleContracts(
                    product_id=product_id, as_of_session=exp.as_of_session
                )
            if exp.failure_type == "RelativeContractUnavailable":
                raise RelativeContractUnavailable(
                    product_id=product_id,
                    as_of_session=exp.as_of_session,
                    n=rule.n,
                    available=int(exp.details.get("eligible_count", 0)),
                )
            raise RuntimeError(exp.message or "Contract selection failed unexpectedly.")
        return exp.selected_contract_id

    def explain(
        self,
        product_id: str,
        as_of_ts: UtcTimestampInput,
        rule: SelectorRule,
    ) -> SelectionExplanation:
        """
        Perform selection, returning a structured explanation artifact.

        Never raises on selection failure; instead returns outcome="failed" with
        typed failure_type and a message. `select(...)` converts failures into
        raised exceptions.
        """
        pf = rule.period_filter
        canon = canonical_relative_id(rule)
        short = short_rel_id(rule)
        as_of_session_np = self.calendars.calendar_for_product(
            product_id
        ).as_of_session(as_of_ts)
        as_of_session = fmt_iso_day(as_of_session_np)

        chain: list[FuturesContract] = self.refdata.get_contracts_for_product(
            product_id, period_type=pf.period_type
        )
        admissible = self._apply_period_filter(chain, pf)
        eligible = self._eligible(admissible, as_of_session_np)

        ordered = sorted(
            eligible,
            key=lambda c: (
                coerce_np_day(c.last_trading_day),
                self.period_index.get(c.period_id),
                c.contract_id,
            ),
        )

        if not ordered:
            return self._fail(
                product_id=product_id,
                as_of_ts=as_of_ts,
                as_of_session=as_of_session,
                rule=rule,
                canonical_relative_id=canon,
                short_rel_id=short,
                failure_type="NoEligibleContracts",
                message="No eligible contracts after applying PeriodFilter and eligibility predicate.",
                details={
                    "period_type": pf.period_type.name,
                    "cycle_id": pf.cycle_id,
                    "cycle_elements": (
                        None if pf.cycle_elements is None else sorted(pf.cycle_elements)
                    ),
                    "chain_count": len(chain),
                    "admissible_count": len(admissible),
                    "eligible_count": 0,
                },
            )

        if rule.n > len(ordered):
            return self._fail(
                product_id=product_id,
                as_of_ts=as_of_ts,
                as_of_session=as_of_session,
                rule=rule,
                canonical_relative_id=canon,
                short_rel_id=short,
                failure_type="RelativeContractUnavailable",
                message=f"Requested n={rule.n} but only {len(ordered)} eligible contracts are available.",
                details={
                    "period_type": pf.period_type.name,
                    "cycle_id": pf.cycle_id,
                    "cycle_elements": (
                        None if pf.cycle_elements is None else sorted(pf.cycle_elements)
                    ),
                    "chain_count": len(chain),
                    "admissible_count": len(admissible),
                    "eligible_count": len(ordered),
                    "eligible_contract_ids_head": [
                        c.contract_id for c in ordered[: min(10, len(ordered))]
                    ],
                },
            )

        selected = ordered[rule.n - 1]
        selected_ltd = fmt_iso_day(coerce_np_day(selected.last_trading_day))

        return SelectionExplanation(
            product_id=product_id,
            as_of_utc=fmt_run_ts(as_of_ts),
            as_of_session=as_of_session,
            rule=rule,
            selected_contract_id=selected.contract_id,
            canonical_relative_id=canon,
            short_rel_id=short,
            outcome="selected",
            failure_type=None,
            message=None,
            details={
                "period_type": pf.period_type.name,
                "cycle_id": pf.cycle_id,
                "cycle_elements": (
                    None if pf.cycle_elements is None else sorted(pf.cycle_elements)
                ),
                "n": rule.n,
                "chain_count": len(chain),
                "admissible_count": len(admissible),
                "eligible_count": len(ordered),
                "selected_last_trading_day": selected_ltd,
            },
        )

    # ------------------------------------------------------------------ #
    # Internal plumbing
    # ------------------------------------------------------------------ #

    def _apply_period_filter(
        self,
        chain: Sequence[FuturesContract],
        pf: PeriodFilter,
    ) -> list[FuturesContract]:
        """
        Apply PeriodFilter in period space.

        If cycle_elements is provided, we lookup period_id -> cycle element via
        refdata PeriodCycle membership artifacts (no parsing, no contract-field hacks).
        """
        if pf.cycle_elements is None:
            return list(chain)

        if pf.cycle_id is None:
            raise ValueError(
                "PeriodFilter.cycle_id must be set when cycle_elements is provided"
            )

        allowed = set(pf.cycle_elements)

        period_ids = [c.period_id for c in chain]
        elem_by_pid = self.refdata.get_cycle_elements(period_ids, cycle_id=pf.cycle_id)

        out: list[FuturesContract] = []
        for c in chain:
            elem = elem_by_pid.get(c.period_id)
            if elem is not None and elem in allowed:
                out.append(c)
        return out

    def _eligible(
        self,
        contracts: Sequence[FuturesContract],
        as_of_session: np.datetime64,
    ) -> list[FuturesContract]:
        """
        Normative Session 18 eligibility: last_trading_day(contract) > as_of_session.
        """
        out: list[FuturesContract] = []
        for c in contracts:
            ltd = coerce_np_day(c.last_trading_day)
            if ltd > as_of_session:
                out.append(c)
        return out

    def _fail(
        self,
        *,
        product_id: str,
        as_of_ts: UtcTimestampInput,
        as_of_session: str,
        rule: SelectorRule,
        canonical_relative_id: str,
        short_rel_id: str,
        failure_type: str,
        message: str,
        details: Mapping[str, object],
    ) -> SelectionExplanation:
        return SelectionExplanation(
            product_id=product_id,
            as_of_utc=fmt_run_ts(as_of_ts),
            as_of_session=as_of_session,
            rule=rule,
            selected_contract_id=None,
            canonical_relative_id=canonical_relative_id,
            short_rel_id=short_rel_id,
            outcome="failed",
            failure_type=failure_type,  # type: ignore[arg-type]
            message=message,
            details=dict(details),
        )
