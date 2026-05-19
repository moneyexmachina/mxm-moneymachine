from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import cast

import pytest

from mxm.refdata.api.ref_data_api import RefDataAPI  # type: ignore
from mxm.refdata.models.contracts.futures_contract import FuturesContract
from mxm.refdata.models.currencies import Currency
from mxm.refdata.models.periods import Period, PeriodType
from mxm.refdata.models.units import ProductUnit
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.contracts.exceptions import NoEligibleContracts, RelativeContractUnavailable
from mxm.v1.contracts.relative_ids import canonical_relative_id, short_rel_id
from mxm.v1.contracts.selectors import PeriodFilter, SelectorRule

# -------------------------
# Fakes
# -------------------------


@dataclass(frozen=True)
class _FakeCalendar:
    as_of_session_value: date

    def as_of_session(self, as_of_ts: datetime) -> date:
        _ = as_of_ts
        return self.as_of_session_value


@dataclass(frozen=True)
class _FakeCalendarService:
    by_product: dict[str, _FakeCalendar]

    def calendar_for_product(self, product_id: str) -> _FakeCalendar:
        return self.by_product[product_id]


@dataclass
class _FakeRefData:
    periods: list[Period]
    contracts_by_product: dict[str, list[FuturesContract]]
    cycle_elements: dict[str, dict[str, int]]  # cycle_id -> period_id -> element

    def get_periods(self) -> list[Period]:
        return list(self.periods)

    def get_contracts_for_product(
        self,
        product_id: str,
        *,
        period_type: PeriodType | None = None,
    ) -> list[FuturesContract]:
        xs = list(self.contracts_by_product.get(product_id, []))
        if period_type is None:
            return xs
        return xs

    def get_cycle_elements(
        self, period_ids: list[str], *, cycle_id: str
    ) -> dict[str, int]:
        mapping = self.cycle_elements.get(cycle_id, {})
        return {pid: mapping[pid] for pid in period_ids if pid in mapping}


def _unit(value: str) -> ProductUnit:
    return cast(ProductUnit, value)


def _currency(value: str) -> Currency:
    return cast(Currency, value)


def _refdata(ref: _FakeRefData) -> RefDataAPI:
    return cast(RefDataAPI, ref)


def _calendar_service(calendars: _FakeCalendarService) -> TradingCalendarService:
    return cast(TradingCalendarService, calendars)


def _ts(yyyy: int, mm: int, dd: int) -> datetime:
    return datetime(yyyy, mm, dd, 12, 0, 0, tzinfo=UTC)


# -------------------------
# Fixtures
# -------------------------


@pytest.fixture()
def sample_periods() -> list[Period]:
    # Keep Period ordering deterministic using first_date.
    # Period.__lt__ sorts by priority then by first_date.
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
def engine(sample_periods: list[Period]) -> ContractSelectorEngine:
    contracts = [
        FuturesContract(
            contract_id="ES-2026-03",
            product_id="ES",
            period_id="2026-03",
            contract_size=1.0,
            unit=_unit("idx"),
            currency=_currency("USD"),
            trading_calendar="CMES",
            first_day_of_interest=date(2026, 1, 1),
            last_trading_day=date(2026, 3, 20),
        ),
        FuturesContract(
            contract_id="ES-2026-06",
            product_id="ES",
            period_id="2026-06",
            contract_size=1.0,
            unit=_unit("idx"),
            currency=_currency("USD"),
            trading_calendar="CMES",
            first_day_of_interest=date(2026, 1, 1),
            last_trading_day=date(2026, 6, 19),
        ),
        FuturesContract(
            contract_id="ES-2026-12",
            product_id="ES",
            period_id="2026-12",
            contract_size=1.0,
            unit=_unit("idx"),
            currency=_currency("USD"),
            trading_calendar="CMES",
            first_day_of_interest=date(2026, 1, 1),
            last_trading_day=date(2026, 12, 18),
        ),
    ]

    ref = _FakeRefData(
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
    cal_svc = _FakeCalendarService(
        by_product={"ES": _FakeCalendar(as_of_session_value=date(2026, 2, 11))}
    )

    return ContractSelectorEngine.build(
        refdata=_refdata(ref), calendars=_calendar_service(cal_svc)
    )


# -------------------------
# Tests
# -------------------------


def test_select_happy_path_n1(engine: ContractSelectorEngine) -> None:
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=1)

    got = engine.select("ES", _ts(2026, 2, 11), rule)
    assert got == "ES-2026-03"


def test_select_happy_path_n2(engine: ContractSelectorEngine) -> None:
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=2)

    got = engine.select("ES", _ts(2026, 2, 11), rule)
    assert got == "ES-2026-06"


def test_eligibility_is_strict_greater_than(engine: ContractSelectorEngine) -> None:
    # Move as_of_session to exactly the first contract's LTD => it becomes ineligible.
    engine2 = ContractSelectorEngine.build(
        refdata=engine.refdata,
        calendars=_calendar_service(
            _FakeCalendarService(
                by_product={"ES": _FakeCalendar(as_of_session_value=date(2026, 3, 20))}
            )
        ),
    )

    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=1)

    got = engine2.select("ES", _ts(2026, 3, 20), rule)
    assert got == "ES-2026-06"


