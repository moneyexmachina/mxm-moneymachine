from __future__ import annotations

"""
Realisation of role-level weights for SyntheticAssetSpec.

This module builds a session-indexed WeightsSeries from a SyntheticAssetSpec.

Scope
-----
Session 25 scope only:

- realise ContractSeries per leg role
- instantiate roll model from spec.weights_rule_id
- compute roll weights for cur/nxt role pairs
- apply static multipliers for spread structures
- return a pure WeightsSeries object

Out of scope
------------
- units, notionals, contract multipliers
- target holdings
- trades / execution / P&L
- persistence of WeightsSeries as a standalone artefact

V1 session-grid policy
----------------------
All leg ContractSeries in one synthetic asset must have identical sessions.

This is expected to hold for current V1 assets:
- CONT
- TS
- PS

If realised leg sessions differ, this module raises.
Cross-calendar alignment is out of scope for v1.
"""

from dataclasses import dataclass
from typing import Iterable, Mapping

import numpy as np
from mxm_refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)
from numpy.typing import NDArray

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.contract_series import (
    ContractSeries,
    ContractSeriesSpec,
    build_contract_series,
)
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.contracts.relative_ids import parse_canonical_relative_id
from mxm.v1.contracts.selectors import SelectorRule
from mxm.v1.synthetic_assets.models import LegBinding, SyntheticAssetSpec
from mxm.v1.synthetic_assets.rolling.bdays_to_ltd_series import (
    build_bdays_to_ltd_series,
)
from mxm.v1.synthetic_assets.rolling.linear_roll import LinearRoll
from mxm.v1.synthetic_assets.weights_rules import parse_weights_rule_id
from mxm.v1.utils.date_utils import coerce_np_day


class UnsupportedWeightsRule(ValueError):
    pass


class UnsupportedLegRoleStructure(ValueError):
    pass


