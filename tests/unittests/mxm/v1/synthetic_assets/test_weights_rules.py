
import pytest

from mxm.v1.synthetic_assets.weights_rules import (
    WeightsRuleSpec,
    canonical_weights_rule_id,
    instantiate_roll_model,
    parse_weights_rule_id,
)


def test_weights_rule_roundtrip():
    spec = WeightsRuleSpec(
        kind="LINEAR_ROLL",
        roll_start_offset=3,
        roll_duration=1,
    )

    wr_id = canonical_weights_rule_id(spec)
    parsed = parse_weights_rule_id(wr_id)

    assert parsed == spec


def test_parse_valid_weights_rule():
    wr_id = "WR::KIND=LINEAR_ROLL::ROLL_START_OFFSET=5::ROLL_DURATION=2"

    spec = parse_weights_rule_id(wr_id)

    assert spec.kind == "LINEAR_ROLL"
    assert spec.roll_start_offset == 5
    assert spec.roll_duration == 2


def test_reject_duration_greater_than_offset():
    wr_id = "WR::KIND=LINEAR_ROLL::ROLL_START_OFFSET=3::ROLL_DURATION=4"

    with pytest.raises(ValueError):
        parse_weights_rule_id(wr_id)


def test_reject_missing_field():
    wr_id = "WR::KIND=LINEAR_ROLL::ROLL_DURATION=1"

    with pytest.raises(ValueError):
        parse_weights_rule_id(wr_id)


def test_reject_unknown_kind():
    wr_id = "WR::KIND=SOMETHING::ROLL_START_OFFSET=3::ROLL_DURATION=1"

    with pytest.raises(ValueError):
        parse_weights_rule_id(wr_id)


def test_instantiate_roll_model():
    spec = WeightsRuleSpec(
        kind="LINEAR_ROLL",
        roll_start_offset=4,
        roll_duration=2,
    )

    model = instantiate_roll_model(spec)

    assert model.roll_start_offset == 4
    assert model.roll_duration == 2
