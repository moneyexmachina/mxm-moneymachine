# src/mxm/v1/synthetic_assets/canonical_ids.py
from __future__ import annotations

import re

from mxm.v1.contracts.relative_ids import canonical_relative_id
from mxm.v1.contracts.selectors import SelectorRule


def canonical_continuous_roll_id(
    *,
    product_id: str,
    cur: SelectorRule,
    nxt: SelectorRule,
    weights_rule_id: str,
) -> str:
    """
    Canonical, machine-parseable id for a continuous rolling future synthetic asset.

    Grammar (V1):
        SA::KIND=CONT::P0=<product_id>::CUR=<RC...>::NXT=<RC...>::WR=<weights_rule_id>

    Notes:
    - CUR/NXT are selector canonical relative ids (RC::...).
    - weights_rule_id is referenced verbatim (registry-scoped).
    """
    return (
        "SA::KIND=CONT"
        f"::P0={product_id}"
        f"::CUR={canonical_relative_id(cur)}"
        f"::NXT={canonical_relative_id(nxt)}"
        f"::WR={weights_rule_id}"
    )


def canonical_time_spread_id(
    *,
    product_id: str,
    near_cur: SelectorRule,
    near_nxt: SelectorRule,
    far_cur: SelectorRule,
    far_nxt: SelectorRule,
    weights_rule_id: str,
) -> str:
    """
    Canonical, machine-parseable id for a time-spread synthetic asset.

    Time-spread is defined as two rolling pairs (near and far) on the same product.

    Grammar (V1):
        SA::KIND=TS::P0=<product_id>
          ::NEAR_CUR=<RC...>::NEAR_NXT=<RC...>
          ::FAR_CUR=<RC...>::FAR_NXT=<RC...>
          ::WR=<weights_rule_id>
    """
    return (
        "SA::KIND=TS"
        f"::P0={product_id}"
        f"::NEAR_CUR={canonical_relative_id(near_cur)}"
        f"::NEAR_NXT={canonical_relative_id(near_nxt)}"
        f"::FAR_CUR={canonical_relative_id(far_cur)}"
        f"::FAR_NXT={canonical_relative_id(far_nxt)}"
        f"::WR={weights_rule_id}"
    )


def canonical_product_spread_id(
    *,
    product_a_id: str,
    product_b_id: str,
    a_cur: SelectorRule,
    a_nxt: SelectorRule,
    b_cur: SelectorRule,
    b_nxt: SelectorRule,
    weights_rule_id: str,
) -> str:
    """
    Canonical, machine-parseable id for a product-spread synthetic asset.

    Product-spread is defined as two rolling pairs (A and B) on two products.

    Grammar (V1):
        SA::KIND=PS::P0=<product_a_id>::P1=<product_b_id>
          ::A_CUR=<RC...>::A_NXT=<RC...>
          ::B_CUR=<RC...>::B_NXT=<RC...>
          ::WR=<weights_rule_id>
    """
    return (
        "SA::KIND=PS"
        f"::P0={product_a_id}"
        f"::P1={product_b_id}"
        f"::A_CUR={canonical_relative_id(a_cur)}"
        f"::A_NXT={canonical_relative_id(a_nxt)}"
        f"::B_CUR={canonical_relative_id(b_cur)}"
        f"::B_NXT={canonical_relative_id(b_nxt)}"
        f"::WR={weights_rule_id}"
    )


