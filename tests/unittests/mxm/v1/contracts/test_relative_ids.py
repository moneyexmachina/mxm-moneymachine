from __future__ import annotations

from mxm_refdata.models.periods import PeriodType

from mxm.v1.contracts.relative_ids import canonical_relative_id  # adjust import
from mxm.v1.contracts.relative_ids import short_rel_id
from mxm.v1.contracts.selectors import PeriodFilter, SelectorRule


def test_canonical_month_none_n1() -> None:
    rule = SelectorRule(period_filter=PeriodFilter(period_type=PeriodType.MONTH), n=1)
    assert canonical_relative_id(rule) == "RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1"


def test_canonical_month_none_n2() -> None:
    rule = SelectorRule(period_filter=PeriodFilter(period_type=PeriodType.MONTH), n=2)
    assert canonical_relative_id(rule) == "RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=2"


def test_canonical_month_cycle_december_only() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset([12]),
    )
    rule = SelectorRule(period_filter=pf, n=1)
    assert (
        canonical_relative_id(rule)
        == "RC::PT=MONTH::CYCLE=CALENDAR_MONTHS[12]::RANK=LTD::N=1"
    )


def test_canonical_cycle_elements_sorted_by_rank() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset([12, 3, 9, 6]),
    )
    rule = SelectorRule(period_filter=pf, n=1)
    assert (
        canonical_relative_id(rule)
        == "RC::PT=MONTH::CYCLE=CALENDAR_MONTHS[3,6,9,12]::RANK=LTD::N=1"
    )


def test_short_unfiltered_is_listed_rank() -> None:
    rule = SelectorRule(period_filter=PeriodFilter(period_type=PeriodType.MONTH), n=1)
    assert short_rel_id(rule) == "L1"


def test_short_unfiltered_n2() -> None:
    rule = SelectorRule(period_filter=PeriodFilter(period_type=PeriodType.MONTH), n=2)
    assert short_rel_id(rule) == "L2"


def test_short_calendar_month_singleton_dec() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset([12]),
    )
    rule = SelectorRule(period_filter=pf, n=1)
    assert short_rel_id(rule) == "Dec1"


def test_short_calendar_month_singleton_mar_n2() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset([3]),
    )
    rule = SelectorRule(period_filter=pf, n=2)
    assert short_rel_id(rule) == "Mar2"


def test_short_calendar_month_subset_renders_m_list() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset([12, 3, 9, 6]),
    )
    rule = SelectorRule(period_filter=pf, n=1)
    assert short_rel_id(rule) == "M[3,6,9,12]1"


def test_short_unknown_cycle_singleton_uses_abbrev_and_dash() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="DELIVERY_MONTHS",
        cycle_elements=frozenset([2]),
    )
    rule = SelectorRule(period_filter=pf, n=1)
    assert short_rel_id(rule) == "DM2-1"


def test_short_unknown_cycle_subset_uses_abbrev_brackets() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="DELIVERY_MONTHS",
        cycle_elements=frozenset([2, 5, 7]),
    )
    rule = SelectorRule(period_filter=pf, n=3)
    assert short_rel_id(rule) == "DM[2,5,7]3"


def test_canonical_unfiltered() -> None:
    rule = SelectorRule(period_filter=PeriodFilter(period_type=PeriodType.MONTH), n=1)
    assert canonical_relative_id(rule) == "RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1"
