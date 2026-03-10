from __future__ import annotations

"""
Realisation of component-level contract identities for SyntheticAssetSpec.

This module builds a session-indexed ComponentContracts object from a
SyntheticAssetSpec.

Conceptually:

    index   = session
    columns = component
    values  = contract_id

Each column represents the realised contract identity selected for one
synthetic-asset component across the session grid.

Scope
-----
- realise one ContractSeries per component
- assemble them into one validated DataFrame
- enforce identical session support across all components
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
All component ContractSeries in one synthetic asset must have identical
sessions.

This is expected to hold for current V1 assets:
- CONT
- TS
- PS

If realised component sessions differ, this module raises.
Cross-calendar alignment is out of scope for v1.
"""

from dataclasses import dataclass

import pandas as pd
from numpy import datetime64

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.contract_series import (
    ContractSeries,
    ContractSeriesSpec,
    build_contract_series,
)
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.contracts.relative_ids import parse_canonical_relative_id
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.utils.date_utils import coerce_np_day


class MisalignedComponentSessions(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ComponentContracts:
    """
    Session-indexed realised contract identities for all components of one
    synthetic asset.

    frame:
        pandas DataFrame indexed by session, with component ids as columns and
        realised contract_id strings as values.
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

        # All values should be strings / object-like contract ids.
        # We keep this check light to avoid over-constraining pandas dtypes.
        for column in frame.columns:
            series = frame[column]
            if not series.map(lambda x: isinstance(x, str)).all():
                raise TypeError(
                    f"ComponentContracts column {column!r} must contain only contract_id strings"
                )

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

    def contracts_for_session(self, session: datetime64) -> pd.DataFrame:
        """
        Return the realised component contracts for a specific session.
        """
        return self.frame.loc[[session]].copy()

    def contracts_for_component(self, component_id: str) -> pd.DataFrame:
        """
        Return the realised contract identity series for one component as a
        single-column DataFrame indexed by session.
        """
        return self.frame[[component_id]].copy()


def build_component_contracts(
    *,
    spec: SyntheticAssetSpec,
    start_session: datetime64,
    end_session: datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
) -> ComponentContracts:
    """
    Build realised ComponentContracts for one SyntheticAssetSpec over
    [start_session, end_session].
    """
    contract_series_by_component = _build_contract_series_by_component(
        spec=spec,
        start_session=start_session,
        end_session=end_session,
        engine=engine,
        calendar_service=calendar_service,
    )

    frame = _assemble_component_contracts_frame(
        component_ids=list(spec.components.keys()),
        contract_series_by_component=contract_series_by_component,
    )

    return ComponentContracts(
        asset_id=spec.asset_id,
        canonical_id=spec.canonical_id,
        frame=frame,
    )


def _build_contract_series_by_component(
    *,
    spec: SyntheticAssetSpec,
    start_session: datetime64,
    end_session: datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
) -> dict[str, ContractSeries]:
    """
    Build one ContractSeries per synthetic-asset component.
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
    component_ids: list[str],
    contract_series_by_component: dict[str, ContractSeries],
) -> pd.DataFrame:
    """
    Assemble a canonical session x component DataFrame from per-component
    ContractSeries objects.

    Raises
    ------
    MisalignedComponentSessions
        If component ContractSeries do not share identical session support.
    """

    if set(component_ids) != set(contract_series_by_component.keys()):
        raise ValueError(
            "Component key mismatch between requested components and realised ContractSeries"
        )

    first_component = component_ids[0]
    first_series = contract_series_by_component[first_component]
    sessions0 = first_series.sessions

    columns: dict[str, pd.Series] = {}

    for component_id in component_ids:
        cs = contract_series_by_component[component_id]

        if sessions0.shape != cs.sessions.shape:
            raise MisalignedComponentSessions(
                "Synthetic-asset component ContractSeries sessions are not identical; "
                "cross-calendar alignment is not supported in v1"
            )

        # numpy comparison kept explicit because sessions are np.datetime64 arrays
        if not (cs.sessions == sessions0).all():
            raise MisalignedComponentSessions(
                "Synthetic-asset component ContractSeries sessions are not identical; "
                "cross-calendar alignment is not supported in v1"
            )

        columns[component_id] = pd.Series(
            cs.contract_ids,
            index=pd.Index(cs.sessions, name="session"),
            name=component_id,
        )

    frame = pd.DataFrame(columns)
    frame.index.name = "session"
    frame = frame.sort_index()

    # Ensure canonical column order from spec.components iteration order
    out = frame.loc[:, component_ids].copy()

    return out
