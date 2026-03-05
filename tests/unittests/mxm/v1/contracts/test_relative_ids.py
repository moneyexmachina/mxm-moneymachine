from __future__ import annotations

import pytest
from mxm_refdata.models.periods import PeriodType

from mxm.v1.contracts.relative_ids import canonical_relative_id  # adjust import
from mxm.v1.contracts.relative_ids import (
    parse_canonical_relative_id,
    short_rel_id,
)
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


def test_canonical_relative_id_roundtrip_no_cycle() -> None:
    rule = SelectorRule(period_filter=PeriodFilter(period_type=PeriodType.MONTH), n=2)
    s = canonical_relative_id(rule)
    assert parse_canonical_relative_id(s) == rule


def test_canonical_relative_id_roundtrip_with_cycle() -> None:
    pf = PeriodFilter(
        period_type=PeriodType.MONTH,
        cycle_id="CALENDAR_MONTHS",
        cycle_elements=frozenset({3, 6, 9, 12}),
    )
    rule = SelectorRule(period_filter=pf, n=1)
    s = canonical_relative_id(rule)
    assert parse_canonical_relative_id(s) == rule


def test_parse_rejects_wrong_prefix() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id("XX::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1")


def test_parse_rejects_missing_keys() -> None:
    # Missing N
    with pytest.raises(ValueError):
        parse_canonical_relative_id("RC::PT=MONTH::CYCLE=NONE::RANK=LTD")


def test_parse_rejects_unexpected_keys() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id(
            "RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1::EXTRA=foo"
        )


def test_parse_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id("RC::PT=MONTH::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1")


def test_parse_rejects_bad_token_without_equals() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id("RC::PT=MONTH::CYCLE=NONE::RANK::N=1")


def test_parse_rejects_unknown_period_type() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id("RC::PT=MOON::CYCLE=NONE::RANK=LTD::N=1")


def test_parse_rejects_non_ltd_rank() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id("RC::PT=MONTH::CYCLE=NONE::RANK=PERIOD::N=1")


def test_parse_rejects_non_int_n() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id("RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=one")


def test_parse_rejects_n_lt_1() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id("RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=0")


def test_parse_cycle_none_roundtrips_to_none_fields() -> None:
    rule = parse_canonical_relative_id("RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=3")
    assert rule.period_filter.cycle_id is None
    assert rule.period_filter.cycle_elements is None
    assert rule.n == 3


def test_parse_cycle_requires_brackets_format_when_not_none() -> None:
    # Missing [..]
    with pytest.raises(ValueError):
        parse_canonical_relative_id(
            "RC::PT=MONTH::CYCLE=CALENDAR_MONTHS12::RANK=LTD::N=1"
        )


def test_parse_cycle_rejects_empty_elements() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id(
            "RC::PT=MONTH::CYCLE=CALENDAR_MONTHS[]::RANK=LTD::N=1"
        )


def test_parse_cycle_rejects_non_int_elements() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id(
            "RC::PT=MONTH::CYCLE=CALENDAR_MONTHS[Dec]::RANK=LTD::N=1"
        )


def test_parse_cycle_rejects_non_positive_elements() -> None:
    with pytest.raises(ValueError):
        parse_canonical_relative_id(
            "RC::PT=MONTH::CYCLE=CALENDAR_MONTHS[0]::RANK=LTD::N=1"
        )


def test_parse_calendar_months_rejects_elements_gt_12() -> None:
    # Only include if your parser enforces this (recommended).
    with pytest.raises(ValueError):
        parse_canonical_relative_id(
            "RC::PT=MONTH::CYCLE=CALENDAR_MONTHS[13]::RANK=LTD::N=1"
        )


def test_parse_cycle_preserves_cycle_id_and_elements_as_set() -> None:
    rule = parse_canonical_relative_id(
        "RC::PT=MONTH::CYCLE=DELIVERY_MONTHS[7,2,5]::RANK=LTD::N=2"
    )
    assert rule.period_filter.cycle_id == "DELIVERY_MONTHS"
    assert rule.period_filter.cycle_elements == frozenset({2, 5, 7})
    assert rule.n == 2
