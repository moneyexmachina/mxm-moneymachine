from __future__ import annotations

from datetime import date

import pandas as pd
import pandas.testing as pdt
import pytest

from mxm.v1.execution.backtester import Backtester, BacktestResult
from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle
from mxm.v1.execution.executor import ExecutionPriceAccessor, PerfectBacktestExecutor
from mxm.v1.execution.orders import OrderGenerationPolicy, OrderGenerator
from mxm.v1.execution.session_engine import SessionEngine, SessionResult
from mxm.v1.synthetic_assets.target_holdings import TargetHoldings
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


def _make_backtester(
    *,
    ref_data_api: DummyRefDataAPI,
    prices: dict[tuple[str, pd.Timestamp], float],
    default_min_block_size: int = 1,
) -> tuple[Backtester, DummyExecutionPriceAccessor]:
    accessor = DummyExecutionPriceAccessor(prices=prices)
    executor = PerfectBacktestExecutor(execution_price_accessor=accessor)
    order_generator = OrderGenerator(
        policy=OrderGenerationPolicy(default_min_block_size=default_min_block_size)
    )
    session_engine = SessionEngine(
        ref_data_api=ref_data_api,
        order_generator=order_generator,
        executor=executor,
    )
    backtester = Backtester(session_engine=session_engine)
    return backtester, accessor


def _make_target_holdings(
    rows: list[tuple[pd.Timestamp, str, float]],
    *,
    asset_id: str = "asset_1",
    canonical_id: str = "asset_1.canonical",
) -> TargetHoldings:
    index = pd.MultiIndex.from_tuples(
        [(session, contract_id) for session, contract_id, _ in rows],
        names=["session", "contract_id"],
    )
    frame = pd.DataFrame(
        {"target_holding": [target_holding for _, _, target_holding in rows]},
        index=index,
    )
    return TargetHoldings(
        asset_id=asset_id,
        canonical_id=canonical_id,
        frame=frame,
    )


