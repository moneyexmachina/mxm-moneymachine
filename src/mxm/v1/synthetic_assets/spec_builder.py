from __future__ import annotations

import re

from mxm.v1.contracts.relative_ids import canonical_relative_id, short_rel_id
from mxm.v1.contracts.selectors import SelectorRule
from mxm.v1.synthetic_assets.canonical_ids import (
    canonical_continuous_roll_id,
    canonical_product_spread_id,
    canonical_time_spread_id,
)
from mxm.v1.synthetic_assets.models import LegBinding, SyntheticAssetSpec
from mxm.v1.synthetic_assets.weights_rules import (
    parse_weights_rule_id,
    short_weights_rule_id,
)

_SLUG_SAFE_RE = re.compile(r"[^a-z0-9_]+")


def _slugify_component(s: str) -> str:
    x = s.strip().lower()
    x = _SLUG_SAFE_RE.sub("_", x)
    x = re.sub(r"_+", "_", x)
    return x.strip("_")


def build_continuous_roll_spec(
    *,
    product_id: str,
    currency: str,
    unit: str,
    size: float,
    weights_rule_id: str,
    cur: SelectorRule,
    nxt: SelectorRule,
    role_cur: str = "cur",
    role_nxt: str = "nxt",
) -> SyntheticAssetSpec:
    cur_short = _slugify_component(short_rel_id(cur))
    wr_short = short_weights_rule_id(parse_weights_rule_id(weights_rule_id))
    asset_id = f"{product_id}_cont_{cur_short}_wr_{wr_short}"

    canonical_id = canonical_continuous_roll_id(
        product_id=product_id,
        cur=cur,
        nxt=nxt,
        weights_rule_id=weights_rule_id,
    )

    legs = {
        role_cur: LegBinding(
            product_id=product_id,
            selector_rule_id=canonical_relative_id(cur),
        ),
        role_nxt: LegBinding(
            product_id=product_id,
            selector_rule_id=canonical_relative_id(nxt),
        ),
    }

    return SyntheticAssetSpec(
        asset_id=asset_id,
        canonical_id=canonical_id,
        currency=currency,
        unit=unit,
        size=size,
        weights_rule_id=weights_rule_id,
        legs=legs,
    )


def build_time_spread_spec(
    *,
    product_id: str,
    currency: str,
    unit: str,
    size: float,
    weights_rule_id: str,
    near_cur: SelectorRule,
    near_nxt: SelectorRule,
    far_cur: SelectorRule,
    far_nxt: SelectorRule,
    role_near_cur: str = "near_cur",
    role_near_nxt: str = "near_nxt",
    role_far_cur: str = "far_cur",
    role_far_nxt: str = "far_nxt",
) -> SyntheticAssetSpec:
    """
    Author a time-spread synthetic asset for a single product.

    Notes:
    - `near_cur` and `far_cur` exist to lock the slug intent (L1 vs L2 etc) independently
      of the internal leg roles, while still allowing explicit leg rule injection.
    - Legs are provided as (near_cur, near_nxt, far_cur, far_nxt) to support the
      later roll-aware execution / target trade derivation.
    """
    near_short = _slugify_component(short_rel_id(near_cur))
    far_short = _slugify_component(short_rel_id(far_cur))

    wr_short = short_weights_rule_id(parse_weights_rule_id(weights_rule_id))
    asset_id = f"{product_id}_ts_{near_short}_{far_short}_wr_{wr_short}"

    canonical_id = canonical_time_spread_id(
        product_id=product_id,
        near_cur=near_cur,
        near_nxt=near_nxt,
        far_cur=far_cur,
        far_nxt=far_nxt,
        weights_rule_id=weights_rule_id,
    )

    legs = {
        role_near_cur: LegBinding(
            product_id=product_id,
            selector_rule_id=canonical_relative_id(near_cur),
        ),
        role_near_nxt: LegBinding(
            product_id=product_id,
            selector_rule_id=canonical_relative_id(near_nxt),
        ),
        role_far_cur: LegBinding(
            product_id=product_id,
            selector_rule_id=canonical_relative_id(far_cur),
        ),
        role_far_nxt: LegBinding(
            product_id=product_id,
            selector_rule_id=canonical_relative_id(far_nxt),
        ),
    }

    return SyntheticAssetSpec(
        asset_id=asset_id,
        canonical_id=canonical_id,
        currency=currency,
        unit=unit,
        size=size,
        weights_rule_id=weights_rule_id,
        legs=legs,
    )


def build_product_spread_spec(
    *,
    product_a_id: str,
    product_b_id: str,
    currency: str,
    unit: str,
    size: float,
    weights_rule_id: str,
    a_cur: SelectorRule,
    a_nxt: SelectorRule,
    b_cur: SelectorRule,
    b_nxt: SelectorRule,
    role_a_cur: str = "a_cur",
    role_a_nxt: str = "a_nxt",
    role_b_cur: str = "b_cur",
    role_b_nxt: str = "b_nxt",
) -> SyntheticAssetSpec:
    """
    Author a product-spread synthetic asset between two products.

    Semantics:
    - Ordered and directional: (A,B) is distinct from (B,A).
    - No sorting or re-ordering is permitted.
    - Slug is anchored on the A-leg selection depth for compactness.
    """
    if product_a_id == product_b_id:
        raise ValueError("Product spread requires two distinct products (A != B)")
    a_short = _slugify_component(short_rel_id(a_cur))

    wr_short = short_weights_rule_id(parse_weights_rule_id(weights_rule_id))
    asset_id = f"{product_a_id}_ps_{product_b_id}_{a_short}_wr_{wr_short}"

    canonical_id = canonical_product_spread_id(
        product_a_id=product_a_id,
        product_b_id=product_b_id,
        a_cur=a_cur,
        a_nxt=a_nxt,
        b_cur=b_cur,
        b_nxt=b_nxt,
        weights_rule_id=weights_rule_id,
    )

    legs = {
        role_a_cur: LegBinding(
            product_id=product_a_id,
            selector_rule_id=canonical_relative_id(a_cur),
        ),
        role_a_nxt: LegBinding(
            product_id=product_a_id,
            selector_rule_id=canonical_relative_id(a_nxt),
        ),
        role_b_cur: LegBinding(
            product_id=product_b_id,
            selector_rule_id=canonical_relative_id(b_cur),
        ),
        role_b_nxt: LegBinding(
            product_id=product_b_id,
            selector_rule_id=canonical_relative_id(b_nxt),
        ),
    }

    return SyntheticAssetSpec(
        asset_id=asset_id,
        canonical_id=canonical_id,
        currency=currency,
        unit=unit,
        size=size,
        weights_rule_id=weights_rule_id,
        legs=legs,
    )
