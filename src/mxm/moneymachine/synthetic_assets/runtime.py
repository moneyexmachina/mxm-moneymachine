"""
Runtime wrapper and orchestration for realised synthetic assets.

This module defines the realised SyntheticAsset object, which bundles:

- the static SyntheticAssetSpec
- realised ComponentContracts
- realised ComponentWeights
- realised TargetHoldings

It also provides a convenience builder that constructs the full realised
synthetic asset over a session range.

Architectural role
------------------
This module does not implement the individual realisation steps itself.
Instead it orchestrates the specialised builders from:

- component_contracts.py
- component_weights.py
- target_holdings.py

Session-grid semantics
----------------------
The realised synthetic asset is now expressed on the MXM business-calendar
session surface.

Concretely:
- ComponentContracts is built on MXM business-day support
- ComponentWeights inherits that same support
- TargetHoldings is derived from those aligned realised surfaces and therefore
  also inherits the same support
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mxm.moneymachine.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.moneymachine.calendars.service import TradingCalendarService
from mxm.moneymachine.contracts.engine import ContractSelectorEngine
from mxm.moneymachine.synthetic_assets.component_contracts import (
    ComponentContracts,
    build_component_contracts,
)
from mxm.moneymachine.synthetic_assets.component_weights import (
    ComponentWeights,
    build_component_weights,
)
from mxm.moneymachine.synthetic_assets.models import SyntheticAssetSpec
from mxm.moneymachine.synthetic_assets.target_holdings import (
    TargetHoldings,
    build_target_holdings,
)
from mxm.moneymachine.synthetic_assets.unit_conversion import UnitConverter
from mxm.refdata import RefDataReader


@dataclass(frozen=True, slots=True)
class SyntheticAsset:
    """
    Fully realised synthetic asset over a concrete session range.

    A SyntheticAsset bundles the authoritative static specification together
    with the realised datasets required to understand and trade the asset:

    - ComponentContracts
    - ComponentWeights
    - TargetHoldings
    """

    spec: SyntheticAssetSpec
    component_contracts: ComponentContracts
    component_weights: ComponentWeights
    target_holdings: TargetHoldings

    def __post_init__(self) -> None:
        self.validate_alignment()

    def validate_alignment(self) -> None:
        """
        Validate that all realised datasets belong to the same synthetic asset
        and are mutually aligned.
        """
        _validate_component_contracts_identity(
            spec=self.spec,
            component_contracts=self.component_contracts,
        )
        _validate_component_weights_identity(
            spec=self.spec,
            component_weights=self.component_weights,
        )
        _validate_target_holdings_identity(
            spec=self.spec,
            target_holdings=self.target_holdings,
        )
        _validate_component_column_alignment(
            spec=self.spec,
            component_contracts=self.component_contracts,
            component_weights=self.component_weights,
        )
        _validate_component_session_alignment(
            component_contracts=self.component_contracts,
            component_weights=self.component_weights,
        )

    def first_session(self) -> np.datetime64:
        """
        Return the first realised session.
        """
        return self.component_contracts.frame.index[0]

    def last_session(self) -> np.datetime64:
        """
        Return the last realised session.
        """
        return self.component_contracts.frame.index[-1]


def _validate_component_contracts_identity(
    *,
    spec: SyntheticAssetSpec,
    component_contracts: ComponentContracts,
) -> None:
    _validate_field_matches(
        lhs_name="component_contracts.asset_id",
        lhs_value=component_contracts.asset_id,
        rhs_name="spec.asset_id",
        rhs_value=spec.asset_id,
    )
    _validate_field_matches(
        lhs_name="component_contracts.canonical_id",
        lhs_value=component_contracts.canonical_id,
        rhs_name="spec.canonical_id",
        rhs_value=spec.canonical_id,
    )


def _validate_component_weights_identity(
    *,
    spec: SyntheticAssetSpec,
    component_weights: ComponentWeights,
) -> None:
    _validate_field_matches(
        lhs_name="component_weights.asset_id",
        lhs_value=component_weights.asset_id,
        rhs_name="spec.asset_id",
        rhs_value=spec.asset_id,
    )
    _validate_field_matches(
        lhs_name="component_weights.canonical_id",
        lhs_value=component_weights.canonical_id,
        rhs_name="spec.canonical_id",
        rhs_value=spec.canonical_id,
    )
    _validate_field_matches(
        lhs_name="component_weights.weights_rule_id",
        lhs_value=component_weights.weights_rule_id,
        rhs_name="spec.weights_rule_id",
        rhs_value=spec.weights_rule_id,
    )


def _validate_target_holdings_identity(
    *,
    spec: SyntheticAssetSpec,
    target_holdings: TargetHoldings,
) -> None:
    _validate_field_matches(
        lhs_name="target_holdings.asset_id",
        lhs_value=target_holdings.asset_id,
        rhs_name="spec.asset_id",
        rhs_value=spec.asset_id,
    )
    _validate_field_matches(
        lhs_name="target_holdings.canonical_id",
        lhs_value=target_holdings.canonical_id,
        rhs_name="spec.canonical_id",
        rhs_value=spec.canonical_id,
    )


def _validate_field_matches(
    *,
    lhs_name: str,
    lhs_value: str,
    rhs_name: str,
    rhs_value: str,
) -> None:
    if lhs_value != rhs_value:
        raise ValueError(
            f"{lhs_name}={lhs_value!r} does not match {rhs_name}={rhs_value!r}"
        )


def _validate_component_column_alignment(
    *,
    spec: SyntheticAssetSpec,
    component_contracts: ComponentContracts,
    component_weights: ComponentWeights,
) -> None:
    spec_component_ids = list(spec.components.keys())
    contract_component_ids = list(component_contracts.frame.columns)
    weight_component_ids = list(component_weights.frame.columns)

    if contract_component_ids != spec_component_ids:
        raise ValueError(
            "ComponentContracts columns do not match spec.components order: "
            f"{contract_component_ids!r} != {spec_component_ids!r}"
        )

    if weight_component_ids != spec_component_ids:
        raise ValueError(
            "ComponentWeights columns do not match spec.components order: "
            f"{weight_component_ids!r} != {spec_component_ids!r}"
        )


def _validate_component_session_alignment(
    *,
    component_contracts: ComponentContracts,
    component_weights: ComponentWeights,
) -> None:
    contracts_index = component_contracts.frame.index
    weights_index = component_weights.frame.index

    if len(contracts_index) != len(weights_index) or not contracts_index.equals(
        weights_index
    ):
        raise ValueError(
            "ComponentContracts and ComponentWeights session indices do not match"
        )


def build_synthetic_asset(
    *,
    spec: SyntheticAssetSpec,
    start_session: np.datetime64,
    end_session: np.datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    mxm_business_calendar: MXMBusinessCalendar,
    refdata_reader: RefDataReader,
    unit_converter: UnitConverter,
) -> SyntheticAsset:
    """
    Build a fully realised SyntheticAsset over the requested session interval.

    Pipeline:
        SyntheticAssetSpec
            -> ComponentContracts        (MXM business-session support)
            -> ComponentWeights          (inherits same support)
            -> TargetHoldings            (inherits same support)
            -> SyntheticAsset
    """
    component_contracts = build_component_contracts(
        spec=spec,
        start_session=start_session,
        end_session=end_session,
        engine=engine,
        calendar_service=calendar_service,
        mxm_business_calendar=mxm_business_calendar,
    )

    component_weights = build_component_weights(
        spec=spec,
        component_contracts=component_contracts,
        engine=engine,
        calendar_service=calendar_service,
        mxm_business_calendar=mxm_business_calendar,
        refdata_reader=refdata_reader,
    )

    target_holdings = build_target_holdings(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
        refdata_reader=refdata_reader,
        unit_converter=unit_converter,
    )

    return SyntheticAsset(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
        target_holdings=target_holdings,
    )
