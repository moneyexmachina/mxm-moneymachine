# src/mxm/v1/synthetic_assets/policy_compile.py
from __future__ import annotations

"""
MXM V1 — Synthetic Asset policy compiler (Session 24b).

This module compiles a *declarative construction policy* plus authoritative
FuturesProduct metadata into a deterministic list of SyntheticAssetSpec objects.

Responsibilities
----------------
- Pure compilation: no filesystem writes, no registry access, no CLI parsing.
- Use authoritative product metadata for:
  - currency
  - unit
  - contract_size  -> SyntheticAssetSpec.size
  - valid_period_rule (month codes) -> fixed-month selector sets
  - period_types (validate PeriodType.MONTH availability)

- Construct SelectorRule objects using existing Session-18 primitives:
  - listed chain: PeriodFilter(period_type=MONTH)
  - fixed months: PeriodFilter(period_type=MONTH, cycle_id="CALENDAR_MONTHS",
                               cycle_elements={m})

- Call spec_builder.py authoring functions to produce:
  - CONT specs
  - TS specs
  - PS specs

- Return a deterministic list sorted by asset_id.

Notes
-----
This compiler is the canonical place where "V1 policy means X" is implemented.
It is expected to be unit tested directly.

This module assumes SyntheticAssetSpec includes a `size: float` field.
"""

from dataclasses import dataclass
from typing import Mapping, Sequence

from mxm_refdata.models.periods import PeriodType

from mxm.v1.contracts.selectors import PeriodFilter, SelectorRule
from mxm.v1.synthetic_assets.construction_policy import (
    FixedMonthMode,
    ProductOverrides,
    ProductSpreadPair,
    SyntheticAssetsPolicy,
)
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.spec_builder import (
    build_continuous_roll_spec,
    build_product_spread_spec,
    build_time_spread_spec,
)

# -----------------------------------------------------------------------------
# FuturesProduct structural protocol (duck-typed; we do not import the model)
# -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _ProductInfo:
    product_id: str
    currency: str
    unit: str
    contract_size: float
    valid_period_rule: str
    period_types: tuple[PeriodType, ...]


def _coerce_enum_to_str(x: object) -> str:
    name = getattr(x, "name", None)
    if isinstance(name, str) and name:
        return name
    return str(x)


def _as_product_info(p: object) -> _ProductInfo:
    """
    Extract only the fields we need from FuturesProduct (duck-typed).
    """
    pid = getattr(p, "product_id")
    currency = _coerce_enum_to_str(getattr(p, "currency"))
    unit = _coerce_enum_to_str(getattr(p, "unit"))
    contract_size_raw = getattr(p, "contract_size")
    contract_size = float(contract_size_raw)
    valid_period_rule = str(getattr(p, "valid_period_rule"))
    period_types = tuple(getattr(p, "period_types"))
    return _ProductInfo(
        product_id=str(pid),
        currency=currency,
        unit=unit,
        contract_size=contract_size,
        valid_period_rule=valid_period_rule,
        period_types=period_types,
    )


# -----------------------------------------------------------------------------
# Month-code mapping (CME-style futures month codes)
# -----------------------------------------------------------------------------

_MONTH_CODE_TO_MONTH: dict[str, int] = {
    "F": 1,  # Jan
    "G": 2,  # Feb
    "H": 3,  # Mar
    "J": 4,  # Apr
    "K": 5,  # May
    "M": 6,  # Jun
    "N": 7,  # Jul
    "Q": 8,  # Aug
    "U": 9,  # Sep
    "V": 10,  # Oct
    "X": 11,  # Nov
    "Z": 12,  # Dec
}

_QUARTERLY_MONTHS: tuple[int, int, int, int] = (3, 6, 9, 12)


def _months_from_valid_period_rule(valid_period_rule: str) -> tuple[int, ...]:
    months: list[int] = []
    for ch in valid_period_rule.strip():
        m = _MONTH_CODE_TO_MONTH.get(ch.upper())
        if m is None:
            # ignore unknown chars silently to avoid brittleness in policy compile;
            # if this becomes an issue, tighten to raise.
            continue
        months.append(m)
    # stable, unique ordering
    out = sorted(set(months))
    return tuple(out)


