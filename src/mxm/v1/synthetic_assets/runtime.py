from __future__ import annotations

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
"""

from dataclasses import dataclass

import numpy as np
from mxm_refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.synthetic_assets.component_contracts import (
    ComponentContracts,
    build_component_contracts,
)
from mxm.v1.synthetic_assets.component_weights import (
    ComponentWeights,
    build_component_weights,
)
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.target_holdings import (
    TargetHoldings,
    build_target_holdings,
)
from mxm.v1.synthetic_assets.unit_conversion import UnitConverter


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
        spec = self.spec

        if self.component_contracts.asset_id != spec.asset_id:
            raise ValueError(
                f"component_contracts.asset_id={self.component_contracts.asset_id!r} "
                f"does not match spec.asset_id={spec.asset_id!r}"
            )

        if self.component_contracts.canonical_id != spec.canonical_id:
            raise ValueError(
                f"component_contracts.canonical_id={self.component_contracts.canonical_id!r} "
                f"does not match spec.canonical_id={spec.canonical_id!r}"
            )

        if self.component_weights.asset_id != spec.asset_id:
            raise ValueError(
                f"component_weights.asset_id={self.component_weights.asset_id!r} "
                f"does not match spec.asset_id={spec.asset_id!r}"
            )

        if self.component_weights.canonical_id != spec.canonical_id:
            raise ValueError(
                f"component_weights.canonical_id={self.component_weights.canonical_id!r} "
                f"does not match spec.canonical_id={spec.canonical_id!r}"
            )

        if self.component_weights.weights_rule_id != spec.weights_rule_id:
            raise ValueError(
                f"component_weights.weights_rule_id={self.component_weights.weights_rule_id!r} "
                f"does not match spec.weights_rule_id={spec.weights_rule_id!r}"
            )

        if self.target_holdings.asset_id != spec.asset_id:
            raise ValueError(
                f"target_holdings.asset_id={self.target_holdings.asset_id!r} "
                f"does not match spec.asset_id={spec.asset_id!r}"
            )

        if self.target_holdings.canonical_id != spec.canonical_id:
            raise ValueError(
                f"target_holdings.canonical_id={self.target_holdings.canonical_id!r} "
                f"does not match spec.canonical_id={spec.canonical_id!r}"
            )

        spec_component_ids = list(spec.components.keys())
        contract_component_ids = list(self.component_contracts.frame.columns)
        weight_component_ids = list(self.component_weights.frame.columns)

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

        contracts_index = self.component_contracts.frame.index
        weights_index = self.component_weights.frame.index

        if len(contracts_index) != len(weights_index) or not contracts_index.equals(
            weights_index
        ):
            raise ValueError(
                "ComponentContracts and ComponentWeights session indices do not match"
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


def build_synthetic_asset(
    *,
    spec: SyntheticAssetSpec,
    start_session: np.datetime64,
    end_session: np.datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    refdata_api: RefDataAPI,
    unit_converter: UnitConverter,
) -> SyntheticAsset:
    """
    Build a fully realised SyntheticAsset over [start_session, end_session].

    Pipeline:
        SyntheticAssetSpec
            -> ComponentContracts
            -> ComponentWeights
            -> TargetHoldings
            -> SyntheticAsset
    """
    component_contracts = build_component_contracts(
        spec=spec,
        start_session=start_session,
        end_session=end_session,
        engine=engine,
        calendar_service=calendar_service,
    )

    component_weights = build_component_weights(
        spec=spec,
        component_contracts=component_contracts,
        engine=engine,
        calendar_service=calendar_service,
        refdata_api=refdata_api,
    )

    target_holdings = build_target_holdings(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
        refdata_api=refdata_api,
        unit_converter=unit_converter,
    )

    return SyntheticAsset(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
        target_holdings=target_holdings,
    )
