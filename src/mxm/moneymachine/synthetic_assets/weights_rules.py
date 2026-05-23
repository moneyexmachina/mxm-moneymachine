from __future__ import annotations

from dataclasses import dataclass

from mxm.moneymachine.synthetic_assets.rolling.linear_roll import LinearRoll


class InvalidWeightsRuleId(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WeightsRuleSpec:
    kind: str
    roll_start_offset: int
    roll_duration: int


def short_weights_rule_id(spec: WeightsRuleSpec) -> str:
    if spec.kind == "LINEAR_ROLL":
        return f"lr_{spec.roll_start_offset}_{spec.roll_duration}"
    raise ValueError(f"Unsupported weights rule kind {spec.kind!r}")


def canonical_weights_rule_id(spec: WeightsRuleSpec) -> str:
    if spec.kind != "LINEAR_ROLL":
        raise ValueError(f"Unsupported weights rule kind {spec.kind!r}")

    if spec.roll_start_offset < 1:
        raise ValueError("roll_start_offset must be >= 1")
    if spec.roll_duration < 1:
        raise ValueError("roll_duration must be >= 1")
    if spec.roll_duration > spec.roll_start_offset:
        raise ValueError("roll_duration must be <= roll_start_offset")

    return (
        f"WR::KIND={spec.kind}"
        f"::ROLL_START_OFFSET={spec.roll_start_offset}"
        f"::ROLL_DURATION={spec.roll_duration}"
    )


def parse_weights_rule_id(weights_rule_id: str) -> WeightsRuleSpec:
    parts = weights_rule_id.split("::")
    if not parts or parts[0] != "WR":
        raise InvalidWeightsRuleId(
            f"weights_rule_id must start with 'WR::', got {weights_rule_id!r}"
        )

    kv: dict[str, str] = {}
    for part in parts[1:]:
        if "=" not in part:
            raise InvalidWeightsRuleId(
                f"Malformed weights_rule_id component {part!r} in {weights_rule_id!r}"
            )
        k, v = part.split("=", 1)
        kv[k] = v

    kind = kv.get("KIND")
    if kind != "LINEAR_ROLL":
        raise InvalidWeightsRuleId(
            f"Unsupported weights rule kind {kind!r} in {weights_rule_id!r}"
        )

    try:
        roll_start_offset = int(kv["ROLL_START_OFFSET"])
        roll_duration = int(kv["ROLL_DURATION"])
    except KeyError as e:
        raise InvalidWeightsRuleId(
            f"Missing required field {e.args[0]!r} in {weights_rule_id!r}"
        ) from e
    except ValueError as e:
        raise InvalidWeightsRuleId(
            f"ROLL_START_OFFSET and ROLL_DURATION must be integers in {weights_rule_id!r}"
        ) from e

    spec = WeightsRuleSpec(
        kind=kind,
        roll_start_offset=roll_start_offset,
        roll_duration=roll_duration,
    )

    # Validate via canonical constructor rules
    canonical_weights_rule_id(spec)

    return spec


def instantiate_roll_model(spec: WeightsRuleSpec) -> LinearRoll:
    if spec.kind != "LINEAR_ROLL":
        raise ValueError(f"Unsupported weights rule kind {spec.kind!r}")

    return LinearRoll(
        roll_start_offset=spec.roll_start_offset,
        roll_duration=spec.roll_duration,
    )
