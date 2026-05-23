from __future__ import annotations

from datetime import date
from typing import cast

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from mxm.moneymachine.calendars.service import TradingCalendarService
from mxm.moneymachine.execution.contract_bundles import (
    ContractBundle,
    TargetContractBundle,
)
from mxm.moneymachine.execution.executor import PerfectBacktestExecutor
from mxm.moneymachine.execution.orders import (
    OrderGenerationPolicy,
    OrderGenerator,
    OrderTimestampPolicy,
    OrderType,
)
from mxm.moneymachine.execution.price_accessors import ExecutionPriceAccessor
from mxm.moneymachine.execution.session_engine import SessionEngine
from mxm.moneymachine.utils.pandas_timestamps import ts_ns_to_pd_timestamp
from mxm.moneymachine.utils.timestamps import TSNSScalar, ts_ns_from_str
from mxm.refdata.api.ref_data_api import RefDataAPI  # type: ignore
from mxm.refdata.models.contracts.futures_contract import (
    FuturesContract,  # type: ignore
)

SESSION = np.datetime64("2026-03-10", "D")
PREVIOUS_SESSION = np.datetime64("2026-03-09", "D")
SESSION_OPEN_TS = ts_ns_from_str("2026-03-10T08:00:00.000000000Z")
SESSION_CLOSE_TS = ts_ns_from_str("2026-03-10T16:00:00.000000000Z")


class DummyRefDataAPI:
    def __init__(self, contracts: dict[str, FuturesContract]) -> None:
        self._contracts = contracts

    def get_contract_by_id(self, contract_id: str) -> FuturesContract:
        try:
            return self._contracts[contract_id]
        except KeyError as exc:
            raise ValueError(f"Unknown contract_id: {contract_id}") from exc


def _contract(*, product_id: str, last_trading_day: date) -> FuturesContract:
    return cast(
        FuturesContract,
        DummyContract(product_id=product_id, last_trading_day=last_trading_day),
    )


class DummyContract:
    def __init__(self, product_id: str, last_trading_day: date) -> None:
        self.product_id = product_id
        self.last_trading_day = last_trading_day


