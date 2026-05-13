from __future__ import annotations

import re

from mxm.v1.contracts.relative_ids import canonical_relative_id
from mxm.v1.contracts.selectors import SelectorRule
from mxm.v1.synthetic_assets.weights_rules import parse_weights_rule_id
from mxm.v1.utils.canonical_id_encoding import (
    decode_canonical_id_component,
    encode_canonical_id_component,
)


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
        f"::WR={encode_canonical_id_component(weights_rule_id)}"
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
        f"::WR={encode_canonical_id_component(weights_rule_id)}"
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
        f"::WR={encode_canonical_id_component(weights_rule_id)}"
    )


_RC_GROUP = r"(RC::.+?)"


def validate_synthetic_asset_canonical_id(canonical_id: str) -> None:
    """
    Validate the structural shape of a Synthetic Asset canonical id.

    V1 scope: structural validation only.
    """
    _validate_synthetic_asset_prefix(canonical_id)

    kind = _parse_synthetic_asset_kind(canonical_id)
    match kind:
        case "CONT":
            _validate_continuous_roll_canonical_id(canonical_id)
        case "TS":
            _validate_time_spread_canonical_id(canonical_id)
        case "PS":
            _validate_product_spread_canonical_id(canonical_id)
        case _:
            raise ValueError(
                f"SyntheticAssetSpec.canonical_id has unknown KIND={kind!r}"
            )


def _validate_synthetic_asset_prefix(canonical_id: str) -> None:
    if not canonical_id.startswith("SA::"):
        raise ValueError("SyntheticAssetSpec.canonical_id must start with 'SA::'")


def _parse_synthetic_asset_kind(canonical_id: str) -> str:
    m_kind = re.match(r"^SA::KIND=(?P<kind>[A-Z]+)", canonical_id)
    if not m_kind:
        raise ValueError("SyntheticAssetSpec.canonical_id missing KIND")
    return m_kind.group("kind")


def _validate_continuous_roll_canonical_id(canonical_id: str) -> None:
    match = _match_continuous_roll_canonical_id(canonical_id)
    _validate_selector_groups_start_with_rc(
        match,
        group_names=("cur", "nxt"),
        error_message=(
            "SyntheticAssetSpec.canonical_id CONT legs must be selector ids "
            "starting with 'RC::'"
        ),
    )
    _validate_wr_group(match)


def _validate_time_spread_canonical_id(canonical_id: str) -> None:
    match = _match_time_spread_canonical_id(canonical_id)
    _validate_selector_groups_start_with_rc(
        match,
        group_names=("near_cur", "near_nxt", "far_cur", "far_nxt"),
        error_message=(
            "SyntheticAssetSpec.canonical_id TS legs must be selector ids "
            "starting with 'RC::'"
        ),
    )
    _validate_wr_group(match)


def _validate_product_spread_canonical_id(canonical_id: str) -> None:
    match = _match_product_spread_canonical_id(canonical_id)
    _validate_selector_groups_start_with_rc(
        match,
        group_names=("a_cur", "a_nxt", "b_cur", "b_nxt"),
        error_message=(
            "SyntheticAssetSpec.canonical_id PS legs must be selector ids "
            "starting with 'RC::'"
        ),
    )
    _validate_wr_group(match)


def _match_continuous_roll_canonical_id(canonical_id: str) -> re.Match[str]:
    pat = re.compile(
        rf"^SA::KIND=CONT"
        rf"::P0=(?P<p0>[^:]+)"
        rf"::CUR=(?P<cur>{_RC_GROUP})(?=::NXT=)"
        rf"::NXT=(?P<nxt>{_RC_GROUP})(?=::WR=)"
        rf"::WR=(?P<wr>.+)$"
    )
    match = pat.match(canonical_id)
    if not match:
        raise ValueError("SyntheticAssetSpec.canonical_id malformed for KIND=CONT")
    return match


def _match_time_spread_canonical_id(canonical_id: str) -> re.Match[str]:
    pat = re.compile(
        rf"^SA::KIND=TS"
        rf"::P0=(?P<p0>[^:]+)"
        rf"::NEAR_CUR=(?P<near_cur>{_RC_GROUP})(?=::NEAR_NXT=)"
        rf"::NEAR_NXT=(?P<near_nxt>{_RC_GROUP})(?=::FAR_CUR=)"
        rf"::FAR_CUR=(?P<far_cur>{_RC_GROUP})(?=::FAR_NXT=)"
        rf"::FAR_NXT=(?P<far_nxt>{_RC_GROUP})(?=::WR=)"
        rf"::WR=(?P<wr>.+)$"
    )
    match = pat.match(canonical_id)
    if not match:
        raise ValueError("SyntheticAssetSpec.canonical_id malformed for KIND=TS")
    return match


def _match_product_spread_canonical_id(canonical_id: str) -> re.Match[str]:
    pat = re.compile(
        rf"^SA::KIND=PS"
        rf"::P0=(?P<p0>[^:]+)"
        rf"::P1=(?P<p1>[^:]+)"
        rf"::A_CUR=(?P<a_cur>{_RC_GROUP})(?=::A_NXT=)"
        rf"::A_NXT=(?P<a_nxt>{_RC_GROUP})(?=::B_CUR=)"
        rf"::B_CUR=(?P<b_cur>{_RC_GROUP})(?=::B_NXT=)"
        rf"::B_NXT=(?P<b_nxt>{_RC_GROUP})(?=::WR=)"
        rf"::WR=(?P<wr>.+)$"
    )
    match = pat.match(canonical_id)
    if not match:
        raise ValueError("SyntheticAssetSpec.canonical_id malformed for KIND=PS")
    return match


def _validate_selector_groups_start_with_rc(
    match: re.Match[str],
    *,
    group_names: tuple[str, ...],
    error_message: str,
) -> None:
    for group_name in group_names:
        if not match.group(group_name).startswith("RC::"):
            raise ValueError(error_message)


def _validate_wr_group(match: re.Match[str]) -> None:
    wr_encoded = match.group("wr")
    try:
        wr = decode_canonical_id_component(wr_encoded)
    except Exception as e:
        raise ValueError(
            "SyntheticAssetSpec.canonical_id contains invalid encoded WR payload"
        ) from e

    try:
        parse_weights_rule_id(wr)
    except Exception as e:
        raise ValueError(
            "SyntheticAssetSpec.canonical_id contains invalid decoded weights_rule_id"
        ) from e
