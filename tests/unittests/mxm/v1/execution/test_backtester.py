from __future__ import annotations

from datetime import date
from typing import cast

import numpy as np
import pandas as pd
import pandas.testing as pdt
import pytest

from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.execution.backtester import Backtester, BacktestResult
from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle
from mxm.v1.execution.executor import OrderSubmission, PerfectBacktestExecutor
from mxm.v1.execution.orders import (
    OrderGenerationPolicy,
    OrderGenerator,
    OrderTimestampPolicy,
)
from mxm.v1.execution.price_accessors import ExecutionPriceAccessor
from mxm.v1.execution.session_engine import SessionEngine, SessionResult
from mxm.v1.synthetic_assets.target_holdings import TargetHoldings
from mxm.v1.utils.time_utils import to_utc_ts

S1 = np.datetime64("2026-03-10", "D")
S2 = np.datetime64("2026-03-11", "D")
S3 = np.datetime64("2026-03-12", "D")


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
        open_ts: pd.Timestamp | None = None,
        close_ts: pd.Timestamp | None = None,
    ) -> None:
        self._open_ts = (
            to_utc_ts("2026-03-10T08:00:00Z") if open_ts is None else open_ts
        )
        self._close_ts = (
            to_utc_ts("2026-03-10T16:00:00Z") if close_ts is None else close_ts
        )

    def session_open(self, session: np.datetime64) -> pd.Timestamp:
        day = session.astype("datetime64[D]")
        return to_utc_ts(f"{day.astype(str)}T08:00:00Z")

    def session_close(self, session: np.datetime64) -> pd.Timestamp:
        day = session.astype("datetime64[D]")
        return to_utc_ts(f"{day.astype(str)}T16:00:00Z")


class DummyCalendarService:
    def __init__(self, mapping: dict[str, DummyCalendar]) -> None:
        self._mapping = mapping

    def calendar_for_product(self, product_id: str) -> DummyCalendar:
        try:
            return self._mapping[product_id]
        except KeyError as exc:
            raise ValueError(f"Unknown product_id {product_id!r}") from exc


def _make_backtester(
    *,
    ref_data_api: DummyRefDataAPI,
    prices: dict[tuple[str, np.datetime64], float],
    default_min_block_size: int = 1,
    timestamp_policy: OrderTimestampPolicy = OrderTimestampPolicy.SESSION_OPEN,
    calendars_by_product: dict[str, DummyCalendar] | None = None,
) -> tuple[Backtester, DummyExecutionPriceAccessor]:
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
    session_engine = SessionEngine(
        ref_data_api=cast(RefDataAPI, ref_data_api),
        order_generator=order_generator,
        executor=executor,
    )
    backtester = Backtester(session_engine=session_engine)
    return backtester, accessor


def _make_target_holdings(
    rows: list[tuple[np.datetime64, str, float]],
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
            ("corn_mar2026", S1): 101.5,
            ("corn_mar2026", S2): 102.25,
        },
    )

    target_holdings = _make_target_holdings(
        [
            (S1, "corn_mar2026", 1.0),
            (S2, "corn_mar2026", 2.0),
        ]
    )

    result = backtester.run_target_holdings(target_holdings=target_holdings)

    assert len(result.session_results) == 2

    r1 = result.session_results[0]
    r2 = result.session_results[1]

    assert r1.previous_session is None
    assert r1.session == S1
    assert r2.previous_session == S1
    assert r2.session == S2

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
        ("corn_mar2026", S1),
        ("corn_mar2026", S2),
    ]


def test_run_target_holdings_uses_empty_initial_realised_holdings_by_default() -> None:
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
        prices={("corn_mar2026", S1): 101.5},
    )

    target_holdings = _make_target_holdings(
        [
            (S1, "corn_mar2026", 1.0),
        ]
    )

    result = backtester.run_target_holdings(target_holdings=target_holdings)

    expected_empty = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))
    pdt.assert_series_equal(
        result.session_results[0].previous_realised_holdings.quantities,
        expected_empty,
    )


def test_run_target_holdings_accepts_explicit_initial_realised_holdings() -> None:
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
        prices={("corn_mar2026", S1): 101.5},
    )

    initial_realised_holdings = ContractBundle.from_dict({"corn_mar2026": 2})
    target_holdings = _make_target_holdings(
        [
            (S1, "corn_mar2026", 3.0),
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
            ("corn_mar2026", S1): 101.5,
            ("corn_may2026", S1): 102.25,
            ("corn_mar2026", S2): 103.0,
            ("corn_may2026", S2): 104.0,
        },
    )

    target_holdings = _make_target_holdings(
        [
            (S1, "corn_mar2026", 1.0),
            (S1, "corn_may2026", -1.0),
            (S2, "corn_mar2026", 2.0),
            (S2, "corn_may2026", 0.0),
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
            ("corn_mar2026", S1): 101.5,
            ("corn_mar2026", S2): 102.25,
        },
    )

    target_holdings = _make_target_holdings(
        [
            (S1, "corn_mar2026", 1.0),
            (S2, "corn_mar2026", 1.0),
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
            ("corn_mar2026", S1): 101.5,
            ("corn_mar2026", S3): 103.25,
        },
    )

    target_holdings = _make_target_holdings(
        [
            (S1, "corn_mar2026", 0.6),
            (S2, "corn_mar2026", 1.4),
            (S3, "corn_mar2026", 1.6),
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
        ("corn_mar2026", S1),
        ("corn_mar2026", S3),
    ]


def test_backtest_result_rejects_unsorted_session_results() -> None:
    empty_holdings = ContractBundle.empty()
    empty_target = TargetContractBundle.empty()

    dummy_execution_result = PerfectBacktestExecutor(
        execution_price_accessor=DummyExecutionPriceAccessor(prices={})
    ).execute_orders(
        OrderSubmission(
            orders=[],
            session=S1,
            submission_timestamp=None,
        )
    )

    r2 = SessionResult(
        previous_session=S1,
        session=S2,
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
        session=S1,
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
            (S1, "corn_mar2026", 1.0),
        ]
    )

    with pytest.raises(ValueError, match="on or beyond last trading day"):
        backtester.run_target_holdings(
            target_holdings=target_holdings,
            initial_realised_holdings=initial_realised_holdings,
        )