def test_run_target_holdings_happy_path_chains_sessions_correctly() -> None:
    s1 = to_utc_ts("2026-03-10T00:00:00Z")
    s2 = to_utc_ts("2026-03-11T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    backtester, accessor = _make_backtester(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", s1): 101.5,
            ("corn_mar2026", s2): 102.25,
        },
    )

    target_holdings = _make_target_holdings(
        [
            (s1, "corn_mar2026", 1.0),
            (s2, "corn_mar2026", 2.0),
        ]
    )

    result = backtester.run_target_holdings(target_holdings=target_holdings)

    assert len(result.session_results) == 2

    r1 = result.session_results[0]
    r2 = result.session_results[1]

    assert r1.previous_session is None
    assert r1.session == s1
    assert r2.previous_session == s1
    assert r2.session == s2

    expected_r1_realised = pd.Series(
        [1],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    expected_r2_previous = pd.Series(
        [1],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    expected_r2_realised = pd.Series(
        [2],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(r1.realised_holdings.quantities, expected_r1_realised)
    pdt.assert_series_equal(
        r2.previous_realised_holdings.quantities, expected_r2_previous
    )
    pdt.assert_series_equal(r2.realised_holdings.quantities, expected_r2_realised)

    assert accessor.calls == [
        ("corn_mar2026", s1),
        ("corn_mar2026", s2),
    ]


def test_run_target_holdings_uses_empty_initial_realised_holdings_by_default() -> None:
    s1 = to_utc_ts("2026-03-10T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    backtester, _ = _make_backtester(
        ref_data_api=ref_data_api,
        prices={("corn_mar2026", s1): 101.5},
    )

    target_holdings = _make_target_holdings(
        [
            (s1, "corn_mar2026", 1.0),
        ]
    )

    result = backtester.run_target_holdings(target_holdings=target_holdings)

    expected_empty = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))
    pdt.assert_series_equal(
        result.session_results[0].previous_realised_holdings.quantities,
        expected_empty,
    )


def test_run_target_holdings_accepts_explicit_initial_realised_holdings() -> None:
    s1 = to_utc_ts("2026-03-10T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    backtester, _ = _make_backtester(
        ref_data_api=ref_data_api,
        prices={("corn_mar2026", s1): 101.5},
    )

    initial_realised_holdings = ContractBundle.from_dict({"corn_mar2026": 2})
    target_holdings = _make_target_holdings(
        [
            (s1, "corn_mar2026", 3.0),
        ]
    )

    result = backtester.run_target_holdings(
        target_holdings=target_holdings,
        initial_realised_holdings=initial_realised_holdings,
    )

    expected_previous = pd.Series(
        [2],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    pdt.assert_series_equal(
        result.session_results[0].previous_realised_holdings.quantities,
        expected_previous,
    )


def test_run_target_holdings_slices_correct_target_holdings_per_session() -> None:
    s1 = to_utc_ts("2026-03-10T00:00:00Z")
    s2 = to_utc_ts("2026-03-11T00:00:00Z")

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

    backtester, _ = _make_backtester(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", s1): 101.5,
            ("corn_may2026", s1): 102.25,
            ("corn_mar2026", s2): 103.0,
            ("corn_may2026", s2): 104.0,
        },
    )

    target_holdings = _make_target_holdings(
        [
            (s1, "corn_mar2026", 1.0),
            (s1, "corn_may2026", -1.0),
            (s2, "corn_mar2026", 2.0),
            (s2, "corn_may2026", 0.0),
        ]
    )

    result = backtester.run_target_holdings(target_holdings=target_holdings)

    expected_s1 = pd.Series(
        [1.0, -1.0],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="float64",
        name="target_holding",
    )
    expected_s2 = pd.Series(
        [2.0],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="float64",
        name="target_holding",
    )

    pdt.assert_series_equal(
        result.session_results[0].target_holdings.quantities, expected_s1
    )
    pdt.assert_series_equal(
        result.session_results[1].target_holdings.quantities, expected_s2
    )


def test_run_target_holdings_carries_realised_holdings_forward_between_sessions() -> (
    None
):
    s1 = to_utc_ts("2026-03-10T00:00:00Z")
    s2 = to_utc_ts("2026-03-11T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    backtester, _ = _make_backtester(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", s1): 101.5,
            ("corn_mar2026", s2): 102.25,
        },
    )

    target_holdings = _make_target_holdings(
        [
            (s1, "corn_mar2026", 1.0),
            (s2, "corn_mar2026", 1.0),
        ]
    )

    result = backtester.run_target_holdings(target_holdings=target_holdings)

    expected_r1_realised = pd.Series(
        [1],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    expected_r2_previous = pd.Series(
        [1],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    expected_r2_target_trades = pd.Series(
        dtype="float64",
        index=pd.Index([], name="contract_id"),
    )

    pdt.assert_series_equal(
        result.session_results[0].realised_holdings.quantities, expected_r1_realised
    )
    pdt.assert_series_equal(
        result.session_results[1].previous_realised_holdings.quantities,
        expected_r2_previous,
    )
    pdt.assert_series_equal(
        result.session_results[1].target_trades.quantities, expected_r2_target_trades
    )


def test_run_target_holdings_respects_rounding_across_sessions() -> None:
    s1 = to_utc_ts("2026-03-10T00:00:00Z")
    s2 = to_utc_ts("2026-03-11T00:00:00Z")
    s3 = to_utc_ts("2026-03-12T00:00:00Z")

    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 20),
            ),
        }
    )

    backtester, accessor = _make_backtester(
        ref_data_api=ref_data_api,
        prices={
            ("corn_mar2026", s1): 101.5,
            ("corn_mar2026", s3): 103.25,
        },
    )

    target_holdings = _make_target_holdings(
        [
            (s1, "corn_mar2026", 0.6),
            (s2, "corn_mar2026", 1.4),
            (s3, "corn_mar2026", 1.6),
        ]
    )

    result = backtester.run_target_holdings(target_holdings=target_holdings)

    r1, r2, r3 = result.session_results

    expected_r1_realised = pd.Series(
        [1],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    expected_r2_implemented = pd.Series(
        dtype="int64",
        index=pd.Index([], name="contract_id"),
    )
    expected_r2_realised = pd.Series(
        [1],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    expected_r3_realised = pd.Series(
        [2],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(r1.realised_holdings.quantities, expected_r1_realised)
    pdt.assert_series_equal(r2.implemented_trades.quantities, expected_r2_implemented)
    pdt.assert_series_equal(r2.realised_holdings.quantities, expected_r2_realised)
    pdt.assert_series_equal(r3.realised_holdings.quantities, expected_r3_realised)

    assert accessor.calls == [
        ("corn_mar2026", s1),
        ("corn_mar2026", s3),
    ]


def test_backtest_result_rejects_unsorted_session_results() -> None:
    s1 = to_utc_ts("2026-03-10T00:00:00Z")
    s2 = to_utc_ts("2026-03-11T00:00:00Z")

    empty_holdings = ContractBundle.empty()
    empty_target = TargetContractBundle.empty()

    dummy_execution_result = PerfectBacktestExecutor(
        execution_price_accessor=DummyExecutionPriceAccessor(prices={})
    ).execute_orders(
        submission=type(
            "DummySubmission",
            (),
            {"orders": [], "submission_timestamp": s1},
        )()
    )

    r2 = SessionResult(
        previous_session=s1,
        session=s2,
        previous_realised_holdings=empty_holdings,
        initial_holdings=empty_holdings,
        target_holdings=empty_target,
        target_trades=empty_target,
        implemented_trades=empty_holdings,
        orders=[],
        execution_result=dummy_execution_result,
        realised_holdings=empty_holdings,
    )
    r1 = SessionResult(
        previous_session=None,
        session=s1,
        previous_realised_holdings=empty_holdings,
        initial_holdings=empty_holdings,
        target_holdings=empty_target,
        target_trades=empty_target,
        implemented_trades=empty_holdings,
        orders=[],
        execution_result=dummy_execution_result,
        realised_holdings=empty_holdings,
    )

    with pytest.raises(ValueError, match="sorted by session"):
        BacktestResult(session_results=[r2, r1])


def test_run_target_holdings_propagates_session_engine_failure() -> None:
    s1 = to_utc_ts("2026-03-10T00:00:00Z")
    initial_realised_holdings = ContractBundle.from_dict({"corn_mar2026": 1})
    ref_data_api = DummyRefDataAPI(
        {
            "corn_mar2026": DummyContract(
                product_id="corn",
                last_trading_day=date(2026, 3, 10),
            ),
        }
    )

    backtester, _ = _make_backtester(
        ref_data_api=ref_data_api,
        prices={},
    )

    target_holdings = _make_target_holdings(
        [
            (s1, "corn_mar2026", 1.0),
        ]
    )

    with pytest.raises(ValueError, match="on or beyond last trading day"):
        backtester.run_target_holdings(
            target_holdings=target_holdings,
            initial_realised_holdings=initial_realised_holdings,
        )