class DummyExecutionPriceAccessor(ExecutionPriceAccessor):
    def __init__(self, prices: dict[tuple[str, np.datetime64], float]) -> None:
        self._prices = prices
        self.calls: list[tuple[str, np.datetime64]] = []

    def get_execution_price(
        self,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        key = (contract_id, session.astype("datetime64[D]"))
        self.calls.append(key)
        return self._prices[key]


class DummyCalendar:
    def __init__(
        self,
        *,
        open_ts: TSNSScalar = SESSION_OPEN_TS,
        close_ts: TSNSScalar = SESSION_CLOSE_TS,
    ) -> None:
        self._open_ts = open_ts
        self._close_ts = close_ts

    def session_open(self, session: np.datetime64) -> pd.Timestamp:
        assert session.astype("datetime64[D]") == SESSION
        return ts_ns_to_pd_timestamp(self._open_ts)

    def session_close(self, session: np.datetime64) -> pd.Timestamp:
        assert session.astype("datetime64[D]") == SESSION
        return ts_ns_to_pd_timestamp(self._close_ts)


class DummyCalendarService:
    def __init__(self, mapping: dict[str, DummyCalendar]) -> None:
        self._mapping = mapping

    def calendar_for_product(self, product_id: str) -> DummyCalendar:
        try:
            return self._mapping[product_id]
        except KeyError as exc:
            raise ValueError(f"Unknown product_id {product_id!r}") from exc


def _make_engine(
    *,
    ref_data_api: DummyRefDataAPI,
    prices: dict[tuple[str, np.datetime64], float],
    default_min_block_size: int = 1,
    timestamp_policy: OrderTimestampPolicy = OrderTimestampPolicy.SESSION_OPEN,
    calendars_by_product: dict[str, DummyCalendar] | None = None,
) -> tuple[SessionEngine, DummyExecutionPriceAccessor]:
    accessor = DummyExecutionPriceAccessor(prices=prices)
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    if calendars_by_product is None:
        product_ids = {
            contract.product_id for contract in ref_data_api._contracts.values()
        }
        calendars_by_product = {
            product_id: DummyCalendar() for product_id in product_ids
        }

    calendar_service = DummyCalendarService(calendars_by_product)
    order_generator = OrderGenerator(
        policy=OrderGenerationPolicy(
            default_min_block_size=default_min_block_size,
            timestamp_policy=timestamp_policy,
        ),
        ref_data_api=cast(RefDataAPI, ref_data_api),
        calendar_service=cast(TradingCalendarService, calendar_service),
    )

    engine = SessionEngine(
        ref_data_api=cast(RefDataAPI, ref_data_api),
        order_generator=order_generator,
        executor=executor,
    )
    return engine, accessor


def test_run_session_happy_path_returns_full_session_result() -> None:
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
            "corn_may2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 5, 20),
            ),
        }
    )

    engine, accessor = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", SESSION): 101.5,
            ("corn_may2026", SESSION): 102.25,
        },
    )

    previous_realised_holdings = ContractBundle.from_dict(
        {
            "corn_mar2026": 2,
            "corn_may2026": -1,
        }
    )
    target_holdings = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 3.0,
            "corn_may2026": 1.0,
        }
    )

    result = engine.run_session(
        session=SESSION,
        previous_realised_holdings=previous_realised_holdings,
        target_holdings=target_holdings,
        previous_session=PREVIOUS_SESSION,
    )

    expected_initial = pd.Series(
        [2, -1],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="int64",
    )
    expected_target_trades = pd.Series(
        [1.0, 2.0],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="float64",
    )
    expected_implemented = pd.Series(
        [1, 2],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="int64",
    )
    expected_realised = pd.Series(
        [3, 1],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="int64",
    )

    assert result.previous_session == PREVIOUS_SESSION
    assert result.session == SESSION
    pdt.assert_series_equal(result.initial_holdings.quantities, expected_initial)
    pdt.assert_series_equal(result.target_trades.quantities, expected_target_trades)
    pdt.assert_series_equal(result.implemented_trades.quantities, expected_implemented)
    pdt.assert_series_equal(result.realised_holdings.quantities, expected_realised)

    assert len(result.orders) == 2
    assert [o.contract_id for o in result.orders] == ["corn_mar2026", "corn_may2026"]
    assert [o.quantity for o in result.orders] == [1, 2]
    assert all(o.order_type == OrderType.MARKET for o in result.orders)

    assert len(result.execution_result.order_executions) == 2
    assert accessor.calls == [
        ("corn_mar2026", SESSION),
        ("corn_may2026", SESSION),
    ]


def test_run_session_accepts_none_previous_session_for_first_step() -> None:
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, _ = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", SESSION): 101.5,
        },
    )

    result = engine.run_session(
        session=SESSION,
        previous_realised_holdings=ContractBundle.empty(),
        target_holdings=TargetContractBundle.from_dict({"corn_mar2026": 1.0}),
        previous_session=None,
    )

    assert result.previous_session is None
    assert result.session == SESSION


def test_run_session_accepts_session_day_labels() -> None:
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, accessor = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", SESSION): 101.5,
        },
    )

    result = engine.run_session(
        session=SESSION,
        previous_realised_holdings=ContractBundle.empty(),
        target_holdings=TargetContractBundle.from_dict({"corn_mar2026": 1.0}),
        previous_session=PREVIOUS_SESSION,
    )

    assert result.session == SESSION
    assert result.previous_session == PREVIOUS_SESSION
    assert accessor.calls == [("corn_mar2026", SESSION)]


