from __future__ import annotations

"""
MXM V1 — Synthetic Asset Policy Compiler

This module compiles the declarative synthetic-asset construction policy into
concrete SyntheticAssetSpec objects.

The compiler combines:

- authoritative FuturesProduct metadata from refdata
- authored synthetic-asset family policy from construction_policy.py

For each product, the compiler builds synthetic assets from the explicitly
authored PeriodFilter families in policy.

For each family, the compiler constructs:
- continuous rolls (CONT)
- time spreads (TS)

For each authored product spread policy, the compiler constructs:
- family-aware product spreads (PS)

This module is pure compilation logic. It must not:
- read or write registries
- touch the filesystem
- perform CLI parsing

It is the canonical place where policy meaning is turned into concrete
SyntheticAssetSpec definitions.
"""

from typing import Mapping, Sequence

from mxm_refdata.models import FuturesProduct, PeriodType

from mxm.v1.contracts.selectors import SelectorRule
from mxm.v1.synthetic_assets.construction_policy import (
    PeriodFamilyPolicy,
    ProductPolicy,
    ProductSpreadPolicy,
    SyntheticAssetsPolicy,
)
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.spec_builder import (
    build_continuous_roll_spec,
    build_product_spread_spec,
    build_time_spread_spec,
)

# -----------------------------------------------------------------------------
# Small helpers
# -----------------------------------------------------------------------------


def _selector_rule(*, family: PeriodFamilyPolicy, n: int) -> SelectorRule:
    """
    Construct a SelectorRule for the nth ranked contract in a policy-authored
    PeriodFilter family.
    """
    return SelectorRule(period_filter=family.period_filter, n=n)


def _family_by_code(
    *,
    product_policy: ProductPolicy,
    family_code: str,
) -> PeriodFamilyPolicy:
    """
    Resolve a family_code within one ProductPolicy.
    """
    for family in product_policy.families:
        if family.family_code == family_code:
            return family
    raise ValueError(
        f"Product {product_policy.product_id!r} has no family_code={family_code!r}"
    )


# -----------------------------------------------------------------------------
# Validation
# -----------------------------------------------------------------------------


def _validate_family_policy(*, product_id: str, family: PeriodFamilyPolicy) -> None:
    ctx = f"product_id={product_id!r}, family_code={family.family_code!r}"

    if not family.family_code:
        raise ValueError(f"{ctx}: family_code must be non-empty")

    if family.cont_max_n < 1:
        raise ValueError(f"{ctx}: cont_max_n must be >= 1")

    if family.ts_max_n < 0:
        raise ValueError(f"{ctx}: ts_max_n must be >= 0")

    if family.ts_max_n > family.cont_max_n - 1:
        raise ValueError(f"{ctx}: ts_max_n must be <= cont_max_n - 1")


def _validate_product_policy(
    *,
    product: FuturesProduct,
    product_policy: ProductPolicy,
) -> None:
    """
    Validate one product policy against the authoritative FuturesProduct.
    """
    if PeriodType.MONTH not in product.period_types:
        raise ValueError(
            f"Product {product.product_id!r} does not support PeriodType.MONTH; "
            f"period_types={tuple(pt.name for pt in product.period_types)}"
        )

    seen_codes: set[str] = set()
    for family in product_policy.families:
        _validate_family_policy(product_id=product.product_id, family=family)

        if family.family_code in seen_codes:
            raise ValueError(
                f"Duplicate family_code={family.family_code!r} for "
                f"product_id={product.product_id!r}"
            )
        seen_codes.add(family.family_code)

        if family.period_filter.period_type != PeriodType.MONTH:
            raise ValueError(
                f"product_id={product.product_id!r}, family_code={family.family_code!r}: "
                f"expected period_filter.period_type=MONTH, got "
                f"{family.period_filter.period_type!r}"
            )


def _validate_spread_policy(
    *,
    spread: ProductSpreadPolicy,
    by_product_policy: Mapping[str, ProductPolicy],
    by_product: Mapping[str, FuturesProduct],
) -> None:
    """
    Validate one product-spread policy.
    """
    if spread.product_a_id == spread.product_b_id:
        raise ValueError(f"Invalid product spread with A==B: {spread!r}")

    if spread.ps_max_n < 1:
        raise ValueError(f"Invalid ps_max_n for spread {spread!r}: must be >= 1")

    if spread.product_a_id not in by_product:
        raise ValueError(
            f"Unknown product_a_id in product spread policy: {spread.product_a_id!r}"
        )
    if spread.product_b_id not in by_product:
        raise ValueError(
            f"Unknown product_b_id in product spread policy: {spread.product_b_id!r}"
        )

    if spread.product_a_id not in by_product_policy:
        raise ValueError(
            f"No ProductPolicy found for spread product_a_id={spread.product_a_id!r}"
        )
    if spread.product_b_id not in by_product_policy:
        raise ValueError(
            f"No ProductPolicy found for spread product_b_id={spread.product_b_id!r}"
        )

    policy_a = by_product_policy[spread.product_a_id]
    policy_b = by_product_policy[spread.product_b_id]

    _family_by_code(product_policy=policy_a, family_code=spread.family_a_code)
    _family_by_code(product_policy=policy_b, family_code=spread.family_b_code)


