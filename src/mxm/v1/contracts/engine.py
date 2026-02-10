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
       cycle_elements: frozenset[int] | None
   )

   Semantics:
   - cycle_elements is None  -> no subset filtering
   - otherwise               -> only keep periods whose cycle index is in the set
                                (e.g. {12} for December in a MONTH cycle)

2) SelectorRule
   Defines selection depth within the admissible set.

   SelectorRule(
       period_filter: PeriodFilter,
       n: int
   )

Engine semantics:

1) Resolve as_of_timestamp -> as_of_session via TradingCalendar.as_of_session()
2) Retrieve the authoritative listed chain from refdata for (product_id, period_type)
3) Apply PeriodFilter subset (optional)
4) Apply eligibility: last_trading_day(contract) > as_of_session
5) Rank eligible contracts by last_trading_day ascending (deterministic tie-break)
6) Select the n-th eligible contract (1-indexed)

Determinism
-----------
Ordering is deterministic. If two eligible contracts share the same last trading
day, the engine breaks ties by contract_id (ascending string order).

Non-goals (explicit)
--------------------
This module does NOT:
- assign labels such as M1 / Dec1 / Q+1
- define or resolve relative_contract_id or short_id
- infer semantics from exchange naming conventions
- implement roll windows, synthetic assets, holdings, persistence, or caching

Failure semantics
-----------------
Selection failures are typed and never silent:
- NoEligibleContracts
- RelativeContractUnavailable

The engine also returns structured explanations via `explain(...)` suitable for
audit logs and CLI inspection.

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Sequence

import numpy as np
from mxm_refdata.api.ref_data_api import RefDataAPI
from mxm_refdata.models.periods import (
    PeriodType,  # adjust import path to your refdata package
)
from mxm_refdata.models.periods import (
    Period,
)

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.utils.date_utils import coerce_np_day, fmt_iso_day
from mxm.v1.utils.time_utils import UtcTimestampInput, fmt_run_ts

from .exceptions import NoEligibleContracts, RelativeContractUnavailable
from .selectors import PeriodFilter, SelectionExplanation, SelectorRule