def test_run_session_uses_order_generator_timestamp_for_order_and_fill_times() -> None:
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, _ = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", SESSION): 101.5,
        },
        calendars_by_product={
            "corn": DummyCalendar(open_ts=SESSION_OPEN_TS),
        },
    )

    result = engine.run_session(
        session=SESSION,
        previous_realised_holdings=ContractBundle.empty(),
        target_holdings=TargetContractBundle.from_dict({"corn_mar2026": 1.0}),
    )

    assert len(result.orders) == 1
    assert result.orders[0].created_at == SESSION_OPEN_TS

    assert len(result.execution_result.order_executions) == 1
    # SessionEngine does not provide submission_timestamp, so perfect executor
    # falls back to order.created_at.
    assert result.execution_result.order_executions[0].fill_timestamp == SESSION_OPEN_TS


def test_run_session_can_use_session_close_timestamp_policy() -> None:
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, _ = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", SESSION): 101.5,
        },
        timestamp_policy=OrderTimestampPolicy.SESSION_CLOSE,
        calendars_by_product={
            "corn": DummyCalendar(close_ts=SESSION_CLOSE_TS),
        },
    )

    result = engine.run_session(
        session=SESSION,
        previous_realised_holdings=ContractBundle.empty(),
        target_holdings=TargetContractBundle.from_dict({"corn_mar2026": 1.0}),
    )

    assert len(result.orders) == 1
    assert result.orders[0].created_at == SESSION_CLOSE_TS
    assert (
        result.execution_result.order_executions[0].fill_timestamp == SESSION_CLOSE_TS
    )


def test_run_session_respects_order_generation_rounding() -> None:
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, _ = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", SESSION): 101.5,
        },
    )

    previous_realised_holdings = ContractBundle.empty()
    target_holdings = TargetContractBundle.from_dict({"corn_mar2026": 0.6})

    result = engine.run_session(
        session=SESSION,
        previous_realised_holdings=previous_realised_holdings,
        target_holdings=target_holdings,
    )

    expected_target_trades = pd.Series(
        [0.6],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="float64",
    )
    expected_implemented = pd.Series(
        [1],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    expected_realised_holdings = pd.Series(
        [1],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.target_trades.quantities, expected_target_trades)
    pdt.assert_series_equal(result.implemented_trades.quantities, expected_implemented)
    pdt.assert_series_equal(
        result.realised_holdings.quantities, expected_realised_holdings
    )


def test_run_session_with_zero_implemented_trades_leaves_realised_holdings_unchanged() -> (
    None
):
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, accessor = _make_engine(
        ref_data_api=ref_data_api,
        prices={},
    )

    previous_realised_holdings = ContractBundle.from_dict({"corn_mar2026": 2})
    target_holdings = TargetContractBundle.from_dict({"corn_mar2026": 2.49})

    result = engine.run_session(
        session=SESSION,
        previous_realised_holdings=previous_realised_holdings,
        target_holdings=target_holdings,
    )

    expected_holdings = pd.Series(
        [2],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )

    assert result.orders == []
    assert result.execution_result.order_executions == []
    assert result.execution_result.realised_trades.is_empty()
    pdt.assert_series_equal(result.realised_holdings.quantities, expected_holdings)
    assert accessor.calls == []


def test_run_session_propagates_prepare_initial_holdings_failure() -> None:
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 3, 10),
            ),
        }
    )

    engine, _ = _make_engine(
        ref_data_api=ref_data_api,
        prices={},
    )

    previous_realised_holdings = ContractBundle.from_dict({"corn_mar2026": 1})
    target_holdings = TargetContractBundle.empty()

    with pytest.raises(ValueError, match="on or beyond last trading day"):
        engine.run_session(
            session=SESSION,
            previous_realised_holdings=previous_realised_holdings,
            target_holdings=target_holdings,
        )


def test_run_session_propagates_executor_failure() -> None:
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": _contract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, _ = _make_engine(
        ref_data_api=ref_data_api,
        prices={},
    )

    previous_realised_holdings = ContractBundle.empty()
    target_holdings = TargetContractBundle.from_dict({"corn_mar2026": 1.0})

    with pytest.raises(KeyError):
        engine.run_session(
            session=SESSION,
            previous_realised_holdings=previous_realised_holdings,
            target_holdings=target_holdings,
        )
