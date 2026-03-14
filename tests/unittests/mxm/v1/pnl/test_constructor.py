from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
import pytest

from mxm.v1.execution.contract_bundles import ContractBundle
from mxm.v1.execution.price_accessors import MarkPriceAccessor
from mxm.v1.fx.spot_fx_converter import SpotFXConverter
from mxm.v1.pnl.constructor import (
    _build_contract_pnl,
    _build_session_pnl,
    _bundle_quantity,
    _compute_contract_price_move_pnl,
    _compute_contract_trade_pnl,
    build_pnl_series,
)


@dataclass(frozen=True, slots=True)
class DummyContract:
    product_id: str
    contract_size: float
    currency: str


class DummyRefDataAPI:
    def __init__(self, mapping: dict[str, DummyContract]) -> None:
        self._mapping = mapping

    def get_contract_by_id(self, contract_id: str) -> DummyContract | None:
        return self._mapping.get(contract_id)


class DummyMarkPriceAccessor(MarkPriceAccessor):
    def __init__(self, prices: dict[tuple[str, pd.Timestamp], float]) -> None:
        self._prices = prices

    def get_mark_price(
        self,
        contract_id: str,
        session: pd.Timestamp,
    ) -> float:
        key = (contract_id, session)
        if key not in self._prices:
            raise ValueError(
                f"Missing mark price for contract_id={contract_id!r}, session={session!r}."
            )
        return float(self._prices[key])


class DummySpotFXConverter(SpotFXConverter):
    def get_fx_multiplier(
        self,
        *,
        from_currency: str,
        to_currency: str,
        timestamp: pd.Timestamp,
    ) -> float:
        if from_currency == to_currency:
            return 1.0
        raise NotImplementedError(
            "Cross-currency spot FX conversion is not yet implemented. "
            f"from_currency={from_currency!r}, "
            f"to_currency={to_currency!r}, "
            f"timestamp={timestamp!r}"
        )


@dataclass(frozen=True, slots=True)
class DummyExecutionResult:
    realised_trades: ContractBundle
    fill_prices: pd.Series


@dataclass(frozen=True, slots=True)
class DummySessionResult:
    previous_session: pd.Timestamp | None
    session: pd.Timestamp
    initial_holdings: ContractBundle
    execution_result: DummyExecutionResult


def _ts(value: str) -> pd.Timestamp:
    return pd.Timestamp(value)


def _fill_prices(mapping: dict[str, float]) -> pd.Series:
    series = pd.Series(mapping, dtype="float64")
    series.index = pd.Index(series.index, name="contract_id")
    return series.sort_index()


def _default_refdata(
    *,
    contract_size: float = 1.0,
    currency: str = "USD",
    contract_id: str = "corn_mar2026",
) -> DummyRefDataAPI:
    return DummyRefDataAPI(
        {
            contract_id: DummyContract(
                product_id="corn",
                contract_size=contract_size,
                currency=currency,
            )
        }
    )


def _default_mark_accessor(
    *,
    contract_id: str = "corn_mar2026",
    previous_mark: float = 100.0,
    current_mark: float = 105.0,
    previous_session: pd.Timestamp | None = None,
    session: pd.Timestamp | None = None,
) -> DummyMarkPriceAccessor:
    if previous_session is None:
        previous_session = _ts("2026-03-10T00:00:00Z")
    if session is None:
        session = _ts("2026-03-11T00:00:00Z")

    prices = {
        (contract_id, previous_session): previous_mark,
        (contract_id, session): current_mark,
    }
    return DummyMarkPriceAccessor(prices)


def test_bundle_quantity_returns_zero_for_missing_contract() -> None:
    bundle = ContractBundle.from_dict({"corn_mar2026": 3})

    result = _bundle_quantity(bundle=bundle, contract_id="corn_may2026")

    assert result == 0


def test_price_move_pnl_first_session_is_zero() -> None:
    contract_id = "corn_mar2026"
    session = _ts("2026-03-11T00:00:00Z")
    accessor = DummyMarkPriceAccessor({(contract_id, session): 105.0})

    result = _compute_contract_price_move_pnl(
        contract_id=contract_id,
        previous_session=None,
        session=session,
        initial_quantity=3,
        contract_multiplier=1.0,
        fx_multiplier=1.0,
        mark_price_accessor=accessor,
    )

    assert result == 0.0


def test_price_move_pnl_for_carried_long_position() -> None:
    contract_id = "corn_mar2026"
    previous_session = _ts("2026-03-10T00:00:00Z")
    session = _ts("2026-03-11T00:00:00Z")
    accessor = _default_mark_accessor(
        contract_id=contract_id,
        previous_mark=100.0,
        current_mark=105.0,
        previous_session=previous_session,
        session=session,
    )

    result = _compute_contract_price_move_pnl(
        contract_id=contract_id,
        previous_session=previous_session,
        session=session,
        initial_quantity=3,
        contract_multiplier=1.0,
        fx_multiplier=1.0,
        mark_price_accessor=accessor,
    )

    assert result == 15.0


