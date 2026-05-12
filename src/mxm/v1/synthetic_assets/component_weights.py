"""
Realisation of component-level weights for SyntheticAssetSpec.

This module builds a session-indexed ComponentWeights object from a
SyntheticAssetSpec.

Conceptually:

    index   = session
    columns = component
    values  = signed weight

Scope
-----
- use ComponentContracts to establish the realised MXM business-session grid
- instantiate roll model from spec.weights_rule_id
- build raw front-anchor contract identity on trading-session support
- map anchor contract identity onto MXM business-session support
- compute trading-days-to-LTD for cur/nxt component pairs on that support
- apply static multipliers for supported spread structures
- return a canonical ComponentWeights object

Out of scope
------------
- units, notionals, contract multipliers
- target holdings
- trades / execution / P&L
- persistence of ComponentWeights as a standalone artefact

V1 session-grid policy
----------------------
ComponentWeights inherits its session grid from ComponentContracts.
For each supported component pair:
- the front-anchor contract identity is first realised on product trading-session support
- that anchor identity is then projected onto the common MXM business-session grid
- roll timing is computed in trading-calendar space, evaluated on MXM business-session support
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

from mxm.refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)
from mxm.v1.calendars.mapping import map_business_to_trading_sessions
from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.contract_series import (
    ContractSeries,
    ContractSeriesSpec,
    build_contract_series,
)
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.contracts.selectors import SelectorRule
from mxm.v1.synthetic_assets.component_contracts import (
    ComponentContracts,
    build_component_contracts,
)
from mxm.v1.synthetic_assets.models import ComponentBinding, SyntheticAssetSpec
from mxm.v1.synthetic_assets.rolling.linear_roll import LinearRoll
from mxm.v1.synthetic_assets.rolling.trading_days_to_ltd_on_business_sessions import (
    build_trading_days_to_ltd_on_business_sessions,
)
from mxm.v1.synthetic_assets.weights_rules import parse_weights_rule_id
from mxm.v1.utils.date_utils import coerce_np_day, searchsorted_exact


class UnsupportedWeightsRule(ValueError):
    pass


class UnsupportedComponentStructure(ValueError):
    pass


class MisalignedAnchorSessions(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ComponentWeights:
    """
    Session-indexed unit-less weights by component.

    frame:
        pandas DataFrame indexed by session, with component ids as columns and
        signed floating-point weights as values.
    """

    asset_id: str
    canonical_id: str
    weights_rule_id: str
    frame: pd.DataFrame

    def __post_init__(self) -> None:
        self.validate_schema()

    def validate_schema(self) -> None:
        frame = self.frame

        if isinstance(frame.index, pd.MultiIndex):
            raise ValueError("ComponentWeights.frame index must not be a MultiIndex")

        if frame.index.name != "session":
            raise ValueError(
                f"ComponentWeights.frame index name must be 'session', got {frame.index.name!r}"
            )

        if frame.columns.has_duplicates:
            raise ValueError("ComponentWeights.frame columns must be unique")

        if len(frame.columns) == 0:
            raise ValueError(
                "ComponentWeights.frame must contain at least one component column"
            )

        if not frame.index.is_monotonic_increasing:
            raise ValueError("ComponentWeights.frame index must be sorted by session")

        if frame.index.hasnans:
            raise ValueError(
                "ComponentWeights.frame index contains null session values"
            )

        if frame.isna().any().any():
            raise ValueError("ComponentWeights.frame contains null weight values")

        values = frame.to_numpy()

        if not np.issubdtype(values.dtype, np.number):
            raise TypeError("ComponentWeights.frame values must be numeric")

        if not np.isfinite(values).all():
            raise ValueError("ComponentWeights.frame values must be finite")

    def sessions(self) -> pd.Index:
        """
        Return the realised session index.
        """
        return self.frame.index

    def components(self) -> list[str]:
        """
        Return component ids in column order.
        """
        return list(self.frame.columns)

    def weights_for_session(self, session: np.datetime64) -> pd.DataFrame:
        """
        Return component weights for a specific session.
        """
        return self.frame.loc[[session]].copy()

    def weights_for_component(self, component_id: str) -> pd.DataFrame:
        """
        Return the realised weight series for one component as a single-column
        DataFrame indexed by session.
        """
        return self.frame[[component_id]].copy()


def build_component_weights(
    *,
    spec: SyntheticAssetSpec,
    component_contracts: ComponentContracts,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    mxm_business_calendar: MXMBusinessCalendar,
    refdata_api: RefDataAPI,
) -> ComponentWeights:
    """
    Realise ComponentWeights from SyntheticAssetSpec on the MXM business-session
    grid inherited from ComponentContracts.
    Roll timing is anchored to the front (N=1) series of the same selector
    family as each pair's cur component, not to the selected cur contract's
    own LTD.

    Trading-days-to-LTD is counted in product trading-calendar space, but
    evaluated on the MXM business-session grid inherited from ComponentContracts.
    """
    roll_model = _build_roll_model(spec.weights_rule_id)

    sessions_index = component_contracts.frame.index
    start_session = sessions_index[0]
    end_session = sessions_index[-1]
    sessions = sessions_index.to_numpy()
    component_pairs = infer_component_pairs(spec.components)

    component_weight_columns: dict[str, np.ndarray] = {}

    for cur_component, nxt_component, multiplier in component_pairs:
        raw_anchor_series = _build_raw_anchor_contract_series_for_component(
            component=spec.components[cur_component],
            start_session=start_session,
            end_session=end_session,
            engine=engine,
            calendar_service=calendar_service,
        )

        anchor_contract_ids = _map_anchor_contract_ids_to_business_sessions(
            series=raw_anchor_series,
            business_sessions=sessions,
        )
        tdays = build_trading_days_to_ltd_on_business_sessions(
            product_id=raw_anchor_series.product_id,
            sessions=sessions,
            contract_ids=anchor_contract_ids,
            calendar_service=calendar_service,
            refdata_api=refdata_api,
        )

        if len(tdays.sessions) != len(sessions) or not np.array_equal(
            tdays.sessions,
            sessions,
        ):
            raise MisalignedAnchorSessions(
                f"Anchor sessions differ from ComponentContracts sessions "
                f"for {cur_component!r}"
            )

        w_cur, w_nxt = roll_model.compute_weights_from_bdays_to_ltd(
            bdays_to_ltd=tdays.trading_days_to_ltd
        )
        m = float(multiplier)
        component_weight_columns[cur_component] = m * w_cur
        component_weight_columns[nxt_component] = m * w_nxt

    component_ids = list(spec.components)

    if set(component_weight_columns.keys()) != set(component_ids):
        raise ValueError(
            "Component weight columns do not match spec.components: "
            f"{sorted(component_weight_columns.keys())!r} != {sorted(component_ids)!r}"
        )

    frame = pd.DataFrame(
        component_weight_columns,
        index=sessions_index,
    )
    frame.index.name = "session"
    frame = frame.loc[:, component_ids]
    frame = frame.sort_index()

    return ComponentWeights(
        asset_id=spec.asset_id,
        canonical_id=spec.canonical_id,
        weights_rule_id=spec.weights_rule_id,
        frame=frame,
    )


def _build_raw_anchor_contract_series_for_component(
    *,
    component: ComponentBinding,
    start_session: np.datetime64,
    end_session: np.datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
) -> ContractSeries:
    """
    Build the raw front-anchor ContractSeries for a component on product
    trading-session support.

    The anchor rule keeps the same selector family (same PeriodFilter) but
    forces n=1, so roll timing is driven by the front of the chain rather than
    the selected cur contract's own LTD.
    """
    rule = SelectorRule.from_canonical_relative_id(component.selector_rule_id)
    anchor_rule = SelectorRule(period_filter=rule.period_filter, n=1)

    cs_spec = ContractSeriesSpec(
        product_id=component.product_id,
        rule=anchor_rule,
        start_session=coerce_np_day(start_session),
        end_session=coerce_np_day(end_session),
    )

    return build_contract_series(
        engine=engine,
        calendar_service=calendar_service,
        spec=cs_spec,
    )


def _map_anchor_contract_ids_to_business_sessions(
    *,
    series: ContractSeries,
    business_sessions: np.ndarray,
) -> list[str]:
    """
    Project raw trading-session anchor contract identity onto MXM business
    sessions using business->trading mapping with how='prev'.

    The resulting contract identity is aligned to MXM business-session support,
    while downstream roll timing is still counted in trading-calendar space.
    """
    mapping = map_business_to_trading_sessions(
        business_sessions=business_sessions,
        trading_sessions=series.sessions,
        how="prev",
    )

    out: list[str] = []
    for mapped_session in mapping.mapped_sessions:
        i = searchsorted_exact(series.sessions, mapped_session)
        if i is None:
            raise RuntimeError(
                "Mapped trading session not found in raw anchor ContractSeries: "
                f"product_id={series.product_id!r} "
                f"mapped_session={mapped_session}"
            )
        out.append(series.contract_ids[i])

    return out


def _build_roll_model(weights_rule_id: str) -> LinearRoll:
    """
    Instantiate roll model from weights_rule_id.

    Expected current rule shape:
        WR::KIND=LINEAR_ROLL::ROLL_START_OFFSET=N1::ROLL_DURATION=D
    """
    wr = parse_weights_rule_id(weights_rule_id)

    if wr.kind != "LINEAR_ROLL":
        raise UnsupportedWeightsRule(
            f"Unsupported weights rule kind {wr.kind!r}; "
            "only LINEAR_ROLL is supported in v1"
        )

    return LinearRoll(
        roll_start_offset=wr.roll_start_offset,
        roll_duration=wr.roll_duration,
    )


def infer_component_pairs(
    components: Mapping[str, ComponentBinding],
) -> list[tuple[str, str, float]]:
    """
    Infer roll-pair structure from the component keys of `components`.

    Returns tuples of:
        (cur_component, nxt_component, multiplier)

    Supported V1 component structures:

    - CONT:
        {"cur", "nxt"}

    - TS:
        {"near_cur", "near_nxt", "far_cur", "far_nxt"}

    - PS:
        {"a_cur", "a_nxt", "b_cur", "b_nxt"}
    """
    component_ids = set(components.keys())

    if component_ids == {"cur", "nxt"}:
        return [("cur", "nxt", 1.0)]

    if component_ids == {"near_cur", "near_nxt", "far_cur", "far_nxt"}:
        return [
            ("near_cur", "near_nxt", 1.0),
            ("far_cur", "far_nxt", -1.0),
        ]

    if component_ids == {"a_cur", "a_nxt", "b_cur", "b_nxt"}:
        return [
            ("a_cur", "a_nxt", 1.0),
            ("b_cur", "b_nxt", -1.0),
        ]

    raise UnsupportedComponentStructure(
        f"Unsupported component structure: {sorted(component_ids)!r}"
    )


def realise_component_weights(
    *,
    spec: SyntheticAssetSpec,
    start_session: np.datetime64,
    end_session: np.datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    mxm_business_calendar: MXMBusinessCalendar,
    refdata_api: RefDataAPI,
) -> ComponentWeights:
    component_contracts = build_component_contracts(
        spec=spec,
        start_session=start_session,
        end_session=end_session,
        engine=engine,
        calendar_service=calendar_service,
        mxm_business_calendar=mxm_business_calendar,
    )
    return build_component_weights(
        spec=spec,
        component_contracts=component_contracts,
        engine=engine,
        calendar_service=calendar_service,
        mxm_business_calendar=mxm_business_calendar,
        refdata_api=refdata_api,
    )
