from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Mapping

from mxm_refdata.models.periods import PeriodType

# ---------------------------------------------------------------------------
# PeriodFilter (Session 18 locked)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PeriodFilter:
    """
    PeriodFilter defines the admissible delivery periods for selection.

    Locked model (Session 18):
        PeriodFilter(
            period_type: PeriodType,
            cycle_elements: frozenset[int] | None
        )

    Semantics:
    - cycle_elements is None -> no subset filtering.
    - otherwise             -> keep only periods whose cycle index is in the set
                              (e.g. {12} for December in a monthly cycle).

    Notes
    -----
    - This is a *period intent* object, not a contract naming object.
    - No labels, no canonical IDs, no "named" fields in Session 18.
    """

    period_type: PeriodType
    cycle_elements: frozenset[int] | None = None

    def __post_init__(self) -> None:
        if self.cycle_elements is None:
            return

        if len(self.cycle_elements) == 0:
            raise ValueError(
                "PeriodFilter.cycle_elements must be non-empty if provided"
            )

        for x in self.cycle_elements:
            if x < 1:
                raise ValueError(
                    f"PeriodFilter.cycle_elements must contain positive integers; got {x}"
                )

        # Session 18: we *define* month element semantics; enforce 1..12 only if monthly.
        if self.period_type == PeriodType.MONTH:
            for x in self.cycle_elements:
                if x > 12:
                    raise ValueError(
                        f"Monthly PeriodFilter.cycle_elements must be in 1..12; got {x}"
                    )

    # ------------------------------------------------------------------
    # Serialisation (config / audit safe)
    # ------------------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        """
        Canonical dict surface suitable for YAML/JSON.

        PeriodType is serialised via its Enum name to keep it stable and explicit.
        """
        d: Dict[str, Any] = {"period_type": self.period_type.name}
        if self.cycle_elements is not None:
            d["cycle_elements"] = sorted(self.cycle_elements)
        return d

    @staticmethod
    def from_dict(d: Mapping[str, Any]) -> "PeriodFilter":
        """
        Decode from YAML/JSON-like dict.

        This assumes the input comes from MXM-controlled config surfaces.
        We still validate basic shape to avoid silent corruption.
        """
        pt_name = d["period_type"]
        period_type = PeriodType[pt_name]

        cycle = d.get("cycle_elements", None)
        if cycle is None:
            cycle_elements: frozenset[int] | None = None
        else:
            # Accept list[int] and normalise to frozenset[int]
            cycle_elements = frozenset(int(x) for x in cycle)

        return PeriodFilter(period_type=period_type, cycle_elements=cycle_elements)


# ---------------------------------------------------------------------------
# SelectorRule (Session 18 locked)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelectorRule:
    """
    SelectorRule defines ranking/selection within admissible periods.

    Locked model (Session 18):
        SelectorRule(
            period_filter: PeriodFilter,
            n: int
        )

    Normative semantics:
    - Eligible contracts are those in admissible periods with last_trading_day > as_of_session.
    - Ranking is by last_trading_day ascending (engine-locked).
    - Selection returns the n-th eligible (1-indexed).
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


# ---------------------------------------------------------------------------
# SelectionExplanation (inspection surface)
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class SelectionExplanation:
    """
    Inspection artifact for deterministic contract selection.

    Requirements:
    - Serialisable
    - CLI-printable
    - Contains only basic values (no pandas/numpy objects in details)
    """

    product_id: str
    as_of_utc: str  # ISO-8601 string, e.g. "2026-02-06T12:34:56Z"
    as_of_session: str  # session label, ISO date string "YYYY-MM-DD"
    rule: SelectorRule

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
            "selected_contract_id": self.selected_contract_id,
            "outcome": self.outcome,
            "failure_type": self.failure_type,
            "message": self.message,
            "details": dict(self.details),
        }