def test_price_move_pnl_for_carried_short_position() -> None:
    contract_id = "corn_mar2026"
    previous_session = _ts("2026-03-10T00:00:00Z")
    session = _ts("2026-03-11T00:00:00Z")
    accessor = _default_mark_accessor(
        contract_id=contract_id,
        previous_mark=100.0,
        current_mark=95.0,
        previous_session=previous_session,
        session=session,
    )

    result = _compute_contract_price_move_pnl(
        contract_id=contract_id,
        previous_session=previous_session,
        session=session,
        initial_quantity=-3,
        contract_multiplier=1.0,
        fx_multiplier=1.0,
        mark_price_accessor=accessor,
    )

    assert result == 15.0


def test_trade_pnl_for_buy_below_mark_is_positive() -> None:
    contract_id = "corn_mar2026"
    session = _ts("2026-03-11T00:00:00Z")
    accessor = DummyMarkPriceAccessor({(contract_id, session): 105.0})

    execution_result = DummyExecutionResult(
        realised_trades=ContractBundle.from_dict({contract_id: 2}),
        fill_prices=_fill_prices({contract_id: 103.0}),
    )

    result = _compute_contract_trade_pnl(
        contract_id=contract_id,
        session=session,
        trade_quantity=2,
        contract_multiplier=1.0,
        fx_multiplier=1.0,
        execution_result=execution_result,
        mark_price_accessor=accessor,
    )

    assert result == 4.0


def test_trade_pnl_for_sell_above_mark_is_positive() -> None:
    contract_id = "corn_mar2026"
    session = _ts("2026-03-11T00:00:00Z")
    accessor = DummyMarkPriceAccessor({(contract_id, session): 105.0})

    execution_result = DummyExecutionResult(
        realised_trades=ContractBundle.from_dict({contract_id: -4}),
        fill_prices=_fill_prices({contract_id: 106.0}),
    )

    result = _compute_contract_trade_pnl(
        contract_id=contract_id,
        session=session,
        trade_quantity=-4,
        contract_multiplier=1.0,
        fx_multiplier=1.0,
        execution_result=execution_result,
        mark_price_accessor=accessor,
    )

    assert result == 4.0


def test_build_contract_pnl_combines_price_move_and_trade_components() -> None:
    contract_id = "corn_mar2026"
    previous_session = _ts("2026-03-10T00:00:00Z")
    session = _ts("2026-03-11T00:00:00Z")

    session_result = DummySessionResult(
        previous_session=previous_session,
        session=session,
        initial_holdings=ContractBundle.from_dict({contract_id: 4}),
        execution_result=DummyExecutionResult(
            realised_trades=ContractBundle.from_dict({contract_id: -4}),
            fill_prices=_fill_prices({contract_id: 104.0}),
        ),
    )

    mark_accessor = _default_mark_accessor(
        contract_id=contract_id,
        previous_mark=100.0,
        current_mark=105.0,
        previous_session=previous_session,
        session=session,
    )

    result = _build_contract_pnl(
        contract_id=contract_id,
        session_result=session_result,
        mark_price_accessor=mark_accessor,
        spot_fx_converter=DummySpotFXConverter(),
        ref_data_api=_default_refdata(contract_id=contract_id),
        target_currency="USD",
    )

    assert result.contract_id == contract_id
    assert result.price_move_pnl == 20.0
    assert result.trade_pnl == -4.0
    assert result.total_pnl == 16.0


def test_build_contract_pnl_applies_contract_multiplier() -> None:
    contract_id = "corn_mar2026"
    previous_session = _ts("2026-03-10T00:00:00Z")
    session = _ts("2026-03-11T00:00:00Z")

    session_result = DummySessionResult(
        previous_session=previous_session,
        session=session,
        initial_holdings=ContractBundle.from_dict({contract_id: 2}),
        execution_result=DummyExecutionResult(
            realised_trades=ContractBundle.from_dict({contract_id: -1}),
            fill_prices=_fill_prices({contract_id: 103.0}),
        ),
    )

    mark_accessor = _default_mark_accessor(
        contract_id=contract_id,
        previous_mark=100.0,
        current_mark=105.0,
        previous_session=previous_session,
        session=session,
    )

    result = _build_contract_pnl(
        contract_id=contract_id,
        session_result=session_result,
        mark_price_accessor=mark_accessor,
        spot_fx_converter=DummySpotFXConverter(),
        ref_data_api=_default_refdata(contract_size=10.0, contract_id=contract_id),
        target_currency="USD",
    )

    assert result.price_move_pnl == 100.0
    assert result.trade_pnl == -20.0
    assert result.total_pnl == 80.0


