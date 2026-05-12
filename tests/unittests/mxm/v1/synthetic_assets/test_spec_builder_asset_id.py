from __future__ import annotations

from mxm.refdata.models.periods import PeriodType
from mxm.v1.contracts.selectors import PeriodFilter, SelectorRule
from mxm.v1.synthetic_assets.spec_builder import (
    build_continuous_roll_spec,
    build_product_spread_spec,
    build_time_spread_spec,
)
from mxm.v1.synthetic_assets.weights_rules import (
    WeightsRuleSpec,
    canonical_weights_rule_id,
)


def _l(n: int) -> SelectorRule:
    return SelectorRule(period_filter=PeriodFilter(period_type=PeriodType.MONTH), n=n)


def _wr(*, roll_start_offset: int, roll_duration: int) -> str:
    return canonical_weights_rule_id(
        WeightsRuleSpec(
            kind="LINEAR_ROLL",
            roll_start_offset=roll_start_offset,
            roll_duration=roll_duration,
        )
    )


def test_asset_id_cont_includes_wr() -> None:
    s1 = build_continuous_roll_spec(
        product_id="p0",
        currency="USD",
        unit="unit",
        size=1000,
        weights_rule_id=_wr(roll_start_offset=3, roll_duration=1),
        cur=_l(1),
        nxt=_l(2),
    )
    assert s1.asset_id == "p0_cont_l1_wr_lr_3_1"


def test_asset_id_cont_changes_with_wr() -> None:
    s1 = build_continuous_roll_spec(
        product_id="p0",
        currency="USD",
        unit="unit",
        size=1000,
        weights_rule_id=_wr(roll_start_offset=3, roll_duration=1),
        cur=_l(1),
        nxt=_l(2),
    )
    s2 = build_continuous_roll_spec(
        product_id="p0",
        currency="USD",
        unit="unit",
        size=1000,
        weights_rule_id=_wr(roll_start_offset=5, roll_duration=2),
        cur=_l(1),
        nxt=_l(2),
    )
    assert s1.asset_id != s2.asset_id


def test_asset_id_ts_includes_wr_and_levels() -> None:
    s = build_time_spread_spec(
        product_id="p0",
        currency="USD",
        unit="unit",
        size=1000,
        weights_rule_id=_wr(roll_start_offset=3, roll_duration=1),
        near_cur=_l(1),
        near_nxt=_l(2),
        far_cur=_l(2),
        far_nxt=_l(3),
    )
    assert s.asset_id == "p0_ts_l1_l2_wr_lr_3_1"


def test_asset_id_ps_is_directional_and_includes_wr() -> None:
    s_ab = build_product_spread_spec(
        product_a_id="pa",
        product_b_id="pb",
        currency="USD",
        unit="unit",
        size=1000,
        weights_rule_id=_wr(roll_start_offset=3, roll_duration=1),
        a_cur=_l(1),
        a_nxt=_l(2),
        b_cur=_l(1),
        b_nxt=_l(2),
    )
    s_ba = build_product_spread_spec(
        product_a_id="pb",
        product_b_id="pa",
        currency="USD",
        unit="unit",
        size=1000,
        weights_rule_id=_wr(roll_start_offset=3, roll_duration=1),
        a_cur=_l(1),
        a_nxt=_l(2),
        b_cur=_l(1),
        b_nxt=_l(2),
    )
    assert s_ab.asset_id == "pa_ps_pb_l1_wr_lr_3_1"
    assert s_ba.asset_id == "pb_ps_pa_l1_wr_lr_3_1"
    assert s_ab.asset_id != s_ba.asset_id


def test_time_spread_allows_shared_component_binding_across_components() -> None:
    s = build_time_spread_spec(
        product_id="p0",
        currency="USD",
        unit="unit",
        size=1000,
        weights_rule_id=_wr(roll_start_offset=3, roll_duration=1),
        near_cur=_l(1),
        near_nxt=_l(2),
        far_cur=_l(2),  # shared with near_nxt
        far_nxt=_l(3),
    )
    assert (
        s.components["near_nxt"].selector_rule_id
        == s.components["far_cur"].selector_rule_id
    )