class MisalignedLegSessions(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WeightsSeries:
    """
    Session-indexed unit-less weights by role.

    sessions:
        common session grid of the realised synthetic asset

    role_weights:
        mapping role -> weight vector aligned to sessions
    """

    asset_id: str
    canonical_id: str
    weights_rule_id: str
    sessions: NDArray[np.datetime64]
    role_weights: dict[str, NDArray[np.float64]]

    def roles(self) -> list[str]:
        return sorted(self.role_weights.keys())


def build_weights_series(
    *,
    spec: SyntheticAssetSpec,
    start_session: np.datetime64,
    end_session: np.datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    refdata_api: RefDataAPI,
) -> WeightsSeries:
    """
    Realise WeightsSeries from SyntheticAssetSpec over [start_session, end_session].

    Roll timing is anchored to the front (N=1) series of the same selector family
    as each pair's cur leg, not to the selected cur contract's own LTD.
    """
    roll_model = _build_roll_model(spec.weights_rule_id)

    contract_series_by_role = _build_contract_series_by_role(
        spec=spec,
        start_session=start_session,
        end_session=end_session,
        engine=engine,
        calendar_service=calendar_service,
    )

    sessions = assert_identical_sessions(contract_series_by_role.values())
    role_pairs = infer_role_pairs(spec.legs)

    role_weights: dict[str, NDArray[np.float64]] = {}

    for cur_role, nxt_role, multiplier in role_pairs:
        cur_series = contract_series_by_role[cur_role]
        nxt_series = contract_series_by_role[nxt_role]

        if not np.array_equal(cur_series.sessions, nxt_series.sessions):
            raise MisalignedLegSessions(
                f"Sessions differ for paired roles {cur_role!r} and {nxt_role!r}"
            )

        # ------------------------------------------------------------------
        # Build anchor series: same selector family as cur_role, but N=1
        # ------------------------------------------------------------------
        anchor_series = _build_anchor_contract_series_for_role(
            leg=spec.legs[cur_role],
            start_session=start_session,
            end_session=end_session,
            engine=engine,
            calendar_service=calendar_service,
        )

        if not np.array_equal(anchor_series.sessions, cur_series.sessions):
            raise MisalignedLegSessions(
                f"Anchor sessions differ from role sessions for {cur_role!r}"
            )

        # ------------------------------------------------------------------
        # Roll clock comes from front-anchor LTD, not cur_series LTD
        # ------------------------------------------------------------------
        bdays = build_bdays_to_ltd_series(
            series=anchor_series,
            calendar_service=calendar_service,
            refdata_api=refdata_api,
        )

        w_cur, w_nxt = roll_model.compute_weights_from_bdays_to_ltd(
            bdays_to_ltd=bdays.bdays_to_ltd
        )

        m = float(multiplier)
        role_weights[cur_role] = m * w_cur
        role_weights[nxt_role] = m * w_nxt

    return WeightsSeries(
        asset_id=spec.asset_id,
        canonical_id=spec.canonical_id,
        weights_rule_id=spec.weights_rule_id,
        sessions=sessions,
        role_weights=role_weights,
    )


def _build_anchor_contract_series_for_role(
    *,
    leg: LegBinding,
    start_session: np.datetime64,
    end_session: np.datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
) -> ContractSeries:
    """
    Build the front-anchor ContractSeries for a leg.

    The anchor rule keeps the same selector family (same PeriodFilter) but
    forces n=1, so roll timing is driven by the front of the chain rather than
    the selected cur contract's own LTD.
    """
    rule = SelectorRule.from_canonical_relative_id(leg.selector_rule_id)
    anchor_rule = SelectorRule(period_filter=rule.period_filter, n=1)

    cs_spec = ContractSeriesSpec(
        product_id=leg.product_id,
        rule=anchor_rule,
        start_session=coerce_np_day(start_session),
        end_session=coerce_np_day(end_session),
    )

    return build_contract_series(
        engine=engine,
        calendar_service=calendar_service,
        spec=cs_spec,
    )


def _build_roll_model(weights_rule_id: str) -> LinearRoll:
    """
    Instantiate roll model from weights_rule_id.

    Expected current rule shape:
        WR::KIND=LINEAR_ROLL::ROLL_START_OFFSET=N1::ROLL_DURATION=D

    Adjust field names to your actual weights_rule parser output.
    """
    wr = parse_weights_rule_id(weights_rule_id)

    if wr.kind != "LINEAR_ROLL":
        raise UnsupportedWeightsRule(
            f"Unsupported weights rule kind {wr.kind!r}; only LINEAR_ROLL is supported in v1"
        )

    return LinearRoll(
        roll_start_offset=wr.roll_start_offset,
        roll_duration=wr.roll_duration,
    )


def _build_contract_series_by_role(
    *,
    spec: SyntheticAssetSpec,
    start_session: np.datetime64,
    end_session: np.datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
) -> dict[str, ContractSeries]:
    out: dict[str, ContractSeries] = {}

    for role, leg in spec.legs.items():
        rule = parse_canonical_relative_id(leg.selector_rule_id)

        cs_spec = ContractSeriesSpec(
            product_id=leg.product_id,
            rule=rule,
            start_session=coerce_np_day(start_session),
            end_session=coerce_np_day(end_session),
        )

        out[role] = build_contract_series(
            engine=engine,
            calendar_service=calendar_service,
            spec=cs_spec,
        )

    return out


def assert_identical_sessions(
    series_iter: Iterable[ContractSeries],
) -> NDArray[np.datetime64]:
    series_list = list(series_iter)
    if not series_list:
        raise ValueError("No ContractSeries provided")

    sessions0 = series_list[0].sessions
    for cs in series_list[1:]:
        if sessions0.shape != cs.sessions.shape or not np.array_equal(
            sessions0, cs.sessions
        ):
            raise MisalignedLegSessions(
                "Synthetic asset leg ContractSeries sessions are not identical; "
                "cross-calendar alignment is not supported in v1"
            )
    return sessions0


def infer_role_pairs(
    legs: Mapping[str, LegBinding],
) -> list[tuple[str, str, float]]:
    """
    Infer roll-pair structure from the role keys of `legs`.

    Returns tuples of:
        (cur_role, nxt_role, multiplier)

    Supported V1 role structures:

    - CONT:
        {"cur", "nxt"}

    - TS:
        {"near_cur", "near_nxt", "far_cur", "far_nxt"}

    - PS:
        {"a_cur", "a_nxt", "b_cur", "b_nxt"}
    """
    roles = set(legs.keys())

    if roles == {"cur", "nxt"}:
        return [("cur", "nxt", 1.0)]

    if roles == {"near_cur", "near_nxt", "far_cur", "far_nxt"}:
        return [
            ("near_cur", "near_nxt", 1.0),
            ("far_cur", "far_nxt", -1.0),
        ]

    if roles == {"a_cur", "a_nxt", "b_cur", "b_nxt"}:
        return [
            ("a_cur", "a_nxt", 1.0),
            ("b_cur", "b_nxt", -1.0),
        ]

    raise UnsupportedLegRoleStructure(
        f"Unsupported leg role structure: {sorted(roles)!r}"
    )