def test_build_session_pnl_aggregates_contract_rows() -> None:
    previous_session = _ts("2026-03-10T00:00:00Z")
    session = _ts("2026-03-11T00:00:00Z")

    session_result = DummySessionResult(
        previous_session=previous_session,
        session=session,
        initial_holdings=ContractBundle.from_dict(
            {
                "corn_mar2026": 3,
                "wheat_mar2026": -2,
            }
        ),
        execution_result=DummyExecutionResult(
            realised_trades=ContractBundle.from_dict(
                {
                    "corn_mar2026": -1,
                    "wheat_mar2026": 2,
                }
            ),
            fill_prices=_fill_prices(
                {
                    "corn_mar2026": 104.0,
                    "wheat_mar2026": 96.0,
                }
            ),
        ),
    )

    mark_accessor = DummyMarkPriceAccessor(
        {
            ("corn_mar2026", previous_session): 100.0,
            ("corn_mar2026", session): 105.0,
            ("wheat_mar2026", previous_session): 100.0,
            ("wheat_mar2026", session): 95.0,
        }
    )

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                contract_size=1.0,
                currency="USD",
            ),
            "wheat_mar2026": DummyContract(
                product_id="wheat",
                contract_size=1.0,
                currency="USD",
            ),
        }
    )

    result = _build_session_pnl(
        session_result=session_result,
        mark_price_accessor=mark_accessor,
        spot_fx_converter=DummySpotFXConverter(),
        ref_data_api=ref_data_api,
        target_currency="USD",
    )

    assert result.previous_session == previous_session
    assert result.session == session
    assert len(result.contract_pnls) == 2

    # corn: 3 * (105 - 100) = +15 ; -1 * (105 - 104) = -1 ; total +14
    # wheat: -2 * (95 - 100) = +10 ; +2 * (95 - 96) = -2 ; total +8
    assert result.price_move_pnl == 25.0
    assert result.trade_pnl == -3.0
    assert result.total_pnl == 22.0


def test_build_pnl_series_builds_ordered_series() -> None:
    session_1 = _ts("2026-03-10T00:00:00Z")
    session_2 = _ts("2026-03-11T00:00:00Z")
    contract_id = "corn_mar2026"

    session_results = [
        DummySessionResult(
            previous_session=None,
            session=session_1,
            initial_holdings=ContractBundle.empty(),
            execution_result=DummyExecutionResult(
                realised_trades=ContractBundle.from_dict({contract_id: 1}),
                fill_prices=_fill_prices({contract_id: 100.0}),
            ),
        ),
        DummySessionResult(
            previous_session=session_1,
            session=session_2,
            initial_holdings=ContractBundle.from_dict({contract_id: 1}),
            execution_result=DummyExecutionResult(
                realised_trades=ContractBundle.empty(),
                fill_prices=_fill_prices({}),
            ),
        ),
    ]

    mark_accessor = DummyMarkPriceAccessor(
        {
            (contract_id, session_1): 100.0,
            (contract_id, session_2): 105.0,
        }
    )

    pnl_series = build_pnl_series(
        session_results=session_results,
        mark_price_accessor=mark_accessor,
        spot_fx_converter=DummySpotFXConverter(),
        ref_data_api=_default_refdata(contract_id=contract_id),
        target_currency="USD",
    )

    assert len(pnl_series) == 2
    assert pnl_series.session_pnls[0].session == session_1
    assert pnl_series.session_pnls[1].session == session_2

    df = pnl_series.to_cumulative_dataframe()
    assert list(df["session"]) == [session_1, session_2]
    assert list(df["cumulative_total_pnl"]) == [0.0, 5.0]


def test_build_contract_pnl_raises_for_missing_fill_price() -> None:
    contract_id = "corn_mar2026"
    previous_session = _ts("2026-03-10T00:00:00Z")
    session = _ts("2026-03-11T00:00:00Z")

    session_result = DummySessionResult(
        previous_session=previous_session,
        session=session,
        initial_holdings=ContractBundle.empty(),
        execution_result=DummyExecutionResult(
            realised_trades=ContractBundle.from_dict({contract_id: 2}),
            fill_prices=_fill_prices({}),
        ),
    )

    mark_accessor = DummyMarkPriceAccessor({(contract_id, session): 105.0})

    with pytest.raises(ValueError, match="Missing fill price"):
        _build_contract_pnl(
            contract_id=contract_id,
            session_result=session_result,
            mark_price_accessor=mark_accessor,
            spot_fx_converter=DummySpotFXConverter(),
            ref_data_api=_default_refdata(contract_id=contract_id),
            target_currency="USD",
        )


def test_build_contract_pnl_raises_for_cross_currency_case() -> None:
    contract_id = "corn_mar2026"
    session = _ts("2026-03-11T00:00:00Z")

    session_result = DummySessionResult(
        previous_session=None,
        session=session,
        initial_holdings=ContractBundle.empty(),
        execution_result=DummyExecutionResult(
            realised_trades=ContractBundle.from_dict({contract_id: 1}),
            fill_prices=_fill_prices({contract_id: 100.0}),
        ),
    )

    mark_accessor = DummyMarkPriceAccessor({(contract_id, session): 100.0})

    with pytest.raises(NotImplementedError, match="Cross-currency"):
        _build_contract_pnl(
            contract_id=contract_id,
            session_result=session_result,
            mark_price_accessor=mark_accessor,
            spot_fx_converter=DummySpotFXConverter(),
            ref_data_api=_default_refdata(
                contract_id=contract_id,
                currency="EUR",
            ),
            target_currency="USD",
        )
