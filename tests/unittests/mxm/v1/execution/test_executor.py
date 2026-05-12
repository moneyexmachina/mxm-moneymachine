from __future__ import annotations

from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from mxm.v1.execution.contract_bundles import ContractBundle
from mxm.v1.execution.executor import (
    ExecutionResult,
    ExecutionStatus,
    OrderExecution,
    OrderSubmission,
    PerfectBacktestExecutor,
)
from mxm.v1.execution.orders import Order, OrderType
from mxm.v1.execution.price_accessors import ExecutionPriceAccessor
from mxm.v1.utils.time_utils import to_utc_ts

SESSION = np.datetime64("2026-03-12", "D")
CREATED_AT = to_utc_ts(datetime(2026, 3, 12, 10, 0, 0, tzinfo=UTC))
SUBMISSION_TS = to_utc_ts(datetime(2026, 3, 12, 16, 0, 0, tzinfo=UTC))


class DummyExecutionPriceAccessor(ExecutionPriceAccessor):
    def __init__(self, prices: dict[tuple[str, np.datetime64], float]) -> None:
        self._prices = prices
        self.calls: list[tuple[str, np.datetime64]] = []

    def get_execution_price(
        self,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        key = (contract_id, np.datetime64(session, "D"))
        self.calls.append(key)
        return self._prices[key]


def _make_order(
    *,
    contract_id: str,
    quantity: int,
    created_at: pd.Timestamp = CREATED_AT,
) -> Order:
    return Order(
        contract_id=contract_id,
        quantity=quantity,
        order_type=OrderType.MARKET,
        created_at=created_at,
    )


def test_order_submission_normalises_session_and_submission_timestamp() -> None:
    submission = OrderSubmission(
        orders=[_make_order(contract_id="corn_mar2026", quantity=1)],
        session="2026-03-12",
        submission_timestamp="2026-03-12T16:00:00Z",
    )

    assert submission.session == np.datetime64("2026-03-12", "D")
    assert submission.submission_timestamp == to_utc_ts("2026-03-12T16:00:00Z")


def test_order_submission_accepts_optional_submission_timestamp_none() -> None:
    submission = OrderSubmission(
        orders=[_make_order(contract_id="corn_mar2026", quantity=1)],
        session=SESSION,
        submission_timestamp=None,
    )

    assert submission.session == SESSION
    assert submission.submission_timestamp is None


def test_order_submission_accepts_orders_unchanged() -> None:
    order = _make_order(contract_id="corn_mar2026", quantity=1)

    submission = OrderSubmission(
        orders=[order],
        session=SESSION,
        submission_timestamp=SUBMISSION_TS,
    )

    assert submission.orders == [order]


def test_order_execution_rejects_zero_filled_quantity() -> None:
    order = _make_order(contract_id="corn_mar2026", quantity=1)

    with pytest.raises(ValueError, match="must be non-zero"):
        OrderExecution(
            order=order,
            status=ExecutionStatus.FILLED,
            filled_quantity=0,
            fill_price=101.5,
            fill_timestamp=SUBMISSION_TS,
        )


def test_order_execution_normalises_fill_timestamp_to_utc() -> None:
    order = _make_order(contract_id="corn_mar2026", quantity=1)

    execution = OrderExecution(
        order=order,
        status=ExecutionStatus.FILLED,
        filled_quantity=1,
        fill_price=101.5,
        fill_timestamp="2026-03-12T16:00:00Z",
    )

    assert execution.fill_timestamp == to_utc_ts("2026-03-12T16:00:00Z")


def test_execution_result_accepts_valid_fill_prices() -> None:
    fill_prices = pd.Series(
        [101.5, 102.25],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="float64",
    )

    result = ExecutionResult(
        realised_trades=ContractBundle.from_dict(
            {"corn_mar2026": 1, "corn_may2026": -2}
        ),
        fill_prices=fill_prices,
        order_executions=[],
    )

    pdt.assert_series_equal(result.fill_prices, fill_prices)


def test_execution_result_rejects_multi_level_fill_price_index() -> None:
    fill_prices = pd.Series(
        [101.5],
        index=pd.MultiIndex.from_tuples(
            [("corn_mar2026", pd.Timestamp("2026-03-12T00:00:00Z"))],
            names=["contract_id", "trading_date"],
        ),
        dtype="float64",
    )

    with pytest.raises(ValueError, match="single-level index"):
        ExecutionResult(
            realised_trades=ContractBundle.from_dict({"corn_mar2026": 1}),
            fill_prices=fill_prices,
            order_executions=[],
        )


def test_execution_result_rejects_duplicate_contract_ids() -> None:
    fill_prices = pd.Series(
        [101.5, 102.25],
        index=pd.Index(["corn_mar2026", "corn_mar2026"], name="contract_id"),
        dtype="float64",
    )

    with pytest.raises(ValueError, match="duplicate"):
        ExecutionResult(
            realised_trades=ContractBundle.from_dict({"corn_mar2026": 1}),
            fill_prices=fill_prices,
            order_executions=[],
        )


def test_execution_result_rejects_missing_fill_prices() -> None:
    fill_prices = pd.Series(
        [None],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="float64",
    )

    with pytest.raises(ValueError, match="must not contain missing values"):
        ExecutionResult(
            realised_trades=ContractBundle.from_dict({"corn_mar2026": 1}),
            fill_prices=fill_prices,
            order_executions=[],
        )


def test_execution_result_rejects_non_numeric_fill_prices() -> None:
    fill_prices = pd.Series(
        ["bad"],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="object",
    )

    with pytest.raises(TypeError, match="must be numeric"):
        ExecutionResult(
            realised_trades=ContractBundle.from_dict({"corn_mar2026": 1}),
            fill_prices=fill_prices,
            order_executions=[],
        )


def test_perfect_executor_returns_empty_result_for_empty_submission() -> None:
    accessor = DummyExecutionPriceAccessor(prices={})
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    submission = OrderSubmission(
        orders=[],
        session=SESSION,
        submission_timestamp=SUBMISSION_TS,
    )

    result = executor.execute_orders(submission)

    expected_realised = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))
    expected_fill_prices = pd.Series(
        dtype="float64", index=pd.Index([], name="contract_id")
    )

    assert result.order_executions == []
    pdt.assert_series_equal(result.realised_trades.quantities, expected_realised)
    pdt.assert_series_equal(result.fill_prices, expected_fill_prices)
    assert accessor.calls == []