# -----------------------------------------------------------------------------
# SelectorRule helpers
# -----------------------------------------------------------------------------


def _listed_rule(*, n: int) -> SelectorRule:
    return SelectorRule(period_filter=PeriodFilter(period_type=PeriodType.MONTH), n=n)


def _fixed_month_rule(*, month: int, n: int) -> SelectorRule:
    return SelectorRule(
        period_filter=PeriodFilter(
            period_type=PeriodType.MONTH,
            cycle_id="CALENDAR_MONTHS",
            cycle_elements=frozenset({int(month)}),
        ),
        n=n,
    )


# -----------------------------------------------------------------------------
# Core compilation
# -----------------------------------------------------------------------------


def compile_specs_from_policy(
    *,
    products: Sequence[object],
    policy: SyntheticAssetsPolicy,
) -> list[SyntheticAssetSpec]:
    """
    Compile SyntheticAssetSpecs from (products, policy).

    Args:
        products: iterable of FuturesProduct-like objects (from RefDataAPI).
        policy: SyntheticAssetsPolicy (from construction_policy.py)

    Returns:
        Deterministic list of SyntheticAssetSpec sorted by asset_id.

    Raises:
        ValueError for missing products, unsupported period_types, or invalid knobs.
    """
    defaults = policy.defaults

    if defaults.cont_max_n < 1:
        raise ValueError("policy.defaults.cont_max_n must be >= 1")
    if defaults.ts_max_n < 0:
        raise ValueError("policy.defaults.ts_max_n must be >= 0")
    if defaults.ts_max_n > max(0, defaults.cont_max_n - 1):
        raise ValueError(
            "policy.defaults.ts_max_n must be <= cont_max_n - 1 "
            "(TS(n) uses levels n..n+2)"
        )
    if defaults.ps_max_n < 0:
        raise ValueError("policy.defaults.ps_max_n must be >= 0")

    infos = [_as_product_info(p) for p in products]
    by_id: dict[str, _ProductInfo] = {pi.product_id: pi for pi in infos}

    # Validate that all policy products exist in this universe.
    missing = sorted(pid for pid in policy.product_overrides.keys() if pid not in by_id)
    if missing:
        raise ValueError(f"Policy references unknown product_ids: {missing}")

    specs: list[SyntheticAssetSpec] = []

    # ------------------------------------------------------------------
    # Per-product assets: listed-chain CONT, TS ladder, and fixed-month CONT set
    # ------------------------------------------------------------------
    for pid, overrides in sorted(policy.product_overrides.items()):
        p = by_id[pid]

        if PeriodType.MONTH not in p.period_types:
            raise ValueError(
                f"Product {pid!r} does not support PeriodType.MONTH; "
                f"period_types={tuple(pt.name for pt in p.period_types)}"
            )

        currency = p.currency
        unit = p.unit
        size = p.contract_size
        wr = defaults.weights_rule_id

        # CONT listed chain: n=1..cont_max_n, each is (Ln, L(n+1))
        for n in range(1, defaults.cont_max_n + 1):
            specs.append(
                build_continuous_roll_spec(
                    product_id=pid,
                    currency=currency,
                    unit=unit,
                    size=size,  # requires SyntheticAssetSpec.size
                    weights_rule_id=wr,
                    cur=_listed_rule(n=n),
                    nxt=_listed_rule(n=n + 1),
                )
            )

        # TS ladder: TS(n) := (Ln/L(n+1)) vs (L(n+1)/L(n+2)), n=1..ts_max_n
        for n in range(1, defaults.ts_max_n + 1):
            specs.append(
                build_time_spread_spec(
                    product_id=pid,
                    currency=currency,
                    unit=unit,
                    size=size,
                    weights_rule_id=wr,
                    near_cur=_listed_rule(n=n),
                    near_nxt=_listed_rule(n=n + 1),
                    far_cur=_listed_rule(n=n + 1),
                    far_nxt=_listed_rule(n=n + 2),
                )
            )

        # Fixed-month CONT set (seasonality / liquidity studies)
        months = _fixed_month_months_for_product(
            p=p,
            overrides=overrides,
        )
        for m in months:
            # Build fixed-month "front within that month family": n=1 only (v1).
            # If you later want depth, add a knob.
            specs.append(
                build_continuous_roll_spec(
                    product_id=pid,
                    currency=currency,
                    unit=unit,
                    size=size,
                    weights_rule_id=wr,
                    cur=_fixed_month_rule(month=m, n=1),
                    nxt=_fixed_month_rule(month=m, n=2),
                )
            )

    # ------------------------------------------------------------------
    # Global product spreads list (directional)
    # ------------------------------------------------------------------
    for pair in policy.product_spreads:
        _validate_pair_exists(pair, by_id)

        pa = by_id[pair.product_a_id]
        pb = by_id[pair.product_b_id]

        # Directional convention (v1): use A's currency/unit/size.
        currency = pa.currency
        unit = pa.unit
        size = pa.contract_size
        wr = defaults.weights_rule_id

        if PeriodType.MONTH not in pa.period_types:
            raise ValueError(f"Product A {pair.product_a_id!r} does not support MONTH")
        if PeriodType.MONTH not in pb.period_types:
            raise ValueError(f"Product B {pair.product_b_id!r} does not support MONTH")

        for n in range(1, defaults.ps_max_n + 1):
            specs.append(
                build_product_spread_spec(
                    product_a_id=pair.product_a_id,
                    product_b_id=pair.product_b_id,
                    currency=currency,
                    unit=unit,
                    size=size,
                    weights_rule_id=wr,
                    a_cur=_listed_rule(n=n),
                    a_nxt=_listed_rule(n=n + 1),
                    b_cur=_listed_rule(n=n),
                    b_nxt=_listed_rule(n=n + 1),
                )
            )

    # Deterministic ordering
    specs.sort(key=lambda s: s.asset_id)
    return specs