def validate_synthetic_asset_canonical_id(canonical_id: str) -> None:
    """
    Validate the structural shape of a Synthetic Asset canonical id.

    V1 scope: structural validation only.

    Important:
    - SyntheticAsset canonical ids embed selector canonical ids (RC::...) which
      themselves contain '::' tokens. Therefore we must not parse SA canonical ids
      by naive splitting on '::'.
    - This validator is intentionally strict on top-level field order and presence.
    - It does not parse RC internals; it only verifies that embedded fields start
      with 'RC::'.
    """
    if not isinstance(canonical_id, str) or not canonical_id:
        raise ValueError("SyntheticAssetSpec.canonical_id must be a non-empty string")

    if not canonical_id.startswith("SA::"):
        raise ValueError("SyntheticAssetSpec.canonical_id must start with 'SA::'")

    # Fast kind detection
    m_kind = re.match(r"^SA::KIND=(?P<kind>[A-Z]+)", canonical_id)
    if not m_kind:
        raise ValueError("SyntheticAssetSpec.canonical_id missing KIND")
    kind = m_kind.group("kind")

    # Common fragments
    # - product ids and weights_rule_id must not contain '::' (they are top-level values)
    # - embedded selector ids must start with 'RC::' and may contain '::' internally
    rc = r"(RC::.+?)"

    if kind == "CONT":
        # SA::KIND=CONT::P0=...::CUR=RC::...::NXT=RC::...::WR=...
        pat = re.compile(
            rf"^SA::KIND=CONT"
            rf"::P0=(?P<p0>[^:]+)"
            rf"::CUR=(?P<cur>{rc})(?=::NXT=)"
            rf"::NXT=(?P<nxt>{rc})(?=::WR=)"
            rf"::WR=(?P<wr>[^:]+)$"
        )
        m = pat.match(canonical_id)
        if not m:
            raise ValueError("SyntheticAssetSpec.canonical_id malformed for KIND=CONT")
        if not m.group("cur").startswith("RC::") or not m.group("nxt").startswith(
            "RC::"
        ):
            raise ValueError(
                "SyntheticAssetSpec.canonical_id CONT legs must be selector ids starting with 'RC::'"
            )
        return

    if kind == "TS":
        # SA::KIND=TS::P0=...::NEAR_CUR=RC::...::NEAR_NXT=RC::...::FAR_CUR=RC::...::FAR_NXT=RC::...::WR=...
        pat = re.compile(
            rf"^SA::KIND=TS"
            rf"::P0=(?P<p0>[^:]+)"
            rf"::NEAR_CUR=(?P<near_cur>{rc})(?=::NEAR_NXT=)"
            rf"::NEAR_NXT=(?P<near_nxt>{rc})(?=::FAR_CUR=)"
            rf"::FAR_CUR=(?P<far_cur>{rc})(?=::FAR_NXT=)"
            rf"::FAR_NXT=(?P<far_nxt>{rc})(?=::WR=)"
            rf"::WR=(?P<wr>[^:]+)$"
        )
        m = pat.match(canonical_id)
        if not m:
            raise ValueError("SyntheticAssetSpec.canonical_id malformed for KIND=TS")
        for k in ("near_cur", "near_nxt", "far_cur", "far_nxt"):
            if not m.group(k).startswith("RC::"):
                raise ValueError(
                    "SyntheticAssetSpec.canonical_id TS legs must be selector ids starting with 'RC::'"
                )
        return

    if kind == "PS":
        # SA::KIND=PS::P0=...::P1=...::A_CUR=RC::...::A_NXT=RC::...::B_CUR=RC::...::B_NXT=RC::...::WR=...
        pat = re.compile(
            rf"^SA::KIND=PS"
            rf"::P0=(?P<p0>[^:]+)"
            rf"::P1=(?P<p1>[^:]+)"
            rf"::A_CUR=(?P<a_cur>{rc})(?=::A_NXT=)"
            rf"::A_NXT=(?P<a_nxt>{rc})(?=::B_CUR=)"
            rf"::B_CUR=(?P<b_cur>{rc})(?=::B_NXT=)"
            rf"::B_NXT=(?P<b_nxt>{rc})(?=::WR=)"
            rf"::WR=(?P<wr>[^:]+)$"
        )
        m = pat.match(canonical_id)
        if not m:
            raise ValueError("SyntheticAssetSpec.canonical_id malformed for KIND=PS")
        for k in ("a_cur", "a_nxt", "b_cur", "b_nxt"):
            if not m.group(k).startswith("RC::"):
                raise ValueError(
                    "SyntheticAssetSpec.canonical_id PS legs must be selector ids starting with 'RC::'"
                )
        return

    raise ValueError(f"SyntheticAssetSpec.canonical_id has unknown KIND={kind!r}")
