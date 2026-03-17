from __future__ import annotations

from mxm.v1.utils.date_utils import coerce_np_day

"""
MXM V1 — Target Holdings for Synthetic Assets

This module converts realised component weights into concrete target holdings
of futures contracts.

Conceptually:

    (session, contract_id) -> target_holding

The target holding is the contract quantity required to replicate one
synthetic contract of the SyntheticAssetSpec.

Scope
-----
- combine ComponentContracts with ComponentWeights
- apply unit conversion and size scaling
- aggregate from component-level contributions to contract-level holdings
- return a canonical TargetHoldings object

Out of scope
------------
- FX conversion
- trade derivation
- execution
- P&L
- persistence
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd
from mxm_refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)

from mxm.v1.synthetic_assets.component_contracts import ComponentContracts
from mxm.v1.synthetic_assets.component_weights import ComponentWeights
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.unit_conversion import UnitConverter


@dataclass(frozen=True, slots=True)
class TargetHoldings:
    """
    Target holdings for one synthetic asset.

    frame:
        pandas DataFrame indexed by (session, contract_id)
        with exactly one value column: "target_holding"
    """

    asset_id: str
    canonical_id: str
    frame: pd.DataFrame

    def __post_init__(self) -> None:
        self.validate_schema()

    def validate_schema(self) -> None:
        frame = self.frame

        if not isinstance(frame.index, pd.MultiIndex):
            raise ValueError("TargetHoldings.frame index must be a pandas MultiIndex")

        if frame.index.nlevels != 2:
            raise ValueError("TargetHoldings.frame index must have exactly two levels")

        expected_names = ["session", "contract_id"]
        if list(frame.index.names) != expected_names:
            raise ValueError(
                f"TargetHoldings.frame index names must be {expected_names}, "
                f"got {list(frame.index.names)}"
            )

        expected_columns = ["target_holding"]
        if list(frame.columns) != expected_columns:
            raise ValueError(
                f"TargetHoldings.frame must contain exactly one column "
                f"{expected_columns}, got {list(frame.columns)}"
            )

        if frame.index.has_duplicates:
            raise ValueError(
                "TargetHoldings.frame index contains duplicate "
                "(session, contract_id) rows"
            )

        if np.any(frame.index.get_level_values("session").isna()):
            raise ValueError("TargetHoldings.frame session index contains null values")

        if np.any(frame.index.get_level_values("contract_id").isna()):
            raise ValueError(
                "TargetHoldings.frame contract_id index contains null values"
            )

        if not frame.index.is_monotonic_increasing:
            raise ValueError(
                "TargetHoldings.frame index must be sorted by (session, contract_id)"
            )

        if frame["target_holding"].isna().any():
            raise ValueError("TargetHoldings.frame target_holding contains null values")

        values = frame["target_holding"].to_numpy()
        if not np.issubdtype(values.dtype, np.number):
            raise TypeError("TargetHoldings.frame target_holding must be numeric")

        if not np.isfinite(values).all():
            raise ValueError(
                "TargetHoldings.frame target_holding must contain only finite values"
            )

    def holdings_for_session(self, session: np.datetime64) -> pd.DataFrame:
        """
        Return the target holdings rows for a specific session.
        """
        session_day = coerce_np_day(session)
        out = self.frame.xs(session_day, level="session", drop_level=False)
        if not isinstance(out, pd.DataFrame):
            raise TypeError("expected DataFrame from holdings_for_session()")
        return out

    def holdings_for_contract(self, contract_id: str) -> pd.DataFrame:
        """
        Return the target holdings rows for a specific contract.
        """
        out = self.frame.xs(contract_id, level="contract_id", drop_level=False)
        if not isinstance(out, pd.DataFrame):
            raise TypeError("expected DataFrame from holdings_for_contract()")
        return out


def build_target_holdings(
    *,
    spec: SyntheticAssetSpec,
    component_contracts: ComponentContracts,
    component_weights: ComponentWeights,
    refdata_api: RefDataAPI,
    unit_converter: UnitConverter,
) -> TargetHoldings:
    """
    Build target holdings for one synthetic asset.

    Notes
    -----
    - ComponentWeights are already signed correctly for supported V1 spread
      structures because build_component_weights() has already applied the
      static multipliers.
    - This function therefore does not infer sign from component names.
    """
    _validate_component_inputs_match_spec(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
    )

    contracts_long = _stack_component_contracts(component_contracts)
    weights_long = _stack_component_weights(component_weights)

    joined = contracts_long.merge(
        weights_long,
        on=["session", "component"],
        how="inner",
        validate="one_to_one",
    )

    if joined.empty:
        raise ValueError(
            "No component contract/weight rows available to build holdings"
        )

    contract_meta = _build_contract_metadata_frame(
        contract_ids=joined["contract_id"].unique().tolist(),
        refdata_api=refdata_api,
        unit_converter=unit_converter,
        synthetic_unit=spec.unit,
    )

    joined = joined.merge(
        contract_meta,
        on="contract_id",
        how="left",
        validate="many_to_one",
    )

    if joined[["contract_size", "unit_factor"]].isna().any().any():
        raise ValueError("Missing contract metadata or unit conversion factor")

    joined["target_holding"] = (
        joined["weight"].astype(float)
        * joined["unit_factor"].astype(float)
        * float(spec.size)
        / joined["contract_size"].astype(float)
    )

    out = (
        joined.groupby(["session", "contract_id"], sort=True, as_index=True)[
            "target_holding"
        ]
        .sum()
        .to_frame()
        .sort_index()
    )
    out.index = out.index.set_names(["session", "contract_id"])

    return TargetHoldings(
        asset_id=spec.asset_id,
        canonical_id=spec.canonical_id,
        frame=out,
    )


def _validate_component_inputs_match_spec(
    *,
    spec: SyntheticAssetSpec,
    component_contracts: ComponentContracts,
    component_weights: ComponentWeights,
) -> None:
    if component_contracts.asset_id != spec.asset_id:
        raise ValueError(
            f"component_contracts.asset_id={component_contracts.asset_id!r} "
            f"does not match spec.asset_id={spec.asset_id!r}"
        )

    if component_contracts.canonical_id != spec.canonical_id:
        raise ValueError(
            f"component_contracts.canonical_id={component_contracts.canonical_id!r} "
            f"does not match spec.canonical_id={spec.canonical_id!r}"
        )

    if component_weights.asset_id != spec.asset_id:
        raise ValueError(
            f"component_weights.asset_id={component_weights.asset_id!r} "
            f"does not match spec.asset_id={spec.asset_id!r}"
        )

    if component_weights.canonical_id != spec.canonical_id:
        raise ValueError(
            f"component_weights.canonical_id={component_weights.canonical_id!r} "
            f"does not match spec.canonical_id={spec.canonical_id!r}"
        )

    if component_weights.weights_rule_id != spec.weights_rule_id:
        raise ValueError(
            f"component_weights.weights_rule_id={component_weights.weights_rule_id!r} "
            f"does not match spec.weights_rule_id={spec.weights_rule_id!r}"
        )

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

    contracts_index = component_contracts.frame.index
    weights_index = component_weights.frame.index

    if len(contracts_index) != len(weights_index) or not contracts_index.equals(
        weights_index
    ):
        raise ValueError(
            "ComponentContracts and ComponentWeights session indices do not match"
        )


def _stack_component_contracts(component_contracts: ComponentContracts) -> pd.DataFrame:
    """
    Convert session x component -> contract_id into long form:

        session | component | contract_id
    """
    series = component_contracts.frame.stack()
    series.index = series.index.set_names(["session", "component"])
    out = series.rename("contract_id").reset_index()
    return out


def _stack_component_weights(component_weights: ComponentWeights) -> pd.DataFrame:
    """
    Convert session x component -> weight into long form:

        session | component | weight
    """
    series = component_weights.frame.stack()
    series.index = series.index.set_names(["session", "component"])
    out = series.rename("weight").reset_index()
    return out


def _build_contract_metadata_frame(
    *,
    contract_ids: list[str],
    refdata_api: RefDataAPI,
    unit_converter: UnitConverter,
    synthetic_unit: str,
) -> pd.DataFrame:
    """
    Build a contract metadata table with columns:

        contract_id
        contract_size
        contract_unit
        unit_factor
    """
    rows: list[dict[str, object]] = []

    for contract_id in contract_ids:
        contract = refdata_api.get_contract_by_id(contract_id)
        contract_unit = contract.unit
        contract_size = float(contract.contract_size)

        unit_factor = float(
            unit_converter.conversion_factor(
                from_unit=synthetic_unit,
                to_unit=contract_unit,
            )
        )

        rows.append(
            {
                "contract_id": contract_id,
                "contract_size": contract_size,
                "contract_unit": contract_unit,
                "unit_factor": unit_factor,
            }
        )

    return pd.DataFrame(
        rows,
        columns=["contract_id", "contract_size", "contract_unit", "unit_factor"],
    )
