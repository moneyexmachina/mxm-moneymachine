from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Mapping

from mxm_refdata.models.periods import PeriodType


@dataclass(frozen=True, slots=True)
class PeriodFilter:
    """
    PeriodFilter defines the admissible delivery periods for selection.

    Locked model (Session 18, cycle-aware):
        PeriodFilter(
            period_type: PeriodType,
            cycle_id: str | None,
            cycle_elements: frozenset[int] | None
        )

    Semantics:
    - cycle_elements is None -> no subset filtering (cycle_id may be None)
    - otherwise             -> cycle_id must be set and contracts are admissible iff
                              cycle_element(period_id, cycle_id) ∈ cycle_elements
                              (as defined by refdata PeriodCycle membership)
    """

    period_type: PeriodType
    cycle_id: str | None = None
    cycle_elements: frozenset[int] | None = None

    def __post_init__(self) -> None:
        if self.cycle_elements is None:
            return

        if len(self.cycle_elements) == 0:
            raise ValueError(
                "PeriodFilter.cycle_elements must be non-empty if provided"
            )

        if self.cycle_id is None or not self.cycle_id:
            raise ValueError(
                "PeriodFilter.cycle_id must be set when cycle_elements is provided"
            )

        for x in self.cycle_elements:
            if x < 1:
                raise ValueError(
                    f"PeriodFilter.cycle_elements must contain positive integers; got {x}"
                )

        # Optional safety: enforce calendar months range when period_type is MONTH.
        if self.period_type == PeriodType.MONTH:
            for x in self.cycle_elements:
                if x > 12:
                    raise ValueError(
                        f"Monthly cycle_elements must be in 1..12; got {x}"
                    )

    # ------------------------------------------------------------------
    # Serialisation (config / audit safe)
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"period_type": self.period_type.name}
        if self.cycle_id is not None:
            d["cycle_id"] = self.cycle_id
        if self.cycle_elements is not None:
            d["cycle_elements"] = sorted(self.cycle_elements)
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "PeriodFilter":
        period_type = PeriodType[d["period_type"]]

        cycle_id_raw = d.get("cycle_id", None)
        cycle_id = None if cycle_id_raw is None else str(cycle_id_raw)

        elems_raw = d.get("cycle_elements", None)
        if elems_raw is None:
            cycle_elements: frozenset[int] | None = None
        else:
            cycle_elements = frozenset(int(x) for x in elems_raw)

        return PeriodFilter(
            period_type=period_type,
            cycle_id=cycle_id,
            cycle_elements=cycle_elements,
        )


@dataclass(frozen=True, slots=True)
class SelectorRule:
    """
    SelectorRule defines selection depth within admissible periods.

    Locked model:
        SelectorRule(
            period_filter: PeriodFilter,
            n: int
        )

    Engine-locked semantics:
    - eligibility: last_trading_day > as_of_session
    - ordering: last_trading_day asc (tie-break by Period then contract_id)
    - selection: n-th eligible (1-indexed)
    """

    period_filter: PeriodFilter
    n: int = 1

    def __post_init__(self) -> None:
        if self.n < 1:
            raise ValueError("SelectorRule.n must be >= 1 (1-indexed)")

    def to_dict(self) -> Dict[str, Any]:
        return {"period_filter": self.period_filter.to_dict(), "n": self.n}

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "SelectorRule":
        pf = PeriodFilter.from_dict(d["period_filter"])
        n = int(d.get("n", 1))
        return SelectorRule(period_filter=pf, n=n)

    @staticmethod
    def from_canonical_relative_id(s: str) -> "SelectorRule":
        from mxm.v1.contracts.relative_ids import parse_canonical_relative_id

        return parse_canonical_relative_id(s)


@dataclass(frozen=True, slots=True)
class SelectionExplanation:
    """
    Inspection artifact for deterministic contract selection.

    Requirements:
    - Serialisable
    - CLI-printable
    - details must contain only JSON-like values
    """

    product_id: str
    as_of_utc: str
    as_of_session: str
    rule: SelectorRule
    canonical_relative_id: str
    short_rel_id: str
    selected_contract_id: str | None
    outcome: Literal["selected", "failed"]
    failure_type: Literal["NoEligibleContracts", "RelativeContractUnavailable"] | None
    message: str | None
    details: Mapping[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "product_id": self.product_id,
            "as_of_utc": self.as_of_utc,
            "as_of_session": self.as_of_session,
            "rule": self.rule.to_dict(),
            "canonical_relative_id": self.canonical_relative_id,
            "short_rel_id": self.short_rel_id,
            "selected_contract_id": self.selected_contract_id,
            "outcome": self.outcome,
            "failure_type": self.failure_type,
            "message": self.message,
            "details": dict(self.details),
        }
