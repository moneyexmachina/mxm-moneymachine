# src/mxm/v1/synthetic_assets/construction_policy.py
from __future__ import annotations

"""
MXM V1 — Synthetic Asset construction policy (Session 24b).

This module defines the *declarative policy* describing which SyntheticAssetSpec
definitions should be constructed and written into the synthetic-asset spec
registry.

Scope
-----
This is a policy-as-data module only.

It MUST NOT:
- call RefDataAPI
- touch the filesystem / registries
- construct SelectorRule objects
- call spec_builder functions

Those responsibilities belong to the compiler layer:
    mxm.v1.synthetic_assets.policy_compile

Design intent
-------------
We keep the builder layer fully expressive, but adopt a deliberately narrow V1
policy surface to avoid configuration sprawl.

In V1, we construct:

1) Continuous rolls (CONT)
   - Listed chain rolls: L1..L12 for every product (rolling pair Ln/L(n+1))

2) Time spreads (TS)
   - Adjacent ladder spreads derived from listed chain rolls:
       TS(n) := (Ln/L(n+1)) vs (L(n+1)/L(n+2))
     therefore TS is defined for n=1..11 when CONT is defined for n=1..12.

3) Fixed-month continuous rolls (CONT, calendar-month-filtered)
   - For each product, build "fixed calendar month" rolls for selected delivery
     months, for seasonality and liquidity studies.
   - Month sets are derived from product metadata (valid_period_rule) with
     per-product overrides.
   - Special case: GBP has quarterly listings far out; therefore fixed-month
     rolls are quarterlies only (Mar, Jun, Sep, Dec).

4) Product spreads (PS)
   - A small global directional list of product pairs, primarily for unit/size
     transformation testing.
   - For each pair, build PS for levels n=1..3 (rolling pair Ln/L(n+1) on both legs).
   - Directional semantics: PS(A,B) is distinct from PS(B,A).

Policy knobs
------------
This module defines:
- default weights_rule_id
- maximum depth for listed-chain rolls and derived time spreads
- per-product fixed-month behaviour
- global product spread pair list

The compiler is responsible for:
- taking authoritative currency/unit/contract_size from FuturesProduct
- mapping month codes to calendar months and cycle_elements
- emitting SyntheticAssetSpec objects deterministically
"""

from dataclasses import dataclass
from typing import Iterable, Literal

from mxm.v1.synthetic_assets.weights_rules import (
    WeightsRuleSpec,
    canonical_weights_rule_id,
)

# -----------------------------------------------------------------------------
# Core policy dataclasses (pure data; no refdata / no builder calls)
# -----------------------------------------------------------------------------

FixedMonthMode = Literal["none", "valid_rule", "quarterlies"]


@dataclass(frozen=True, slots=True)
class PolicyDefaults:
    """
    Global defaults and depth knobs.

    Semantics:
    - cont_max_n: build CONT for n=1..cont_max_n (each uses Ln/L(n+1))
    - ts_max_n: build TS for n=1..ts_max_n, where TS(n) uses levels n..(n+2)
      therefore ts_max_n should typically be cont_max_n - 1.
    - ps_max_n: build PS for n=1..ps_max_n for each product spread pair.
    """

    weights_rule_id: str = canonical_weights_rule_id(
        WeightsRuleSpec(
            kind="LINEAR_ROLL",
            roll_start_offset=3,
            roll_duration=1,
        )
    )
    cont_max_n: int = 12
    ts_max_n: int = 11
    ps_max_n: int = 3


@dataclass(frozen=True, slots=True)
class ProductOverrides:
    """
    Per-product policy overrides.

    fixed_month_mode:
      - "none":         do not build fixed-month CONT assets
      - "valid_rule":   build fixed-month CONT for months derived from product.valid_period_rule
      - "quarterlies":  build fixed-month CONT for Mar/Jun/Sep/Dec regardless of valid_period_rule

    fixed_month_months:
      - optional explicit calendar month numbers (1..12) if you want to pin a
        custom subset. If provided, it takes precedence over fixed_month_mode.
    """

    fixed_month_mode: FixedMonthMode = "valid_rule"
    fixed_month_months: tuple[int, ...] | None = None


@dataclass(frozen=True, slots=True)
class ProductSpreadPair:
    """
    One directional product spread pair PS(A,B).

    Semantics:
    - product_a_id is the first leg (A) and product_b_id is the second (B).
    - The compiler builds PS for levels n=1..defaults.ps_max_n, using Ln/L(n+1)
      on both products.
    """

    product_a_id: str
    product_b_id: str


@dataclass(frozen=True, slots=True)
class SyntheticAssetsPolicy:
    """
    Top-level policy container.

    - defaults apply to all products unless overridden by product_overrides.
    - product_spreads is a global directional list.
    """

    defaults: PolicyDefaults
    product_overrides: dict[str, ProductOverrides]
    product_spreads: tuple[ProductSpreadPair, ...]


# -----------------------------------------------------------------------------
# V1 policy authoring
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
    cont_max_n=12,
    ts_max_n=11,
    ps_max_n=3,
)


def v1_policy(*, product_ids: Iterable[str]) -> SyntheticAssetsPolicy:
    """
    Construct the V1 policy for a given product universe.

    Notes:
    - For most products we use fixed_month_mode="valid_rule".
    - Explicit override for GBP: fixed_month_mode="quarterlies".
    """
    universe = set(product_ids)
    overrides: dict[str, ProductOverrides] = {}
    for pid in product_ids:
        overrides[pid] = ProductOverrides(fixed_month_mode="valid_rule")

    # Product-specific overrides (locked for V1).
    # GBP: far-out listings are quarterly; serial months exist only near the front.
    if "cme_gbp_futures" in overrides:
        overrides["cme_gbp_futures"] = ProductOverrides(fixed_month_mode="quarterlies")

    # If you later want to pin explicit month sets, do it like:
    # overrides["cbot_corn_futures"] = ProductOverrides(
    #     fixed_month_months=(3, 5, 7, 9, 12),
    # )

    base_spreads: tuple[ProductSpreadPair, ...] = (
        ProductSpreadPair(
            product_a_id="comex_gold_futures",
            product_b_id="nymex_natural_gas_futures",
        ),
        ProductSpreadPair(
            product_a_id="cbot_corn_futures",
            product_b_id="nymex_natural_gas_futures",
        ),
        ProductSpreadPair(
            product_a_id="cme_emini_snp500_futures",
            product_b_id="cme_gbp_futures",
        ),
    )
    spreads = tuple(
        p
        for p in base_spreads
        if (p.product_a_id in universe and p.product_b_id in universe)
    )
    return SyntheticAssetsPolicy(
        defaults=V1_DEFAULTS,
        product_overrides=overrides,
        product_spreads=spreads,
    )
