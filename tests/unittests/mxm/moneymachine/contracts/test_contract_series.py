from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import cast

import numpy as np
import pytest

from mxm.moneymachine.calendars.service import TradingCalendarService
from mxm.moneymachine.contracts.contract_series import (
    ContractSeries,
    ContractSeriesSpec,
    build_contract_series,
)
from mxm.moneymachine.contracts.engine import ContractSelectorEngine
from mxm.moneymachine.contracts.relative_ids import canonical_relative_id, short_rel_id
from mxm.moneymachine.contracts.selectors import PeriodFilter, SelectorRule
from mxm.refdata import RefDataReader
from mxm.refdata.models.contracts.futures_contract import FuturesContract
from mxm.refdata.models.currencies import Currency
from mxm.refdata.models.periods import Period, PeriodType
from mxm.refdata.models.units import ProductUnit

EngineAndCalendar = tuple[ContractSelectorEngine, TradingCalendarService]
UtcTs = datetime | np.datetime64


def _unit(value: str) -> ProductUnit:
    return cast(ProductUnit, value)


def _currency(value: str) -> Currency:
    return cast(Currency, value)


def _calendar_service(calendars: _FakeCalendarService) -> TradingCalendarService:
    return cast(TradingCalendarService, calendars)


def _to_py_date(x: UtcTs) -> date:
    if isinstance(x, datetime):
        return x.date()

    return date.fromisoformat(str(x)[:10])


@dataclass(frozen=True)
class _FakeTradingCalendar:
    """
    Provides both:
      - trading_days for ContractSeries calendar slicing
      - as_of_session for engine selection
    """

    trading_days: np.ndarray

    def as_of_session(self, as_of_ts: UtcTs) -> date:
        return _to_py_date(as_of_ts)


@dataclass(frozen=True)
class _FakeCalendarService:
    by_product: dict[str, _FakeTradingCalendar]

    def calendar_for_product(self, product_id: str) -> _FakeTradingCalendar:
        return self.by_product[product_id]


@dataclass
class _FakeRefDataReader:
    periods: list[Period]
    contracts_by_product: dict[str, list[FuturesContract]]
    cycle_elements: dict[str, dict[str, int]]

    def get_periods(self) -> list[Period]:
        return list(self.periods)

    def get_contracts_for_product(
        self,
        product_id: str,
        *,
        period_type: PeriodType | None = None,
    ) -> list[FuturesContract]:
        _ = period_type
        return list(self.contracts_by_product.get(product_id, []))

    def get_cycle_elements(
        self,
        period_ids: list[str],
        *,
        cycle_id: str,
    ) -> dict[str, int]:
        mapping = self.cycle_elements.get(cycle_id, {})
        return {pid: mapping[pid] for pid in period_ids if pid in mapping}


def _contract(
    *,
    contract_id: str,
    period_id: str,
    last_trading_day: date,
) -> FuturesContract:
    return FuturesContract(
        contract_id=contract_id,
        product_id="ES",
        period_id=period_id,
        contract_size=1.0,
        unit=_unit("idx"),
        currency=_currency("USD"),
        trading_calendar="CMES",
        first_day_of_interest=date(2026, 1, 1),
        last_trading_day=last_trading_day,
    )


@pytest.fixture()
def sample_periods() -> list[Period]:
    return [
        Period(
            period_id="2026-03",
            period_type=PeriodType.MONTH,
            first_date=date(2026, 3, 1),
            last_date=date(2026, 3, 31),
        ),
        Period(
            period_id="2026-06",
            period_type=PeriodType.MONTH,
            first_date=date(2026, 6, 1),
            last_date=date(2026, 6, 30),
        ),
        Period(
            period_id="2026-12",
            period_type=PeriodType.MONTH,
            first_date=date(2026, 12, 1),
            last_date=date(2026, 12, 31),
        ),
    ]


@pytest.fixture()
def engine_and_calendar(
    sample_periods: list[Period],
) -> EngineAndCalendar:
    contracts = [
        _contract(
            contract_id="ES-2026-03",
            period_id="2026-03",
            last_trading_day=date(2026, 3, 20),
        ),
        _contract(
            contract_id="ES-2026-06",
            period_id="2026-06",
            last_trading_day=date(2026, 6, 19),
        ),
        _contract(
            contract_id="ES-2026-12",
            period_id="2026-12",
            last_trading_day=date(2026, 12, 18),
        ),
    ]

    refdata_reader = _FakeRefDataReader(
        periods=sample_periods,
        contracts_by_product={"ES": contracts},
        cycle_elements={
            "CALENDAR_MONTHS": {
                "2026-03": 3,
                "2026-06": 6,
                "2026-12": 12,
            }
        },
    )

    cal_days = np.array(
        [
            np.datetime64("2026-03-18"),
            np.datetime64("2026-03-19"),
            np.datetime64("2026-03-20"),
            np.datetime64("2026-03-23"),
            np.datetime64("2026-03-24"),
        ],
        dtype="datetime64[D]",
    )

    cal_svc = _FakeCalendarService(
        by_product={"ES": _FakeTradingCalendar(trading_days=cal_days)}
    )

    calendar_service = _calendar_service(cal_svc)
    eng = ContractSelectorEngine.build(
        refdata_reader=cast(RefDataReader, refdata_reader),
        calendars=calendar_service,
    )
    return eng, calendar_service