@dataclass(frozen=True, slots=True)
class PeriodIndex:
    by_id: Dict[str, Period]

    @staticmethod
    def from_periods(periods: Iterable[Period]) -> "PeriodIndex":
        by_id = {p.period_id: p for p in periods}
        return PeriodIndex(by_id=by_id)

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

    Required services
    -----------------
    refdata must provide:
        get_contracts_for_product(product_id: str, period_type: PeriodType) -> Sequence[Contract]

    calendars must provide:
        calendar_for_product(product_id: str) -> TradingCalendar

    TradingCalendar must provide:
        as_of_session(as_of_ts: UtcTimestampInput) -> day-like (coercible to np.datetime64[D])

    Contract must expose:
        contract_id
        last_trading_day (date-like / timestamp-like; coercible by coerce_np_day)

    For monthly cycle subset filtering (cycle_elements != None), Contract must also expose:
        delivery_month (int 1..12)

    Notes
    -----
    - Selection operates in session-label (day) space.
    - No pricing, no roll logic, no persistence.
    """

    refdata: RefDataAPI
    calendars: TradingCalendarService
    period_index: PeriodIndex

    @staticmethod
    def build(
        refdata: RefDataAPI, calendars: TradingCalendarService
    ) -> "ContractSelectorEngine":
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
        Resolve and return the selected contract.

        Raises:
            NoEligibleContracts
            RelativeContractUnavailable
        """
        exp = self.explain(product_id=product_id, as_of_ts=as_of_ts, rule=rule)
        if exp.outcome != "selected" or exp.selected_contract_id is None:
            # Typed failure surface: always one of the defined exceptions.
            if exp.failure_type == "NoEligibleContracts":
                raise NoEligibleContracts(
                    product_id=product_id,
                    as_of_session=exp.as_of_session,
                )
            if exp.failure_type == "RelativeContractUnavailable":
                raise RelativeContractUnavailable(
                    product_id=product_id,
                    as_of_session=exp.as_of_session,
                    n=rule.n,
                    available=int(exp.details.get("eligible_count", 0)),
                )
            # Defensive: should not occur.
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
        typed failure_type and a message. The companion `select(...)` method
        converts those into raised exceptions.
        """
        pf = rule.period_filter

        as_of_session_np = self.calendars.calendar_for_product(
            product_id
        ).as_of_session(as_of_ts)
        as_of_session = fmt_iso_day(as_of_session_np)

        chain = self.refdata.get_contracts_for_product(product_id, pf.period_type)
        admissible = self._apply_period_filter(chain, pf)
        eligible = self._eligible(admissible, as_of_session_np)

        # Deterministic ordering:
        #   1) last_trading_day ascending
        #   2) contract_id ascending (tie-break)
        ordered = sorted(
            eligible,
            key=lambda c: (
                coerce_np_day(c.last_trading_day),
                self.period_index.get(c.period_id),
                c.contract_id,
            ),
        )

        ordered = sorted(
            eligible,
            key=lambda c: (coerce_np_day(c.last_trading_day), str(c.instrument_id)),
        )

        if not ordered:
            return self._fail(
                product_id=product_id,
                as_of_ts=as_of_ts,
                as_of_session=as_of_session,
                rule=rule,
                failure_type="NoEligibleContracts",
                message="No eligible contracts after applying PeriodFilter and eligibility predicate.",
                details={
                    "period_type": _period_type_to_str(pf.period_type),
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
                failure_type="RelativeContractUnavailable",
                message=(
                    f"Requested n={rule.n} but only {len(ordered)} eligible contracts are available."
                ),
                details={
                    "period_type": _period_type_to_str(pf.period_type),
                    "cycle_elements": (
                        None if pf.cycle_elements is None else sorted(pf.cycle_elements)
                    ),
                    "chain_count": len(chain),
                    "admissible_count": len(admissible),
                    "eligible_count": len(ordered),
                    "eligible_instrument_ids_head": [
                        str(_contract_field(c, "instrument_id"))
                        for c in ordered[: min(10, len(ordered))]
                    ],
                },
            )

        selected = ordered[rule.n - 1]
        selected_id = str(_contract_field(selected, "instrument_id"))
        selected_ltd = fmt_iso_day(
            coerce_np_day(_contract_field(selected, "last_trading_day"))
        )

        return SelectionExplanation(
            product_id=product_id,
            as_of_utc=self._fmt_as_of_utc(as_of_ts),
            as_of_session=as_of_session,
            rule=rule,
            selected_instrument_id=selected_id,
            outcome="selected",
            failure_type=None,
            message=None,
            details={
                "period_type": _period_type_to_str(pf.period_type),
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
        self, chain: Sequence[Any], pf: PeriodFilter
    ) -> Sequence[Any]:
        """
        Apply PeriodFilter in "period space".

        In practice, refdata hands us contracts. For MONTH-type filters we implement
        the cycle_elements subset by filtering on contract.delivery_month.

        For other PeriodTypes with subset semantics (e.g. quarters), this method is
        the single controlled expansion point, but Session 18 only *requires* the
        generic semantics and does not mandate multi-period element subsets.
        """
        if pf.cycle_elements is None:
            return list(chain)

        # Session 18: cycle subset is defined in "cycle space" but we may need to
        # implement it using contract fields.
        if _is_monthly(pf.period_type):
            allowed = set(pf.cycle_elements)
            out: list[Any] = []
            for c in chain:
                dm = int(_contract_field(c, "delivery_month"))
                if dm in allowed:
                    out.append(c)
            return out

        # If we reach here, the product is using a non-monthly period_type with
        # cycle_elements specified. This is a configuration/model error.
        raise ValueError(
            "cycle_elements subset filtering is only implemented for monthly PeriodType in Session 18"
        )

    def _eligible(
        self, contracts: Sequence[Any], as_of_session: np.datetime64
    ) -> Sequence[Any]:
        """
        Normative Session 18 eligibility: last_trading_day(contract) > as_of_session.
        """
        out: list[Any] = []
        for c in contracts:
            ltd = coerce_np_day(_contract_field(c, "last_trading_day"))
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
        failure_type: str,
        message: str,
        details: Mapping[str, Any],
    ) -> SelectionExplanation:
        return SelectionExplanation(
            product_id=product_id,
            as_of_utc=fmt_run_ts(as_of_ts),
            as_of_session=as_of_session,
            rule=rule,
            selected_instrument_id=None,
            outcome="failed",
            failure_type=failure_type,
            message=message,
            details=dict(details),
        )
