"""
Realisation of component-level contract identities for SyntheticAssetSpec.

This module builds a session-indexed ComponentContracts object from a
SyntheticAssetSpec.

Conceptually:

    index   = MXM business session
    columns = component
    values  = contract_id

Each column represents the realised contract identity state for one
synthetic-asset component across the MXM business-day session grid.

Scope
-----
- realise one raw product ContractSeries per component on trading-session support
- map MXM business sessions onto each component's product trading calendar
- project contract identity onto the business-session surface
- assemble all components into one validated DataFrame
- return a canonical ComponentContracts object

Out of scope
------------
- weights
- unit conversion
- target holdings
- trades / execution / P&L
- persistence of ComponentContracts as a standalone artefact

V1 session-grid policy
----------------------
ComponentContracts is an MXM machine-time surface.

For each component:
- raw contract identity is realised on product trading-session support
- MXM business sessions are mapped onto that trading-session support
- the resulting contract identity state is expressed on the common
  MXM business-day session grid

V1 alignment policy
-------------------
Business-session to trading-session mapping uses:

    how="prev"

That is, each business session is mapped to the greatest trading session
less than or equal to it for the component's product calendar.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd
from numpy import datetime64

from mxm.v1.calendars.mapping import map_business_to_trading_sessions
from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.contract_series import (
    ContractSeries,
    ContractSeriesSpec,
    build_contract_series,
)
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.contracts.relative_ids import parse_canonical_relative_id
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.utils.date_utils import coerce_np_day, searchsorted_exact


class MisalignedComponentSessions(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ComponentContracts:
    """
    Session-indexed realised contract identities for all components of one
    synthetic asset.

    frame:
        pandas DataFrame indexed by MXM business session, with component ids
        as columns and realised contract_id strings as values.
    """

    asset_id: str
    canonical_id: str
    frame: pd.DataFrame

    def __post_init__(self) -> None:
        self.validate_schema()

    def validate_schema(self) -> None:
        frame = self.frame

        if isinstance(frame.index, pd.MultiIndex):
            raise ValueError("ComponentContracts.frame index must not be a MultiIndex")

        if frame.index.name != "session":
            raise ValueError(
                f"ComponentContracts.frame index name must be 'session', got {frame.index.name!r}"
            )

        if frame.columns.has_duplicates:
            raise ValueError("ComponentContracts.frame columns must be unique")

        if len(frame.columns) == 0:
            raise ValueError(
                "ComponentContracts.frame must contain at least one component column"
            )
        if frame.index.hasnans:
            raise ValueError(
                "ComponentContracts.frame index contains null session values"
            )

        if not frame.index.is_monotonic_increasing:
            raise ValueError("ComponentContracts.frame index must be sorted by session")

        if frame.isna().any().any():
            raise ValueError(
                "ComponentContracts.frame contains null contract_id values"
            )

        for column in frame.columns:
            series = frame[column]
            if not series.map(lambda x: isinstance(x, str)).all():
                raise TypeError(
                    f"ComponentContracts column {column!r} must contain only contract_id strings"
                )

    def sessions(self) -> pd.Index:
        """
        Return the realised MXM business-session index.
        """
        return self.frame.index

    def components(self) -> list[str]:
        """
        Return component ids in column order.
        """
        return list(self.frame.columns)

    def contracts_for_session(self, session: datetime64) -> pd.DataFrame:
        """
        Return the realised component contracts for a specific MXM business session.
        """
        return self.frame.loc[[session]].copy()

    def contracts_for_component(self, component_id: str) -> pd.DataFrame:
        """
        Return the realised contract identity series for one component as a
        single-column DataFrame indexed by MXM business session.
        """
        return self.frame[[component_id]].copy()


def build_component_contracts(
    *,
    spec: SyntheticAssetSpec,
    start_session: datetime64,
    end_session: datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    mxm_business_calendar: MXMBusinessCalendar,
) -> ComponentContracts:
    """
    Build realised ComponentContracts for one SyntheticAssetSpec over the
    requested session interval, expressed on MXM business-day support.
    """
    business_sessions = _target_business_sessions(
        mxm_business_calendar=mxm_business_calendar,
        start_session=start_session,
        end_session=end_session,
    )

    raw_contract_series_by_component = _build_contract_series_by_component(
        spec=spec,
        start_session=business_sessions[0],
        end_session=business_sessions[-1],
        engine=engine,
        calendar_service=calendar_service,
    )

    frame = _assemble_component_contracts_frame(
        spec=spec,
        business_sessions=business_sessions,
        contract_series_by_component=raw_contract_series_by_component,
    )

    return ComponentContracts(
        asset_id=spec.asset_id,
        canonical_id=spec.canonical_id,
        frame=frame,
    )


def _target_business_sessions(
    *,
    mxm_business_calendar: MXMBusinessCalendar,
    start_session: datetime64,
    end_session: datetime64,
) -> np.ndarray:
    """
    Derive the target MXM business-session labels for this build call.

    Policy
    ------
    - normalize start to next available business-session label
    - normalize end to previous available business-session label
    - require non-empty closed interval on MXM business-session support
    """
    start_day = start_session.astype("datetime64[D]")
    end_day = end_session.astype("datetime64[D]")

    if np.isnat(start_day):
        raise ValueError("start_session must not be NaT")
    if np.isnat(end_day):
        raise ValueError("end_session must not be NaT")
    labels = mxm_business_calendar.labels
    start_day = cast(np.datetime64, start_session.astype("datetime64[D]"))
    end_day = cast(np.datetime64, end_session.astype("datetime64[D]"))

    start_idx = int(np.searchsorted(labels, start_day, side="left"))
    end_idx = int(np.searchsorted(labels, end_day, side="right")) - 1

    if start_idx >= labels.size:
        raise ValueError(
            f"start_session {start_day} is after last MXM business session {labels[-1]}"
        )

    if end_idx < 0:
        raise ValueError(
            f"end_session {end_day} is before first MXM business session {labels[0]}"
        )

    if start_idx > end_idx:
        raise ValueError(
            "Requested interval contains no MXM business sessions after "
            "boundary normalization"
        )

    return labels[start_idx : end_idx + 1].copy()


def _build_contract_series_by_component(
    *,
    spec: SyntheticAssetSpec,
    start_session: datetime64,
    end_session: datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
) -> dict[str, ContractSeries]:
    """
    Build one raw product ContractSeries per synthetic-asset component on
    trading-session support.
    """
    out: dict[str, ContractSeries] = {}

    for component_id, component in spec.components.items():
        rule = parse_canonical_relative_id(component.selector_rule_id)

        cs_spec = ContractSeriesSpec(
            product_id=component.product_id,
            rule=rule,
            start_session=coerce_np_day(start_session),
            end_session=coerce_np_day(end_session),
        )

        out[component_id] = build_contract_series(
            engine=engine,
            calendar_service=calendar_service,
            spec=cs_spec,
        )

    return out


def _assemble_component_contracts_frame(
    *,
    spec: SyntheticAssetSpec,
    business_sessions: np.ndarray,
    contract_series_by_component: dict[str, ContractSeries],
) -> pd.DataFrame:
    """
    Assemble a canonical business-session x component DataFrame by projecting
    each component's raw trading-session ContractSeries onto the shared MXM
    business-session surface.
    """
    component_ids = list(spec.components.keys())

    if set(component_ids) != set(contract_series_by_component.keys()):
        raise ValueError(
            "Component key mismatch between requested components and realised ContractSeries"
        )

    columns: dict[str, pd.Series] = {}

    for component_id in component_ids:
        cs = contract_series_by_component[component_id]

        mapped_contract_ids = _map_contract_series_to_business_sessions(
            series=cs,
            business_sessions=business_sessions,
        )

        columns[component_id] = pd.Series(
            mapped_contract_ids,
            index=pd.Index(business_sessions, name="session"),
            name=component_id,
        )

    frame = pd.DataFrame(columns)
    frame.index.name = "session"
    frame = frame.sort_index()

    return frame.loc[:, component_ids].copy()


def _map_contract_series_to_business_sessions(
    *,
    series: ContractSeries,
    business_sessions: np.ndarray,
) -> list[str]:
    """
    Project raw trading-session contract identity onto MXM business sessions.

    Policy
    ------
    Business-session to trading-session alignment uses how="prev".
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
                "Mapped trading session not found in ContractSeries sessions: "
                f"product_id={series.product_id!r} "
                f"mapped_session={mapped_session}"
            )
        out.append(series.contract_ids[i])

    return out