# -----------------------------------------------------------------------------
# Core compilation
# -----------------------------------------------------------------------------


def compile_specs_from_policy(
    *,
    products: Sequence[FuturesProduct],
    policy: SyntheticAssetsPolicy,
) -> list[SyntheticAssetSpec]:
    """
    Compile SyntheticAssetSpecs from authoritative products plus construction policy.

    Args:
        products:
            FuturesProduct objects from refdata.
        policy:
            SyntheticAssetsPolicy authored in construction_policy.py.

    Returns:
        Deterministic list of SyntheticAssetSpec sorted by asset_id.

    Raises:
        ValueError:
            If policy references missing products, uses invalid depth knobs,
            references unknown families, or is structurally inconsistent.
    """
    by_product: dict[str, FuturesProduct] = {p.product_id: p for p in products}
    by_product_policy: dict[str, ProductPolicy] = {
        pp.product_id: pp for pp in policy.products
    }

    missing_products = sorted(pid for pid in by_product_policy if pid not in by_product)
    if missing_products:
        raise ValueError(f"Policy references unknown product_ids: {missing_products}")

    for product_policy in policy.products:
        product = by_product[product_policy.product_id]
        _validate_product_policy(product=product, product_policy=product_policy)

    for spread in policy.product_spreads:
        _validate_spread_policy(
            spread=spread,
            by_product_policy=by_product_policy,
            by_product=by_product,
        )

    specs: list[SyntheticAssetSpec] = []
    weights_rule_id = policy.defaults.weights_rule_id

    # ------------------------------------------------------------------
    # Per-product family compilation
    # ------------------------------------------------------------------
    for product_policy in sorted(policy.products, key=lambda x: x.product_id):
        product = by_product[product_policy.product_id]

        currency = product.currency.name
        unit = product.unit.name
        size = float(product.contract_size)

        for family in product_policy.families:
            # CONT: family1 .. familyN
            for n in range(1, family.cont_max_n + 1):
                specs.append(
                    build_continuous_roll_spec(
                        product_id=product.product_id,
                        currency=currency,
                        unit=unit,
                        size=size,
                        weights_rule_id=weights_rule_id,
                        cur=_selector_rule(family=family, n=n),
                        nxt=_selector_rule(family=family, n=n + 1),
                    )
                )

            # TS: family1/family2 .. familyN/family(N+1)
            for n in range(1, family.ts_max_n + 1):
                specs.append(
                    build_time_spread_spec(
                        product_id=product.product_id,
                        currency=currency,
                        unit=unit,
                        size=size,
                        weights_rule_id=weights_rule_id,
                        near_cur=_selector_rule(family=family, n=n),
                        near_nxt=_selector_rule(family=family, n=n + 1),
                        far_cur=_selector_rule(family=family, n=n + 1),
                        far_nxt=_selector_rule(family=family, n=n + 2),
                    )
                )

    # ------------------------------------------------------------------
    # Family-aware product spreads
    # ------------------------------------------------------------------
    for spread in policy.product_spreads:
        product_a = by_product[spread.product_a_id]
        product_b = by_product[spread.product_b_id]

        policy_a = by_product_policy[spread.product_a_id]
        policy_b = by_product_policy[spread.product_b_id]

        family_a = _family_by_code(
            product_policy=policy_a,
            family_code=spread.family_a_code,
        )
        family_b = _family_by_code(
            product_policy=policy_b,
            family_code=spread.family_b_code,
        )

        # Directional convention retained from earlier implementation:
        # PS(A,B) uses A's currency, unit, and contract size.
        currency = product_a.currency.name
        unit = product_a.unit.name
        size = float(product_a.contract_size)

        for n in range(1, spread.ps_max_n + 1):
            specs.append(
                build_product_spread_spec(
                    product_a_id=product_a.product_id,
                    product_b_id=product_b.product_id,
                    currency=currency,
                    unit=unit,
                    size=size,
                    weights_rule_id=weights_rule_id,
                    a_cur=_selector_rule(family=family_a, n=n),
                    a_nxt=_selector_rule(family=family_a, n=n + 1),
                    b_cur=_selector_rule(family=family_b, n=n),
                    b_nxt=_selector_rule(family=family_b, n=n + 1),
                )
            )

    specs.sort(key=lambda s: s.asset_id)
    return specs
