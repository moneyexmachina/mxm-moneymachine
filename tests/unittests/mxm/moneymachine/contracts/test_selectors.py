from __future__ import annotations

import pytest

from mxm.moneymachine.contracts.relative_ids import canonical_relative_id, short_rel_id
from mxm.moneymachine.contracts.selectors import (
    PeriodFilter,
    SelectionExplanation,
    SelectorRule,
)
from mxm.refdata.models.periods import PeriodType


def test_period_filter_allows_no_cycle_when_no_elements() -> None:
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    assert pf.cycle_id is None
    assert pf.cycle_elements is None


def test_period_filter_requires_cycle_id_if_elements_provided() -> None:
    with pytest.raises(ValueError, match="cycle_id must be set"):
        PeriodFilter(
            period_type=PeriodType.MONTH,
            cycle_id=None,
            cycle_elements=frozenset({12}),
        )


def test_period_filter_rejects_empty_cycle_elements() -> None:
    with pytest.raises(ValueError, match="must be non-empty"):
        PeriodFilter(
            period_type=PeriodType.MONTH,
            cycle_id="CALENDAR_MONTHS",
            cycle_elements=frozenset(),
        )


def test_period_filter_rejects_non_positive_cycle_elements() -> None:
    with pytest.raises(ValueError, match="positive integers"):
        PeriodFilter(
            period_type=PeriodType.MONTH,
            cycle_id="CALENDAR_MONTHS",
            cycle_elements=frozenset({0, 1}),
        )


def test_period_filter_month_enforces_1_to_12() -> None:
    with pytest.raises(ValueError, match=r"1..12"):
        PeriodFilter(
            period_type=PeriodType.MONTH,
            cycle_id="CALENDAR_MONTHS",
            cycle_elements=frozenset({13}),
        )


def test_period_filter_non_month_allows_large_elements() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.QUARTER,
        cycle_id="CALENDAR_QUARTERS",
        cycle_elements=frozenset({4}),
    )
    assert pf.cycle_elements == frozenset({4})


def test_period_filter_roundtrip_dict() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset({12, 1}),
    )
    d = pf.to_dict()
    assert d["period_type"] == "MONTH"
    assert d["cycle_id"] == "CALENDAR_MONTHS"
    assert d["cycle_elements"] == [1, 12]

    pf2 = PeriodFilter.from_dict(d)
    assert pf2 == pf


def test_selector_rule_rejects_n_lt_1() -> None:
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    with pytest.raises(ValueError, match="must be >= 1"):
        SelectorRule(period_filter=pf, n=0)


def test_selector_rule_roundtrip_dict() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset({12}),
    )
    rule = SelectorRule(period_filter=pf, n=2)

    d = rule.to_dict()
    assert d["n"] == 2
    assert d["period_filter"]["period_type"] == "MONTH"

    rule2 = SelectorRule.from_dict(d)
    assert rule2 == rule


def test_selection_explanation_to_dict_smoke() -> None:
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=1)
    canon = canonical_relative_id(rule)
    short = short_rel_id(rule)

    exp = SelectionExplanation(
        product_id="ES",
        as_of_utc="2026-02-11T12:00:00Z",
        as_of_session="2026-02-11",
        rule=rule,
        canonical_relative_id=canon,
        short_rel_id=short,
        selected_contract_id="ES-2026-03",
        outcome="selected",
        failure_type=None,
        message=None,
        details={"eligible_count": 3},
    )

    d = exp.to_dict()
    assert d["product_id"] == "ES"
    assert d["rule"]["n"] == 1
    assert d["details"]["eligible_count"] == 3
