from __future__ import annotations

from mxm.refdata.models import (
    Currency,
    FuturesProduct,
    PeriodType,
    ProductUnit,
    SettlementMethod,
)
from mxm.v1.synthetic_assets.construction_policy import v1_policy
from mxm.v1.synthetic_assets.policy_compile import compile_specs_from_policy


def _product(
    *,
    product_id: str,
    venue: str,
    description: str,
    currency: Currency,
    unit: ProductUnit,
    contract_size: float,
    valid_period_rule: str,
    listing_rule: str,
    settlement: SettlementMethod,
) -> FuturesProduct:
    """
    Minimal FuturesProduct fixture helper for policy-compile tests.

    Only a subset of fields are materially used by compile_specs_from_policy,
    but FuturesProduct is an authoritative dataclass so we populate all required
    constructor fields.
    """
    return FuturesProduct(
        product_id=product_id,
        venue=venue,
        description=description,
        currency=currency,
        unit=unit,
        contract_size=contract_size,
        valid_period_rule=valid_period_rule,
        listing_rule=listing_rule,
        period_types=(PeriodType.MONTH,),
        settlement=settlement,
        last_trading_rule="dummy last trading rule",
        expiry_rule="dummy expiry rule",
        trading_calendar="CMES",
        trading_hours=None,
        tick_size=None,
        tick_value=None,
        initial_margin=None,
        maintenance_margin=None,
    )


def _five_products() -> list[FuturesProduct]:
    return [
        _product(
            product_id="comex_gold_futures",
            venue="COMEX",
            description="Gold Futures",
            currency=Currency.USD,
            unit=ProductUnit.TROY_OUNCE,
            contract_size=100.0,
            valid_period_rule="FGHJKMNQUVXZ",
            listing_rule=(
                "Monthly contracts listed for 24 consecutive months and any "
                "Jun and Dec in the nearest 72 months."
            ),
            settlement=SettlementMethod.PHYSICAL,
        ),
        _product(
            product_id="cbot_corn_futures",
            venue="CBOT",
            description="Corn Futures",
            currency=Currency.USD,
            unit=ProductUnit.BUSHEL,
            contract_size=5000.0,
            valid_period_rule="HKNUZ",
            listing_rule=(
                "9 monthly contracts of Mar, May, Sep and 8 monthly contracts "
                "of Jul and Dec listed annually after the termination of trading "
                "in the December contract of the current year."
            ),
            settlement=SettlementMethod.PHYSICAL,
        ),
        _product(
            product_id="cme_gbp_futures",
            venue="CME",
            description="British Pound Futures",
            currency=Currency.USD,
            unit=ProductUnit.GBP,
            contract_size=62500.0,
            valid_period_rule="FGHJKMNQUVXZ",
            listing_rule=(
                "Quarterly contracts (Mar, Jun, Sep, Dec) listed for 20 "
                "consecutive quarters and serial contracts listed for 3 months."
            ),
            settlement=SettlementMethod.PHYSICAL,
        ),
        _product(
            product_id="cme_emini_snp500_futures",
            venue="CME",
            description="S&P 500 E-mini Futures",
            currency=Currency.USD,
            unit=ProductUnit.INDEX_POINT,
            contract_size=50.0,
            valid_period_rule="HMUZ",
            listing_rule="Quarterly contracts (Mar, Jun, Sep, Dec) listed for 21 consecutive quarters.",
            settlement=SettlementMethod.FINANCIAL,
        ),
        _product(
            product_id="nymex_natural_gas_futures",
            venue="NYMEX",
            description="HH Natural Gas Futures",
            currency=Currency.USD,
            unit=ProductUnit.MMBTU,
            contract_size=10000.0,
            valid_period_rule="FGHJKMNQUVXZ",
            listing_rule=(
                "Monthly contracts listed for the current year and the next "
                "12 calendar years."
            ),
            settlement=SettlementMethod.PHYSICAL,
        ),
    ]


def test_compile_counts_and_determinism_for_5_products() -> None:
    products = _five_products()
    policy = v1_policy(product_ids=[p.product_id for p in products])

    specs1 = compile_specs_from_policy(products=products, policy=policy)
    specs2 = compile_specs_from_policy(products=products, policy=policy)

    # deterministic and stable ordering
    assert [s.asset_id for s in specs1] == [s.asset_id for s in specs2]
    assert [s.asset_id for s in specs1] == sorted(s.asset_id for s in specs1)

    # Session-26 policy surface:
    #
    # Gold:
    #   M family                22 CONT + 21 TS = 43
    #   12 singleton months      24 CONT + 12 TS = 36
    #   JunDec family             5 CONT +  4 TS =  9
    #   total gold = 88
    #
    # NatGas:
    #   M family                70 CONT + 69 TS = 139
    #   12 singleton months      60 CONT + 48 TS = 108
    #   total natgas = 247
    #
    # GBP:
    #   M family                 3 CONT +  2 TS =  5
    #   HMUZ family             20 CONT + 19 TS = 39
    #   4 singleton months       20 CONT + 16 TS = 36
    #   total gbp = 80
    #
    # ES:
    #   HMUZ family             20 CONT + 19 TS = 39
    #   4 singleton months       20 CONT + 16 TS = 36
    #   total es = 75
    #
    # Corn:
    #   HKNUZ family             8 CONT +  7 TS = 15
    #   5 singleton months       10 CONT +  5 TS = 15
    #   total corn = 30
    #
    # Product spreads:
    #   gold M vs natgas M       3
    #   es HMUZ vs gbp HMUZ      3
    #   total PS = 6
    #
    # Grand total = 88 + 247 + 80 + 75 + 30 + 6 = 526
    assert len(specs1) == 526


def test_gbp_singleton_month_families_are_quarterlies_only() -> None:
    products = [
        _product(
            product_id="cme_gbp_futures",
            venue="CME",
            description="British Pound Futures",
            currency=Currency.USD,
            unit=ProductUnit.GBP,
            contract_size=62500.0,
            valid_period_rule="FGHJKMNQUVXZ",
            listing_rule=(
                "Quarterly contracts (Mar, Jun, Sep, Dec) listed for 20 "
                "consecutive quarters and serial contracts listed for 3 months."
            ),
            settlement=SettlementMethod.PHYSICAL,
        )
    ]

    policy = v1_policy(product_ids=["cme_gbp_futures"])
    specs = compile_specs_from_policy(products=products, policy=policy)
    ids = [s.asset_id for s in specs]

    # Present: quarter-month singleton families
    assert any("_cont_mar1_" in x for x in ids)
    assert any("_cont_jun1_" in x for x in ids)
    assert any("_cont_sep1_" in x for x in ids)
    assert any("_cont_dec1_" in x for x in ids)

    # Absent: non-quarter singleton month families
    assert not any("_cont_jan1_" in x for x in ids)
    assert not any("_cont_feb1_" in x for x in ids)
    assert not any("_cont_apr1_" in x for x in ids)
    assert not any("_cont_may1_" in x for x in ids)
    assert not any("_cont_jul1_" in x for x in ids)
    assert not any("_cont_aug1_" in x for x in ids)
    assert not any("_cont_oct1_" in x for x in ids)
    assert not any("_cont_nov1_" in x for x in ids)
