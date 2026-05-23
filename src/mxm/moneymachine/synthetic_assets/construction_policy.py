"""
MXM V1 — Synthetic Asset Construction Policy

This module defines the declarative policy describing which synthetic assets
should be constructed for each futures product.

The policy is expressed as *families of synthetic assets*, where each family
corresponds to a specific contract-selection rule applied to a product's listed
contracts.

Conceptually:

    product
        → period-filter family
            → ranked contracts (n = 1..N)
                → synthetic assets (CONT, TS, etc.)

Each family is defined by:
- a PeriodFilter describing which contracts belong to the family
- a family_code used in asset identifiers
- maximum depths for continuous rolls (CONT) and time spreads (TS)

Examples of families include:
- full calendar-month ladders (e.g. M1..M70)
- quarterly ladders (e.g. HMUZ1..HMUZ20)
- seasonal ladders (e.g. HKNUZ1..HKNUZ8)
- repeating annual months (e.g. Mar1..Mar5)

The policy does not construct any assets itself. It only describes the intended
synthetic asset surface.

Compilation of this policy into concrete SyntheticAssetSpec objects is handled
by:

    mxm.v1.synthetic_assets.policy_compile

Design constraints
------------------
This module is strictly policy-as-data and must remain free of operational
dependencies. It must not:

- access reference data APIs
- read or write registries or files
- construct SelectorRule objects
- call spec builder functions

Its only responsibility is to author the synthetic asset construction policy
in a clear, deterministic, and declarative form.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from mxm.moneymachine.contracts.selectors import PeriodFilter
from mxm.moneymachine.synthetic_assets.weights_rules import (
    WeightsRuleSpec,
    canonical_weights_rule_id,
)
from mxm.refdata.models import PeriodType

# -----------------------------------------------------------------------------
# Constants
# -----------------------------------------------------------------------------

ALL_CALENDAR_MONTHS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12)
HMUZ_MONTHS: tuple[int, ...] = (3, 6, 9, 12)
HKNUZ_MONTHS: tuple[int, ...] = (3, 5, 7, 9, 12)
JUNDEC_MONTHS: tuple[int, ...] = (6, 12)

_MONTH_TO_ABBR: dict[int, str] = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}

# -----------------------------------------------------------------------------
# Helpers for policy authoring
# -----------------------------------------------------------------------------


def _validate_months(months: Iterable[int]) -> tuple[int, ...]:
    """
    Validate and normalise calendar month numbers.

    Returns:
        Stable tuple of unique month numbers in ascending order.
    """
    out = tuple(sorted({int(m) for m in months}))
    if not out:
        raise ValueError("months must be non-empty")
    bad = [m for m in out if m < 1 or m > 12]
    if bad:
        raise ValueError(f"Invalid calendar months {bad}; must be in 1..12")
    return out


def calendar_months_period_filter(*, months: Iterable[int]) -> PeriodFilter:
    """
    Build a PeriodFilter over CALENDAR_MONTHS for the given month subset.

    Examples:
        {1..12}      -> monthly family
        {3,6,9,12}   -> HMUZ quarterly family
        {6,12}       -> JunDec semiannual family
        {3}          -> March repeated annually
    """
    month_tuple = _validate_months(months)
    return PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset(month_tuple),
    )


def repeated_calendar_period_family(
    *,
    family_code: str,
    months: Iterable[int],
    cont_max_n: int,
    ts_max_n: int,
) -> PeriodFamilyPolicy:
    """
    Convenience helper to author one PeriodFamilyPolicy over CALENDAR_MONTHS.
    """
    return PeriodFamilyPolicy(
        family_code=family_code,
        period_filter=calendar_months_period_filter(months=months),
        cont_max_n=cont_max_n,
        ts_max_n=ts_max_n,
    )


def repeated_singleton_calendar_families(
    *,
    months: Iterable[int],
    cont_max_n: int,
    ts_max_n: int,
) -> tuple[PeriodFamilyPolicy, ...]:
    """
    Convenience helper to author repeated singleton calendar-month families.

    Example:
        months=(3,6,9,12), cont_max_n=5, ts_max_n=4
        -> Mar, Jun, Sep, Dec family policies
    """
    out: list[PeriodFamilyPolicy] = []
    for month in _validate_months(months):
        family_code = _MONTH_TO_ABBR[month]
        out.append(
            repeated_calendar_period_family(
                family_code=family_code,
                months=(month,),
                cont_max_n=cont_max_n,
                ts_max_n=ts_max_n,
            )
        )
    return tuple(out)


# -----------------------------------------------------------------------------
# Policy dataclasses
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PolicyDefaults:
    """
    Global defaults that genuinely remain global.

    For Session 26, the roll weights rule remains global across all families.
    """

    weights_rule_id: str


@dataclass(frozen=True, slots=True)
class PeriodFamilyPolicy:
    """
    One explicitly authored synthetic family for a product.

    Examples:
    - M       : PeriodFilter(MONTH, CALENDAR_MONTHS, {1..12})
    - HMUZ    : PeriodFilter(MONTH, CALENDAR_MONTHS, {3,6,9,12})
    - HKNUZ   : PeriodFilter(MONTH, CALENDAR_MONTHS, {3,5,7,9,12})
    - JunDec  : PeriodFilter(MONTH, CALENDAR_MONTHS, {6,12})
    - Mar     : PeriodFilter(MONTH, CALENDAR_MONTHS, {3})

    Semantics:
    - family_code is the token used in asset_ids for this family
    - period_filter defines the cycle family
    - cont_max_n builds CONT family_code1 .. family_codeN
    - ts_max_n builds TS family_code1/family_code2 .. family_codeN/family_code(N+1)

    Convention:
    - ts_max_n should usually equal cont_max_n - 1
    """

    family_code: str
    period_filter: PeriodFilter
    cont_max_n: int
    ts_max_n: int


@dataclass(frozen=True, slots=True)
class ProductPolicy:
    """
    All synthetic-family policy for one product.
    """

    product_id: str
    families: tuple[PeriodFamilyPolicy, ...]


@dataclass(frozen=True, slots=True)
class ProductSpreadPolicy:
    """
    One directional family-aware product spread policy.

    Example:
        A = cme_emini_snp500_futures, family_a_code = "HMUZ"
        B = cme_gbp_futures,         family_b_code = "HMUZ"

    This means:
        build PS over the quarterly HMUZ families on both products.
    """

    product_a_id: str
    family_a_code: str
    product_b_id: str
    family_b_code: str
    ps_max_n: int


@dataclass(frozen=True, slots=True)
class SyntheticAssetsPolicy:
    """
    Top-level policy container for Session 26+.

    Structure:
    - defaults: truly global settings
    - products: explicit per-product family authoring
    - product_spreads: explicit family-aware PS authoring
    """

    defaults: PolicyDefaults
    products: tuple[ProductPolicy, ...]
    product_spreads: tuple[ProductSpreadPolicy, ...]


# -----------------------------------------------------------------------------
# V1 / Session-26 authored policy
# -----------------------------------------------------------------------------

V1_LINEAR_ROLL_RULE = canonical_weights_rule_id(
    WeightsRuleSpec(
        kind="LINEAR_ROLL",
        roll_start_offset=3,
        roll_duration=1,
    )
)

V1_DEFAULTS = PolicyDefaults(
    weights_rule_id=V1_LINEAR_ROLL_RULE,
)


def v1_policy(*, product_ids: Iterable[str]) -> SyntheticAssetsPolicy:
    """
    Construct the Session-26 synthetic-asset policy for a given product universe.

    Notes:
    - This function authors the agreed product-family surface explicitly.
    - It does not inspect refdata.
    - It simply filters the authored policy to the requested universe.
    """
    universe = set(product_ids)

    authored_products: tuple[ProductPolicy, ...] = (
        ProductPolicy(
            product_id="comex_gold_futures",
            families=(
                repeated_calendar_period_family(
                    family_code="M",
                    months=ALL_CALENDAR_MONTHS,
                    cont_max_n=22,
                    ts_max_n=21,
                ),
                *repeated_singleton_calendar_families(
                    months=ALL_CALENDAR_MONTHS,
                    cont_max_n=2,
                    ts_max_n=1,
                ),
                repeated_calendar_period_family(
                    family_code="JunDec",
                    months=JUNDEC_MONTHS,
                    cont_max_n=5,
                    ts_max_n=4,
                ),
            ),
        ),
        ProductPolicy(
            product_id="nymex_natural_gas_futures",
            families=(
                repeated_calendar_period_family(
                    family_code="M",
                    months=ALL_CALENDAR_MONTHS,
                    cont_max_n=70,
                    ts_max_n=69,
                ),
                *repeated_singleton_calendar_families(
                    months=ALL_CALENDAR_MONTHS,
                    cont_max_n=5,
                    ts_max_n=4,
                ),
            ),
        ),
        ProductPolicy(
            product_id="cme_gbp_futures",
            families=(
                repeated_calendar_period_family(
                    family_code="M",
                    months=ALL_CALENDAR_MONTHS,
                    cont_max_n=3,
                    ts_max_n=2,
                ),
                repeated_calendar_period_family(
                    family_code="HMUZ",
                    months=HMUZ_MONTHS,
                    cont_max_n=20,
                    ts_max_n=19,
                ),
                *repeated_singleton_calendar_families(
                    months=HMUZ_MONTHS,
                    cont_max_n=5,
                    ts_max_n=4,
                ),
            ),
        ),
        ProductPolicy(
            product_id="cme_emini_snp500_futures",
            families=(
                repeated_calendar_period_family(
                    family_code="HMUZ",
                    months=HMUZ_MONTHS,
                    cont_max_n=20,
                    ts_max_n=19,
                ),
                *repeated_singleton_calendar_families(
                    months=HMUZ_MONTHS,
                    cont_max_n=5,
                    ts_max_n=4,
                ),
            ),
        ),
        ProductPolicy(
            product_id="cbot_corn_futures",
            families=(
                repeated_calendar_period_family(
                    family_code="HKNUZ",
                    months=HKNUZ_MONTHS,
                    cont_max_n=8,
                    ts_max_n=7,
                ),
                *repeated_singleton_calendar_families(
                    months=HKNUZ_MONTHS,
                    cont_max_n=2,
                    ts_max_n=1,
                ),
            ),
        ),
    )

    authored_spreads: tuple[ProductSpreadPolicy, ...] = (
        ProductSpreadPolicy(
            product_a_id="comex_gold_futures",
            family_a_code="M",
            product_b_id="nymex_natural_gas_futures",
            family_b_code="M",
            ps_max_n=3,
        ),
        ProductSpreadPolicy(
            product_a_id="cme_emini_snp500_futures",
            family_a_code="HMUZ",
            product_b_id="cme_gbp_futures",
            family_b_code="HMUZ",
            ps_max_n=3,
        ),
        # Corn product spreads left out until explicitly paired with a
        # compatible family on another product.
    )

    products = tuple(p for p in authored_products if p.product_id in universe)
    spreads = tuple(
        s
        for s in authored_spreads
        if s.product_a_id in universe and s.product_b_id in universe
    )

    return SyntheticAssetsPolicy(
        defaults=V1_DEFAULTS,
        products=products,
        product_spreads=spreads,
    )
