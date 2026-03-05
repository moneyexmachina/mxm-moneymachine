from __future__ import annotations

from dataclasses import dataclass

from mxm_refdata.models.periods import PeriodType

from mxm.v1.synthetic_assets.construction_policy import v1_policy
from mxm.v1.synthetic_assets.policy_compile import compile_specs_from_policy


@dataclass(frozen=True, slots=True)
class DummyProduct:
    product_id: str
    currency: str
    unit: str
    contract_size: float
    valid_period_rule: str
    period_types: tuple[PeriodType, ...]


def test_compile_counts_and_determinism_for_5_products() -> None:
    products = [
        DummyProduct(
            product_id="comex_gold_futures",
            currency="USD",
            unit="TROY_OUNCE",
            contract_size=100.0,
            valid_period_rule="FGHJKMNQUVXZ",
            period_types=(PeriodType.MONTH,),
        ),
        DummyProduct(
            product_id="cbot_corn_futures",
            currency="USD",
            unit="BUSHEL",
            contract_size=5000.0,
            valid_period_rule="HKNUZ",
            period_types=(PeriodType.MONTH,),
        ),
        DummyProduct(
            product_id="cme_gbp_futures",
            currency="USD",
            unit="GBP",
            contract_size=62500.0,
            valid_period_rule="FGHJKMNQUVXZ",
            period_types=(PeriodType.MONTH,),
        ),
        DummyProduct(
            product_id="cme_emini_snp500_futures",
            currency="USD",
            unit="INDEX_POINT",
            contract_size=50.0,
            valid_period_rule="HMUZ",
            period_types=(PeriodType.MONTH,),
        ),
        DummyProduct(
            product_id="nymex_natural_gas_futures",
            currency="USD",
            unit="MMBTU",
            contract_size=10000.0,
            valid_period_rule="FGHJKMNQUVXZ",
            period_types=(PeriodType.MONTH,),
        ),
    ]

    policy = v1_policy(product_ids=[p.product_id for p in products])

    specs1 = compile_specs_from_policy(products=products, policy=policy)
    specs2 = compile_specs_from_policy(products=products, policy=policy)

    # deterministic and stable ordering
    assert [s.asset_id for s in specs1] == [s.asset_id for s in specs2]
    assert [s.asset_id for s in specs1] == sorted(s.asset_id for s in specs1)

    # sanity counts for v1 defaults:
    # CONT: 5 * 12 = 60
    # TS:   5 * 11 = 55
    # fixed-month CONT:
    #   gold 12 + natgas 12 + corn 5 + es 4 + gbp quarterlies 4 = 37
    # PS: 3 pairs * 3 levels = 9
    # total = 161
    assert len(specs1) == 161


def test_gbp_fixed_month_is_quarterlies_only() -> None:
    products = [
        DummyProduct(
            product_id="cme_gbp_futures",
            currency="USD",
            unit="GBP",
            contract_size=62500.0,
            valid_period_rule="FGHJKMNQUVXZ",
            period_types=(PeriodType.MONTH,),
        )
    ]
    policy = v1_policy(product_ids=["cme_gbp_futures"])
    specs = compile_specs_from_policy(products=products, policy=policy)

    # Fixed-month CONT assets embed selector short ids in asset_id via spec_builder.
    # Quarterlies are Mar/Jun/Sep/Dec => Mar1, Jun1, Sep1, Dec1 appear (slugified).
    ids = [s.asset_id for s in specs]
    fixed = [
        x
        for x in ids
        if "_cont_" in x and ("mar1" in x or "jun1" in x or "sep1" in x or "dec1" in x)
    ]
    assert len(fixed) == 4