def _month_rule(n: int) -> SelectorRule:
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    return SelectorRule(period_filter=pf, n=n)


def test_contract_series_spec_rejects_end_before_start() -> None:
    rule = _month_rule(1)

    with pytest.raises(ValueError, match="end_session must be >= start_session"):
        ContractSeriesSpec(
            product_id="ES",
            rule=rule,
            start_session=np.datetime64("2026-03-20"),
            end_session=np.datetime64("2026-03-19"),
        )


def test_contract_series_spec_coerces_to_day_dtype() -> None:
    rule = _month_rule(1)

    spec = ContractSeriesSpec(
        product_id="ES",
        rule=rule,
        start_session=np.datetime64("2026-03-20T12:34:56"),
        end_session=np.datetime64("2026-03-20T23:59:59"),
    )

    assert spec.start_session.dtype == np.dtype("datetime64[D]")
    assert spec.end_session.dtype == np.dtype("datetime64[D]")


def test_build_contract_series_requires_start_in_calendar(
    engine_and_calendar: EngineAndCalendar,
) -> None:
    engine, cal_svc = engine_and_calendar
    rule = _month_rule(1)

    spec = ContractSeriesSpec(
        product_id="ES",
        rule=rule,
        start_session=np.datetime64("2026-03-17"),
        end_session=np.datetime64("2026-03-19"),
    )

    with pytest.raises(ValueError, match="start_session not in trading calendar"):
        build_contract_series(engine=engine, calendar_service=cal_svc, spec=spec)


def test_build_contract_series_requires_end_in_calendar(
    engine_and_calendar: EngineAndCalendar,
) -> None:
    engine, cal_svc = engine_and_calendar
    rule = _month_rule(1)

    spec = ContractSeriesSpec(
        product_id="ES",
        rule=rule,
        start_session=np.datetime64("2026-03-18"),
        end_session=np.datetime64("2026-03-22"),
    )

    with pytest.raises(ValueError, match="end_session not in trading calendar"):
        build_contract_series(engine=engine, calendar_service=cal_svc, spec=spec)


def test_build_contract_series_hard_fails_on_non_selected(
    engine_and_calendar: EngineAndCalendar,
) -> None:
    engine, cal_svc = engine_and_calendar

    rule = _month_rule(10)
    canon = canonical_relative_id(rule)

    spec = ContractSeriesSpec(
        product_id="ES",
        rule=rule,
        start_session=np.datetime64("2026-03-18"),
        end_session=np.datetime64("2026-03-19"),
    )

    with pytest.raises(RuntimeError) as e:
        build_contract_series(engine=engine, calendar_service=cal_svc, spec=spec)

    msg = str(e.value)
    assert "product_id=ES" in msg
    assert f"rule={canon}" in msg
    assert "outcome=" in msg
    assert "session=" in msg


def test_build_contract_series_identity_path_and_labels(
    engine_and_calendar: EngineAndCalendar,
) -> None:
    engine, cal_svc = engine_and_calendar
    rule = _month_rule(1)

    spec = ContractSeriesSpec(
        product_id="ES",
        rule=rule,
        start_session=np.datetime64("2026-03-18"),
        end_session=np.datetime64("2026-03-24"),
    )

    series = build_contract_series(engine=engine, calendar_service=cal_svc, spec=spec)

    assert series.product_id == "ES"
    assert series.canonical_relative_id == canonical_relative_id(rule)
    assert series.short_rel_id == short_rel_id(rule)

    assert series.sessions.dtype == np.dtype("datetime64[D]")
    assert len(series.sessions) == len(series.contract_ids)
    assert len(series.sessions) == 5

    assert series.contract_ids == [
        "ES-2026-03",
        "ES-2026-03",
        "ES-2026-06",
        "ES-2026-06",
        "ES-2026-06",
    ]

    m = series.switch_mask()
    assert m.dtype == bool
    assert len(m) == len(series.sessions)
    assert not m[0]

    sw = series.switch_sessions()
    assert sw.tolist() == [np.datetime64("2026-03-20")]

    view = series.switch_view(max_rows=10)
    assert view == [(np.datetime64("2026-03-20"), "ES-2026-03", "ES-2026-06")]


def test_switch_helpers_no_switch_when_constant_contract() -> None:
    series = ContractSeries(
        product_id="ES",
        canonical_relative_id="RC::dummy",
        short_rel_id="X",
        sessions=np.array(
            [np.datetime64("2026-03-18"), np.datetime64("2026-03-19")],
            dtype="datetime64[D]",
        ),
        contract_ids=["ES-2026-03", "ES-2026-03"],
    )

    m = series.switch_mask()
    assert m.tolist() == [False, False]
    assert series.switch_sessions().tolist() == []
    assert series.switch_view() == []


def test_build_contract_series_non_empty_smoke(
    engine_and_calendar: EngineAndCalendar,
) -> None:
    engine, cal_svc = engine_and_calendar
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset({12}),
    )
    rule = SelectorRule(period_filter=pf, n=1)

    spec = ContractSeriesSpec(
        product_id="ES",
        rule=rule,
        start_session=np.datetime64("2026-03-18"),
        end_session=np.datetime64("2026-03-24"),
    )

    series = build_contract_series(engine=engine, calendar_service=cal_svc, spec=spec)

    assert len(series.sessions) > 0
    assert all(isinstance(x, str) and x for x in series.contract_ids)