def test_perfect_executor_fills_single_order_completely() -> None:
    accessor = DummyExecutionPriceAccessor(
        prices={
            ("corn_mar2026", SESSION): 101.5,
        }
    )
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    order = _make_order(contract_id="corn_mar2026", quantity=3)
    submission = OrderSubmission(
        orders=[order],
        session=SESSION,
        submission_timestamp=SUBMISSION_TS,
    )

    result = executor.execute_orders(submission)

    expected_realised = pd.Series(
        [3],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    expected_fill_prices = pd.Series(
        [101.5],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(result.realised_trades.quantities, expected_realised)
    pdt.assert_series_equal(result.fill_prices, expected_fill_prices)

    assert len(result.order_executions) == 1
    execution = result.order_executions[0]
    assert execution.order == order
    assert execution.status == ExecutionStatus.FILLED
    assert execution.filled_quantity == 3
    assert execution.fill_price == 101.5
    assert execution.fill_timestamp == SUBMISSION_TS


def test_perfect_executor_uses_accessor_prices() -> None:
    accessor = DummyExecutionPriceAccessor(
        prices={
            ("corn_mar2026", SESSION): 101.5,
            ("corn_may2026", SESSION): 102.25,
        }
    )
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    submission = OrderSubmission(
        orders=[
            _make_order(contract_id="corn_mar2026", quantity=1),
            _make_order(contract_id="corn_may2026", quantity=-2),
        ],
        session=SESSION,
        submission_timestamp=SUBMISSION_TS,
    )

    result = executor.execute_orders(submission)

    expected_fill_prices = pd.Series(
        [101.5, 102.25],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(result.fill_prices, expected_fill_prices)


def test_perfect_executor_sets_fill_timestamp_to_submission_timestamp_when_present() -> (
    None
):
    accessor = DummyExecutionPriceAccessor(prices={("corn_mar2026", SESSION): 101.5})
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    submission = OrderSubmission(
        orders=[_make_order(contract_id="corn_mar2026", quantity=1)],
        session=SESSION,
        submission_timestamp="2026-03-12T16:00:00Z",
    )

    result = executor.execute_orders(submission)

    assert result.order_executions[0].fill_timestamp == to_utc_ts(
        "2026-03-12T16:00:00Z"
    )


def test_perfect_executor_falls_back_to_order_created_at_when_submission_timestamp_missing() -> (
    None
):
    order = _make_order(
        contract_id="corn_mar2026",
        quantity=1,
        created_at=to_utc_ts("2026-03-12T10:15:00Z"),
    )
    accessor = DummyExecutionPriceAccessor(prices={("corn_mar2026", SESSION): 101.5})
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    submission = OrderSubmission(
        orders=[order],
        session=SESSION,
        submission_timestamp=None,
    )

    result = executor.execute_orders(submission)

    assert result.order_executions[0].fill_timestamp == to_utc_ts(
        "2026-03-12T10:15:00Z"
    )


def test_perfect_executor_aggregates_realised_trades_by_contract() -> None:
    accessor = DummyExecutionPriceAccessor(
        prices={
            ("corn_mar2026", SESSION): 101.5,
            ("corn_may2026", SESSION): 102.25,
        }
    )
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    submission = OrderSubmission(
        orders=[
            _make_order(contract_id="corn_mar2026", quantity=2),
            _make_order(contract_id="corn_may2026", quantity=-1),
        ],
        session=SESSION,
        submission_timestamp=SUBMISSION_TS,
    )

    result = executor.execute_orders(submission)

    expected_realised = pd.Series(
        [2, -1],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.realised_trades.quantities, expected_realised)


def test_perfect_executor_queries_accessor_with_session_label() -> None:
    accessor = DummyExecutionPriceAccessor(prices={("corn_mar2026", SESSION): 101.5})
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    submission = OrderSubmission(
        orders=[_make_order(contract_id="corn_mar2026", quantity=1)],
        session="2026-03-12",
        submission_timestamp="2026-03-12T16:00:00Z",
    )

    executor.execute_orders(submission)

    assert accessor.calls == [("corn_mar2026", np.datetime64("2026-03-12", "D"))]


def test_perfect_executor_all_order_executions_have_filled_status() -> None:
    accessor = DummyExecutionPriceAccessor(
        prices={
            ("corn_mar2026", SESSION): 101.5,
            ("corn_may2026", SESSION): 102.25,
        }
    )
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    submission = OrderSubmission(
        orders=[
            _make_order(contract_id="corn_mar2026", quantity=1),
            _make_order(contract_id="corn_may2026", quantity=-2),
        ],
        session=SESSION,
        submission_timestamp=SUBMISSION_TS,
    )

    result = executor.execute_orders(submission)

    assert all(
        execution.status == ExecutionStatus.FILLED
        for execution in result.order_executions
    )


def test_perfect_executor_rejects_same_contract_multiple_orders_in_one_submission() -> (
    None
):
    accessor = DummyExecutionPriceAccessor(prices={("corn_mar2026", SESSION): 101.5})
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)

    submission = OrderSubmission(
        orders=[
            _make_order(contract_id="corn_mar2026", quantity=1),
            _make_order(contract_id="corn_mar2026", quantity=-2),
        ],
        session=SESSION,
        submission_timestamp=SUBMISSION_TS,
    )

    with pytest.raises(ValueError, match="same contract_id"):
        executor.execute_orders(submission)
