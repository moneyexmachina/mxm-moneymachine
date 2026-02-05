"""
MXM V1 — Contract selection engine.

This module defines the contract-layer engine responsible for resolving
**selector rules** into concrete futures contracts as-of a trading date.

The engine provides deterministic, calendar-aware selection semantics for
questions of the form:

    (product_id, as_of, rule) -> instrument_id

Scope
-----
- Selection semantics only: eligibility filtering and deterministic ranking.
- No pricing, no roll rules, no interpolation, no holdings, no P&L.
- No I/O, no persistence, no internal caching.

Authority
---------
Contract selection is a pure function of:
- reference data (contract metadata, including last trading day)
- trading calendars (observed or projected)
- explicit input arguments

This module is therefore a semantic authority layer that sits:
- above refdata and calendars
- below synthetic assets / rolls / holdings

Design note: rule vocabulary
----------------------------
The engine operates on explicit rule objects defined in ``selectors.py``.
Rules are serialisable and hashable so that selections can be named, tested,
and audited.

In MXM V1 we will explicitly distinguish selection substrates, to avoid
overloading ambiguous names such as "M1":

- listing/chain rank within a period_type (e.g. "front monthly")
- period selectors (delivery-period shifts; provided by mxm-refdata)
- selection cycles (intent-driven slot lattices; later)

The engine itself remains agnostic: it evaluates only the rule it is given.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Sequence

from .exceptions import (
    NoEligibleContracts,
    NonTradingDayInput,
    RelativeContractUnavailable,
    UnknownSelectorRule,
)
from .selectors import SelectionExplanation, SelectorRule

# NOTE: These imports are placeholders. Replace with actual types from MXM.
# - InstrumentId: canonical contract identifier type
# - PeriodType: e.g. "monthly", "quarterly", "annual", "summer", "winter", ...
# - TradingCalendar: calendar API used to validate trading days / comparisons
#
# from mxm.types import InstrumentId
# from mxm.refdata.types import PeriodType
# from mxm.v1.calendars import TradingCalendar


@dataclass(frozen=True, slots=True)
class ContractSelectorEngine:
    """
    Deterministic contract-selection engine for MXM V1.

    Parameters
    ----------
    refdata:
        Reference-data service (or façade) providing access to contracts and
        their metadata (e.g. last trading day, delivery period, period_type).

        The engine treats refdata as read-only.

    calendars:
        Calendar service providing TradingCalendar instances per product_id.

        The engine relies on calendars for:
        - validating as_of is a trading day (strict by default)
        - trading-day arithmetic / comparisons, if required by rules

    strict_trading_day:
        If True, ``as_of`` must be a trading day and selection raises on
        non-trading-day input. If False, the engine may normalise input
        (normalisation policy should still be explicit and test-covered).
    """

    refdata: Any
    calendars: Any
    strict_trading_day: bool = True

    # --------------------------------------------------------------------- #
    # Public API
    # --------------------------------------------------------------------- #

    def select(
        self,
        product_id: str,
        as_of: date,
        rule: SelectorRule,
    ):
        """
        Resolve a selector rule to a concrete contract identifier.

        This is the primary entry point used by downstream layers.

        Raises
        ------
        NonTradingDayInput
            If strict_trading_day is True and as_of is not a trading day.
        NoEligibleContracts
            If no eligible contracts exist for the rule on as_of.
        RelativeContractUnavailable
            If the rule requests a contract that does not exist (e.g. depth too
            large).
        UnknownSelectorRule
            If rule.kind is not supported by this engine.
        """
        self._validate_as_of(product_id, as_of)

        kind = getattr(rule, "kind", None)
        if kind is None:
            raise UnknownSelectorRule(f"Rule has no 'kind': {rule!r}")

        # Dispatch by rule.kind. Implementations live in private methods.
        if kind == "listing_rank":
            return self._select_listing_rank(product_id, as_of, rule)

        # Future rule kinds (placeholders):
        # if kind == "period":
        #     return self._select_period(product_id, as_of, rule)
        # if kind == "cycle_rank":
        #     return self._select_cycle_rank(product_id, as_of, rule)
        # if kind == "month":
        #     return self._select_fixed_month(product_id, as_of, rule)

        raise UnknownSelectorRule(f"Unsupported selector kind: {kind!r}")

    def explain(
        self,
        product_id: str,
        as_of: date,
        rule: SelectorRule,
    ) -> SelectionExplanation:
        """
        Return a structured explanation of how a selection was obtained.

        This should be cheap enough for interactive inspection but is not
        intended for tight loops in holdings materialisation.

        The explanation is designed to be:
        - printable in CLI reports
        - serialisable for audit logs
        - stable under tests

        It must include at minimum:
        - the resolved contract_id
        - eligibility universe size and the eligible ordered list (or summary)
        - the rule as provided
        - key dates (as_of, selected last_trading_day)
        - whether projected calendars were used (exposed via calendars service)
        """
        self._validate_as_of(product_id, as_of)

        contract_id = self.select(product_id, as_of, rule)
        # Minimal explanation for now; expand once selection methods exist.
        return SelectionExplanation(
            product_id=product_id,
            as_of=as_of,
            rule=rule,
            contract_id=contract_id,
            details={},
        )

    def list_supported_kinds(self) -> tuple[str, ...]:
        """
        Return the selector kinds supported by this engine instance.

        This is intended for CLI help / validation and test assertions.
        """
        return ("listing_rank",)

    # --------------------------------------------------------------------- #
    # Validation / plumbing
    # --------------------------------------------------------------------- #

    def _validate_as_of(self, product_id: str, as_of: date) -> None:
        if not self.strict_trading_day:
            return
        cal = self._calendar_for(product_id)
        if not cal.is_trading_day(as_of):
            raise NonTradingDayInput(product_id=product_id, as_of=as_of)

    def _calendar_for(self, product_id: str):
        """
        Return the TradingCalendar for a product_id.

        The calendars service is responsible for observed vs projected sourcing.
        """
        return self.calendars.calendar_for_product(product_id)

    # --------------------------------------------------------------------- #
    # Rule implementations (private)
    # --------------------------------------------------------------------- #

    def _select_listing_rank(self, product_id: str, as_of: date, rule: Any):
        """
        Select the nth eligible listed contract for a given period_type.

        Normative semantics (MXM V1):
        - eligible iff last_trading_day(contract) > as_of
        - ordering: ascending last_trading_day
        - n is 1-indexed
        - ranking is defined within a single period_type chain
        """
        # Placeholder. Implement after selectors.py is in place and refdata API
        # surfaces are confirmed.
        raise NotImplementedError("listing_rank selection not implemented yet")
