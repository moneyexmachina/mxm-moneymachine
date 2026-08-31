from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from mxm.refdata.models.contracts.futures_contract import (
    FuturesContract,  # type: ignore
)
from mxm.refdata.models.currencies import Currency
from mxm.refdata.models.units import ProductUnit


def make_contract(
    *,
    product_id: str,
    contract_id: str = "TEST.2020-01",
    period_id: str = "P.TEST.2020-01",
    first_day_of_interest: dt.date = dt.date(2020, 1, 2),
    last_trading_day: dt.date = dt.date(2020, 1, 3),
    contract_size: float = 1.0,
    unit: ProductUnit = ProductUnit.CONTRACT,
    currency: Currency = Currency.USD,
    trading_calendar: str = "TEST_CAL",
) -> FuturesContract:
    """
    Construct a FuturesContract using the real domain class.

    NOTE: In production, contract_year_month() resolves via RefDataReader periods lookup.
    Hermetic tests should patch contract_year_month() (or period_by_id()) so period_id
    does not require live refdata.
    """
    return FuturesContract(
        contract_id=contract_id,
        product_id=product_id,
        period_id=period_id,
        contract_size=contract_size,
        unit=unit,
        currency=currency,
        trading_calendar=trading_calendar,
        first_day_of_interest=first_day_of_interest,
        last_trading_day=last_trading_day,
    )


def make_contracts(
    *,
    product_id: str,
    year: int = 2020,
    months: Iterable[int] = (1,),
) -> list[FuturesContract]:
    contracts: list[FuturesContract] = []
    for m in months:
        period_id = f"P.TEST.{year:04d}-{m:02d}"
        contract_id = f"{product_id}.{year:04d}-{m:02d}"
        contracts.append(
            make_contract(
                product_id=product_id,
                contract_id=contract_id,
                period_id=period_id,
                first_day_of_interest=dt.date(year, m, 1),
                last_trading_day=dt.date(year, m, 3),
            )
        )
    return contracts