def test_no_eligible_contracts_raises(engine: ContractSelectorEngine) -> None:
    # as_of_session beyond all LTDs => none eligible
    engine2 = ContractSelectorEngine.build(
        refdata=engine.refdata,
        calendars=_calendar_service(
            _FakeCalendarService(
                by_product={"ES": _FakeCalendar(as_of_session_value=date(2027, 1, 1))}
            )
        ),
    )

    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=1)

    with pytest.raises(NoEligibleContracts):
        engine2.select("ES", _ts(2027, 1, 1), rule)

    exp = engine2.explain("ES", _ts(2027, 1, 1), rule)
    assert exp.outcome == "failed"
    assert exp.failure_type == "NoEligibleContracts"
    assert exp.details["eligible_count"] == 0


def test_relative_contract_unavailable_raises(engine: ContractSelectorEngine) -> None:
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=10)

    with pytest.raises(RelativeContractUnavailable) as e:
        engine.select("ES", _ts(2026, 2, 11), rule)

    exc = e.value
    assert exc.n == 10
    assert exc.available == 3

    exp = engine.explain("ES", _ts(2026, 2, 11), rule)
    assert exp.outcome == "failed"
    assert exp.failure_type == "RelativeContractUnavailable"
    assert exp.details["eligible_count"] == 3


def test_cycle_filter_calendar_months_december_only(
    engine: ContractSelectorEngine,
) -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset({12}),
    )
    rule = SelectorRule(period_filter=pf, n=1)

    got = engine.select("ES", _ts(2026, 2, 11), rule)
    assert got == "ES-2026-12"

    exp = engine.explain("ES", _ts(2026, 2, 11), rule)
    assert exp.outcome == "selected"
    assert exp.details["admissible_count"] == 1
    assert exp.details["eligible_count"] == 1


def test_tie_break_by_period_then_contract_id(sample_periods: list[Period]) -> None:
    # Two contracts share LTD; order should use Period ordering then contract_id.
    contracts = [
        FuturesContract(
            contract_id="ES-2026-06-B",
            product_id="ES",
            period_id="2026-06",
            contract_size=1.0,
            unit=_unit("idx"),
            currency=_currency("USD"),
            trading_calendar="CMES",
            first_day_of_interest=date(2026, 1, 1),
            last_trading_day=date(2026, 6, 19),
        ),
        FuturesContract(
            contract_id="ES-2026-03-A",
            product_id="ES",
            period_id="2026-03",
            contract_size=1.0,
            unit=_unit("idx"),
            currency=_currency("USD"),
            trading_calendar="CMES",
            first_day_of_interest=date(2026, 1, 1),
            last_trading_day=date(2026, 6, 19),  # same LTD as above
        ),
        FuturesContract(
            contract_id="ES-2026-03-C",
            product_id="ES",
            period_id="2026-03",
            contract_size=1.0,
            unit=_unit("idx"),
            currency=_currency("USD"),
            trading_calendar="CMES",
            first_day_of_interest=date(2026, 1, 1),
            last_trading_day=date(
                2026, 6, 19
            ),  # same LTD, same period, contract_id tie-break
        ),
    ]

    ref = _FakeRefData(
        periods=sample_periods,
        contracts_by_product={"ES": contracts},
        cycle_elements={},
    )
    cal_svc = _FakeCalendarService(
        by_product={"ES": _FakeCalendar(as_of_session_value=date(2026, 1, 1))}
    )
    eng = ContractSelectorEngine.build(
        refdata=_refdata(ref), calendars=_calendar_service(cal_svc)
    )

    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=1)

    # Period ordering should prefer 2026-03 before 2026-06 when LTD ties.
    # Within the 2026-03 period, contract_id ascending should pick "-A" before "-C".
    got = eng.select("ES", _ts(2026, 1, 1), rule)
    assert got == "ES-2026-03-A"


def test_explain_includes_labels_on_success(engine: ContractSelectorEngine) -> None:
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=1)

    exp = engine.explain("ES", _ts(2026, 2, 11), rule)

    assert exp.outcome == "selected"
    assert exp.canonical_relative_id == canonical_relative_id(rule)
    assert exp.short_rel_id == short_rel_id(rule)
    assert exp.short_rel_id == "L1"


def test_explain_includes_labels_on_no_eligible_failure(
    engine: ContractSelectorEngine,
) -> None:
    engine2 = ContractSelectorEngine.build(
        refdata=engine.refdata,
        calendars=_calendar_service(
            _FakeCalendarService(
                by_product={"ES": _FakeCalendar(as_of_session_value=date(2027, 1, 1))}
            )
        ),
    )

    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=1)

    exp = engine2.explain("ES", _ts(2027, 1, 1), rule)

    assert exp.outcome == "failed"
    assert exp.failure_type == "NoEligibleContracts"
    assert exp.canonical_relative_id == canonical_relative_id(rule)
    assert exp.short_rel_id == short_rel_id(rule)
    assert exp.short_rel_id == "L1"


def test_explain_includes_labels_on_unavailable_failure(
    engine: ContractSelectorEngine,
) -> None:
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=10)

    exp = engine.explain("ES", _ts(2026, 2, 11), rule)

    assert exp.outcome == "failed"
    assert exp.failure_type == "RelativeContractUnavailable"
    assert exp.canonical_relative_id == canonical_relative_id(rule)
    assert exp.short_rel_id == short_rel_id(rule)
    assert exp.short_rel_id == "L10"


def test_explain_labels_for_calendar_month_singleton_filter(
    engine: ContractSelectorEngine,
) -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset({12}),
    )
    rule = SelectorRule(period_filter=pf, n=2)

    exp = engine.explain("ES", _ts(2026, 2, 11), rule)

    # Outcome does not matter for the label invariant; labels must be correct regardless.
    assert exp.canonical_relative_id == canonical_relative_id(rule)
    assert exp.short_rel_id == short_rel_id(rule)
    assert exp.short_rel_id == "Dec2"
