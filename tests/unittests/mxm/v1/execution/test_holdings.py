import datetime as dt
from typing import cast

import pandas as pd
import pandas.testing as pdt
import pytest

from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.v1.execution.contract_bundles import ContractBundle
from mxm.v1.execution.holdings import (
    apply_realised_trades,
    prepare_initial_holdings,
)


class DummyContract:
    def __init__(self, last_trading_day: dt.date | None) -> None:
        self.last_trading_day = last_trading_day


class DummyRefDataAPI:
    def __init__(self, contracts: dict[str, DummyContract]) -> None:
        self._contracts = contracts

    def get_contract_by_id(self, contract_id: str) -> DummyContract | None:
        return self._contracts.get(contract_id)


def test_prepare_initial_holdings_returns_empty_bundle_for_empty_realised_holdings() -> (
    None
):
    realised_holdings = ContractBundle.empty()
    ref_data_api = DummyRefDataAPI({})

    result = prepare_initial_holdings(
        realised_holdings=realised_holdings,
        session=pd.Timestamp("2026-03-10").to_datetime64(),
        ref_data_api=cast(RefDataAPI, ref_data_api),
    )

    expected = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))

    assert result.is_empty()
    pdt.assert_series_equal(result.quantities, expected)


def test_prepare_initial_holdings_returns_same_bundle_when_all_held_contracts_are_valid() -> (
    None
):
    realised_holdings = ContractBundle.from_dict(
        {
            "corn_mar2026": 2,
            "corn_may2026": -1,
        }
    )

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(last_trading_day=dt.date(2026, 3, 20)),
            "corn_may2026": DummyContract(last_trading_day=dt.date(2026, 5, 20)),
        }
    )

    result = prepare_initial_holdings(
        realised_holdings=realised_holdings,
        session=pd.Timestamp("2026-03-10").to_datetime64(),
        ref_data_api=cast(RefDataAPI, ref_data_api),
    )

    expected = pd.Series(
        [2, -1],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_prepare_initial_holdings_raises_for_missing_contract_in_refdata() -> None:
    realised_holdings = ContractBundle.from_dict({"corn_mar2026": 1})
    ref_data_api = DummyRefDataAPI({})

    with pytest.raises(ValueError, match="could not resolve held contract"):
        prepare_initial_holdings(
            realised_holdings=realised_holdings,
            session=pd.Timestamp("2026-03-10").to_datetime64(),
            ref_data_api=cast(RefDataAPI, ref_data_api),
        )


def test_prepare_initial_holdings_raises_when_held_contract_is_on_last_trading_day() -> (
    None
):
    realised_holdings = ContractBundle.from_dict({"corn_mar2026": 1})
    ref_data_api = DummyRefDataAPI(
        {"corn_mar2026": DummyContract(last_trading_day=dt.date(2026, 3, 10))}
    )

    with pytest.raises(ValueError, match="on or beyond last trading day"):
        prepare_initial_holdings(
            realised_holdings=realised_holdings,
            session=pd.Timestamp("2026-03-10").to_datetime64(),
            ref_data_api=cast(RefDataAPI, ref_data_api),
        )


def test_prepare_initial_holdings_raises_when_held_contract_is_after_last_trading_day() -> (
    None
):
    realised_holdings = ContractBundle.from_dict({"corn_mar2026": 1})
    ref_data_api = DummyRefDataAPI(
        {"corn_mar2026": DummyContract(last_trading_day=dt.date(2026, 3, 9))}
    )

    with pytest.raises(ValueError, match="on or beyond last trading day"):
        prepare_initial_holdings(
            realised_holdings=realised_holdings,
            session=pd.Timestamp("2026-03-10").to_datetime64(),
            ref_data_api=cast(RefDataAPI, ref_data_api),
        )


def test_prepare_initial_holdings_ignores_unheld_contracts_in_refdata() -> None:
    realised_holdings = ContractBundle.from_dict({"corn_mar2026": 1})
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(last_trading_day=dt.date(2026, 3, 20)),
            "corn_may2026": DummyContract(last_trading_day=None),
        }
    )

    result = prepare_initial_holdings(
        realised_holdings=realised_holdings,
        session=pd.Timestamp("2026-03-10").to_datetime64(),
        ref_data_api=cast(RefDataAPI, ref_data_api),
    )

    expected = pd.Series(
        [1],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_apply_realised_trades_adds_overlapping_contracts_correctly() -> None:
    initial_holdings = ContractBundle.from_dict(
        {
            "corn_mar2026": 2,
            "corn_may2026": -1,
        }
    )
    realised_trades = ContractBundle.from_dict(
        {
            "corn_mar2026": -1,
            "corn_may2026": 3,
        }
    )

    result = apply_realised_trades(
        initial_holdings=initial_holdings,
        realised_trades=realised_trades,
    )

    expected = pd.Series(
        [1, 2],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_apply_realised_trades_adds_disjoint_contracts_correctly() -> None:
    initial_holdings = ContractBundle.from_dict({"corn_mar2026": 2})
    realised_trades = ContractBundle.from_dict({"corn_may2026": 3})

    result = apply_realised_trades(
        initial_holdings=initial_holdings,
        realised_trades=realised_trades,
    )

    expected = pd.Series(
        [2, 3],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_apply_realised_trades_prunes_zero_resulting_positions() -> None:
    initial_holdings = ContractBundle.from_dict({"corn_mar2026": 2})
    realised_trades = ContractBundle.from_dict({"corn_mar2026": -2})

    result = apply_realised_trades(
        initial_holdings=initial_holdings,
        realised_trades=realised_trades,
    )

    expected = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))

    assert result.is_empty()
    pdt.assert_series_equal(result.quantities, expected)


def test_apply_realised_trades_with_empty_initial_holdings_returns_realised_trades() -> (
    None
):
    initial_holdings = ContractBundle.empty()
    realised_trades = ContractBundle.from_dict({"corn_mar2026": 3})

    result = apply_realised_trades(
        initial_holdings=initial_holdings,
        realised_trades=realised_trades,
    )

    expected = pd.Series(
        [3],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_apply_realised_trades_with_empty_realised_trades_returns_initial_holdings() -> (
    None
):
    initial_holdings = ContractBundle.from_dict({"corn_mar2026": 3})
    realised_trades = ContractBundle.empty()

    result = apply_realised_trades(
        initial_holdings=initial_holdings,
        realised_trades=realised_trades,
    )

    expected = pd.Series(
        [3],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_apply_realised_trades_with_both_empty_returns_empty_bundle() -> None:
    initial_holdings = ContractBundle.empty()
    realised_trades = ContractBundle.empty()

    result = apply_realised_trades(
        initial_holdings=initial_holdings,
        realised_trades=realised_trades,
    )

    expected = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))

    assert result.is_empty()
    pdt.assert_series_equal(result.quantities, expected)
