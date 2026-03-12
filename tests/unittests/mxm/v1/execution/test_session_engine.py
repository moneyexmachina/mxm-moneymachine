from __future__ import annotations

from datetime import date

import pandas as pd
import pandas.testing as pdt
import pytest

from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle
from mxm.v1.execution.executor import ExecutionPriceAccessor, PerfectBacktestExecutor
from mxm.v1.execution.orders import OrderGenerationPolicy, OrderGenerator, OrderType
from mxm.v1.execution.session_engine import SessionEngine
from mxm.v1.utils.time_utils import to_utc_ts


class DummyContract:
    def __init__(self, product_id: str, last_trading_day: date) -> None:
        self.product_id = product_id
        self.last_trading_day = last_trading_day


class DummyRefDataAPI:
    def __init__(self, contracts: dict[str, DummyContract]) -> None:
        self._contracts = contracts

    def get_contract_by_id(self, contract_id: str) -> DummyContract | None:
        return self._contracts.get(contract_id)


class DummyExecutionPriceAccessor(ExecutionPriceAccessor):
    def __init__(self, prices: dict[tuple[str, pd.Timestamp], float]) -> None:
        self._prices = prices
        self.calls: list[tuple[str, pd.Timestamp]] = []

    def get_execution_price(
        self,
        contract_id: str,
        submission_timestamp: pd.Timestamp,
    ) -> float:
        key = (contract_id, submission_timestamp)
        self.calls.append(key)
        return self._prices[key]


def _make_engine(
    *,
    ref_data_api: DummyRefDataAPI,
    prices: dict[tuple[str, pd.Timestamp], float],
    default_min_block_size: int = 1,
) -> tuple[SessionEngine, DummyExecutionPriceAccessor]:
    accessor = DummyExecutionPriceAccessor(prices=prices)
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)
    order_generator = OrderGenerator(
        policy=OrderGenerationPolicy(default_min_block_size=default_min_block_size)
    )
    engine = SessionEngine(
        ref_data_api=ref_data_api,
        order_generator=order_generator,
        executor=executor,
    )
    return engine, accessor


def test_run_session_happy_path_returns_full_session_result() -> None:
    session_ts = to_utc_ts("2026-03-10T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
            "corn_may2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 5, 20),
            ),
        }
    )

    engine, accessor = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", session_ts): 101.5,
            ("corn_may2026", session_ts): 102.25,
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
        session=session_ts,
        previous_realised_holdings=previous_realised_holdings,
        target_holdings=target_holdings,
        previous_session="2026-03-09T00:00:00Z",
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

    assert result.previous_session == to_utc_ts("2026-03-09T00:00:00Z")
    assert result.session == session_ts
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
        ("corn_mar2026", session_ts),
        ("corn_may2026", session_ts),
    ]


def test_run_session_accepts_none_previous_session_for_first_step() -> None:
    session_ts = to_utc_ts("2026-03-10T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, _ = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", session_ts): 101.5,
        },
    )

    result = engine.run_session(
        session=session_ts,
        previous_realised_holdings=ContractBundle.empty(),
        target_holdings=TargetContractBundle.from_dict({"corn_mar2026": 1.0}),
        previous_session=None,
    )

    assert result.previous_session is None
    assert result.session == session_ts


def test_run_session_normalises_session_timestamps_to_utc() -> None:
    session_str = "2026-03-10T00:00:00Z"
    session_ts = to_utc_ts(session_str)

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, accessor = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", session_ts): 101.5,
        },
    )

    result = engine.run_session(
        session=session_str,
        previous_realised_holdings=ContractBundle.empty(),
        target_holdings=TargetContractBundle.from_dict({"corn_mar2026": 1.0}),
        previous_session="2026-03-09T00:00:00Z",
    )

    assert result.session == session_ts
    assert result.previous_session == to_utc_ts("2026-03-09T00:00:00Z")
    assert accessor.calls == [("corn_mar2026", session_ts)]


def test_run_session_propagates_session_timestamp_to_order_and_fill_times() -> None:
    session_ts = to_utc_ts("2026-03-10T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, _ = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", session_ts): 101.5,
        },
    )

    result = engine.run_session(
        session=session_ts,
        previous_realised_holdings=ContractBundle.empty(),
        target_holdings=TargetContractBundle.from_dict({"corn_mar2026": 1.0}),
    )

    assert len(result.orders) == 1
    assert result.orders[0].created_at == session_ts

    assert len(result.execution_result.order_executions) == 1
    assert result.execution_result.order_executions[0].fill_timestamp == session_ts


def test_run_session_respects_order_generation_rounding() -> None:
    session_ts = to_utc_ts("2026-03-10T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    engine, _ = _make_engine(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", session_ts): 101.5,
        },
    )

    previous_realised_holdings = ContractBundle.empty()
    target_holdings = TargetContractBundle.from_dict({"corn_mar2026": 0.6})

    result = engine.run_session(
        session=session_ts,
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
    session_ts = to_utc_ts("2026-03-10T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
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
        session=session_ts,
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
    session_ts = to_utc_ts("2026-03-10T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
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
            session=session_ts,
            previous_realised_holdings=previous_realised_holdings,
            target_holdings=target_holdings,
        )


def test_run_session_propagates_executor_failure() -> None:
    session_ts = to_utc_ts("2026-03-10T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
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
            session=session_ts,
            previous_realised_holdings=previous_realised_holdings,
            target_holdings=target_holdings,
        )