def _fixed_month_months_for_product(
    *, p: _ProductInfo, overrides: ProductOverrides
) -> tuple[int, ...]:
    """
    Determine the calendar month set for fixed-month CONT assets for one product.

    Precedence:
    1) overrides.fixed_month_months if provided
    2) overrides.fixed_month_mode:
       - "none"        -> ()
       - "quarterlies" -> (3,6,9,12)
       - "valid_rule"  -> derive from product.valid_period_rule month codes
    """
    if overrides.fixed_month_months is not None:
        # Validate month range 1..12
        months = tuple(int(x) for x in overrides.fixed_month_months)
        bad = [m for m in months if m < 1 or m > 12]
        if bad:
            raise ValueError(
                f"Invalid fixed_month_months for {p.product_id!r}: {bad} (must be in 1..12)"
            )
        return tuple(sorted(set(months)))

    mode: FixedMonthMode = overrides.fixed_month_mode

    if mode == "none":
        return ()

    if mode == "quarterlies":
        return _QUARTERLY_MONTHS

    if mode == "valid_rule":
        return _months_from_valid_period_rule(p.valid_period_rule)

    raise ValueError(f"Unknown fixed_month_mode {mode!r} for product {p.product_id!r}")


def _validate_pair_exists(
    pair: ProductSpreadPair, by_id: Mapping[str, _ProductInfo]
) -> None:
    if pair.product_a_id == pair.product_b_id:
        raise ValueError(f"Invalid product spread pair with A==B: {pair!r}")
    if pair.product_a_id not in by_id:
        raise ValueError(
            f"Unknown product_a_id in product_spreads: {pair.product_a_id!r}"
        )
    if pair.product_b_id not in by_id:
        raise ValueError(
            f"Unknown product_b_id in product_spreads: {pair.product_b_id!r}"
        )
