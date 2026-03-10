from __future__ import annotations

"""
MXM V1 — Target Holdings for Synthetic Assets

This module converts a realised WeightsSeries into concrete target holdings
of futures contracts.

Conceptually:

    (session, contract_id) -> target_holding

The target holding is the contract quantity required to replicate one
synthetic contract of the SyntheticAssetSpec.

Scope
-----
Session 27 scope:

- reuse realised role structure from SyntheticAssetSpec
- realise ContractSeries by role over the WeightsSeries session range
- combine role weights with realised contract_ids
- apply unit conversion and size scaling
- aggregate to (session, contract_id)
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
from typing import cast

import numpy as np
import pandas as pd
from mxm_refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.unit_conversion import UnitConverter
from mxm.v1.synthetic_assets.weights_series import (
    WeightsSeries,
    assert_identical_sessions,
    build_contract_series_by_role,
)


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
            raise ValueError("frame.index must be a pandas MultiIndex")

        if frame.index.nlevels != 2:
            raise ValueError("frame.index must have exactly two levels")

        expected_names = ["session", "contract_id"]
        if list(frame.index.names) != expected_names:
            raise ValueError(
                f"frame.index names must be {expected_names}, got {list(frame.index.names)}"
            )

        expected_columns = ["target_holding"]
        if list(frame.columns) != expected_columns:
            raise ValueError(
                f"frame must contain exactly one column {expected_columns}, got {list(frame.columns)}"
            )

        if frame.index.has_duplicates:
            raise ValueError(
                "frame index contains duplicate (session, contract_id) rows"
            )

        if not frame.index.is_monotonic_increasing:
            raise ValueError("frame index must be sorted by (session, contract_id)")

        if frame.index.get_level_values("session").isna().any():
            raise ValueError("session index contains null values")

        if frame.index.get_level_values("contract_id").isna().any():
            raise ValueError("contract_id index contains null values")

        if frame["target_holding"].isna().any():
            raise ValueError("target_holding contains null values")

        values = frame["target_holding"].to_numpy()
        if not np.issubdtype(values.dtype, np.number):
            raise TypeError("target_holding must be numeric")

        if not np.isfinite(values).all():
            raise ValueError("target_holding must contain only finite values")

    def holdings_for_session(self, session: np.datetime64) -> pd.DataFrame:
        out = self.frame.xs(session, level="session", drop_level=False)
        if not isinstance(out, pd.DataFrame):
            raise TypeError("expected DataFrame from holdings_for_session()")
        return cast(pd.DataFrame, out)

    def holdings_for_contract(self, contract_id: str) -> pd.DataFrame:
        out = self.frame.xs(contract_id, level="contract_id", drop_level=False)
        if not isinstance(out, pd.DataFrame):
            raise TypeError("expected DataFrame from holdings_for_contract()")
        return cast(pd.DataFrame, out)


def build_target_holdings(
    *,
    spec: SyntheticAssetSpec,
    weights: WeightsSeries,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    refdata_api: RefDataAPI,
    unit_converter: UnitConverter,
) -> TargetHoldings:
    """
    Build target holdings for one synthetic asset over the WeightsSeries sessions.

    Notes
    -----
    - weights.role_weights are already signed correctly for supported V1 spread
      structures because build_weights_series() has already applied the static
      spread multipliers.
    - this function therefore does not infer sign from role names.
    """
    _validate_weights_match_spec(spec=spec, weights=weights)

    start_session = weights.sessions[0]
    end_session = weights.sessions[-1]

    contract_series_by_role = build_contract_series_by_role(
        spec=spec,
        start_session=start_session,
        end_session=end_session,
        engine=engine,
        calendar_service=calendar_service,
    )

    realised_sessions = assert_identical_sessions(contract_series_by_role.values())
    if realised_sessions.shape != weights.sessions.shape or not np.array_equal(
        realised_sessions, weights.sessions
    ):
        raise ValueError(
            "WeightsSeries sessions do not match realised ContractSeries sessions"
        )

    role_frames: list[pd.DataFrame] = []

    for role, leg in spec.legs.items():
        cs = contract_series_by_role[role]
        role_weight = weights.role_weights[role]

        contract_ids = cs.contract_ids
        if contract_ids.shape != weights.sessions.shape:
            raise ValueError(
                f"ContractSeries contract_ids shape mismatch for role {role!r}"
            )

        rows = []
        for i, session in enumerate(weights.sessions):
            contract_id = str(contract_ids[i])

            contract = refdata_api.get_contract(contract_id)  # adjust to your real API
            contract_unit = contract.unit
            contract_size = float(contract.contract_size)

            unit_factor = float(
                unit_converter.conversion_factor(
                    from_unit=spec.unit,
                    to_unit=contract_unit,
                )
            )

            target_holding = (
                float(role_weight[i]) * unit_factor * float(spec.size) / contract_size
            )

            rows.append(
                {
                    "session": session,
                    "contract_id": contract_id,
                    "target_holding": target_holding,
                }
            )

        role_frames.append(
            pd.DataFrame(rows, columns=["session", "contract_id", "target_holding"])
        )

    if not role_frames:
        raise ValueError(f"synthetic asset {spec.asset_id!r} has no legs")

    frame = pd.concat(role_frames, axis=0, ignore_index=True)

    out = (
        frame.groupby(["session", "contract_id"], sort=True, as_index=True)[
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


def _validate_weights_match_spec(
    *,
    spec: SyntheticAssetSpec,
    weights: WeightsSeries,
) -> None:
    if weights.asset_id != spec.asset_id:
        raise ValueError(
            f"weights.asset_id={weights.asset_id!r} does not match spec.asset_id={spec.asset_id!r}"
        )

    if weights.canonical_id != spec.canonical_id:
        raise ValueError(
            f"weights.canonical_id={weights.canonical_id!r} does not match "
            f"spec.canonical_id={spec.canonical_id!r}"
        )

    if weights.weights_rule_id != spec.weights_rule_id:
        raise ValueError(
            f"weights.weights_rule_id={weights.weights_rule_id!r} does not match "
            f"spec.weights_rule_id={spec.weights_rule_id!r}"
        )

    spec_roles = set(spec.legs.keys())
    weight_roles = set(weights.role_weights.keys())

    if spec_roles != weight_roles:
        raise ValueError(
            f"weights roles {sorted(weight_roles)!r} do not match spec roles {sorted(spec_roles)!r}"
        )

    if weights.sessions.ndim != 1:
        raise ValueError("weights.sessions must be one-dimensional")

    if len(weights.sessions) == 0:
        raise ValueError("weights.sessions must not be empty")

    for role, arr in weights.role_weights.items():
        if arr.ndim != 1:
            raise ValueError(f"weights for role {role!r} must be one-dimensional")
        if arr.shape != weights.sessions.shape:
            raise ValueError(
                f"weights shape mismatch for role {role!r}: "
                f"{arr.shape!r} != {weights.sessions.shape!r}"
            )
        if not np.isfinite(arr).all():
            raise ValueError(f"weights for role {role!r} contain non-finite values")
