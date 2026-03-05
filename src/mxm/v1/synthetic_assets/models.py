# mxm/v1/synthetic_assets/models.py
from __future__ import annotations

"""
mxm.v1.synthetic_assets.models
==============================

Domain models for Synthetic Asset instrument definitions (MXM V1).

This module defines the canonical, static specification objects for
synthetic assets. These models represent *instrument definitions*,
not time-indexed trading artefacts.

Architectural Position
----------------------

Contracts subsystem:
    SelectorRule
    ContractSeries  (identity over sessions)

Synthetic Assets (this module):
    SyntheticAssetSpec
    LegBinding
    SyntheticAsset (runtime wrapper)

Strategies (later layers):
    Signals
    Risk overlays
    Portfolio construction
    Execution
    P&L

Core Concepts
-------------

SyntheticAssetSpec
    A deterministic replication definition composed of:

        - asset_id
        - canonical_id
        - base_currency
        - unit (semantic synthetic unit)
        - weights_rule_id (product-agnostic rule identifier)
        - legs: mapping role -> LegBinding

LegBinding
    Binds a *role* to a concrete leg defined by:

        - product_id
        - selector_rule_id (canonical relative id)

    Contract identity over time is realised later as:
        (product_id, selector_rule_id) -> ContractSeries

Roles
-----

Legs are keyed by role (string identifiers). Weight rules operate over
roles, not products. This allows weight rules to remain generic and
reusable across products, while the synthetic asset specification binds
those roles to concrete products and selector rules.

Separation of Concerns
----------------------

These models are:

    - Deterministic
    - Stateless
    - Fully serialisable
    - Registry-backed

They do NOT contain:

    - ContractSeries realisation
    - Weight time series
    - FX conversion
    - Contract multiplier logic
    - Target holdings
    - Trades
    - Execution
    - P&L
    - Storage pipelines

All time-indexed surfaces are constructed in later sessions by combining:

    - SyntheticAssetSpec
    - ContractSeries per role
    - Trading calendars
    - Instrument metadata

After Session 24, the identity and structure of a synthetic asset are
considered locked. Subsequent layers may derive time-series artefacts,
but must not mutate the instrument-definition model defined here.
"""
import re
from dataclasses import dataclass
from typing import Mapping

from mxm.v1.synthetic_assets.canonical_ids import validate_synthetic_asset_canonical_id

_ASSET_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_ROLE_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_asset_id(value: str, *, field: str) -> None:
    if not _ASSET_ID_RE.fullmatch(value):
        raise ValueError(f"{field} must match {_ASSET_ID_RE.pattern}; got {value!r}")

    # Optional hygiene: avoid accidental namespace-like double underscores.
    if "__" in value:
        raise ValueError(f"{field} must not contain '__'; got {value!r}")


def _validate_role(role: str) -> None:
    if not _ROLE_RE.fullmatch(role):
        raise ValueError(f"leg role {role!r} must match {_ROLE_RE.pattern}")

    if "__" in role:
        raise ValueError(f"leg role {role!r} must not contain '__'")


@dataclass(frozen=True, slots=True)
class LegBinding:
    """
    Role-bound leg definition.

    A leg is not an instrument. It is a binding from a role name to a
    product_id and a selector-rule id (canonical relative id).

    Contract identity over time is realised later via ContractSeries:
        (product_id, selector_rule_id) + sessions -> contract_id[session]
    """

    product_id: str
    selector_rule_id: str  # canonical_relative_id string


@dataclass(frozen=True, slots=True)
class SyntheticAssetSpec:
    """
    Authoritative, static specification for a Synthetic Asset instrument.

    Locked model:
        SyntheticAssetSpec(
            asset_id: str,
            canonical_id: str,
            currency: str,
            unit: str,
            size: int,
            weights_rule_id: str,
            legs: Mapping[str, LegBinding]   # role -> binding
        )

    Notes:
    - weights_rule_id is product-agnostic; it operates over roles.
    - legs bind roles to concrete (product_id, selector_rule_id).
    - No time series surfaces exist here (weights/holdings/trades/etc.).
    """

    asset_id: str
    canonical_id: str
    currency: str
    unit: str
    size: float
    weights_rule_id: str
    legs: Mapping[str, LegBinding]

    def __post_init__(self) -> None:
        validate_synthetic_asset_canonical_id(self.canonical_id)
        _validate_asset_id(self.asset_id, field="SyntheticAssetSpec.asset_id")

        if len(self.legs) == 0:
            raise ValueError("SyntheticAssetSpec.legs must be non-empty")

        # Validate roles + bindings.
        for role, _ in self.legs.items():
            _validate_role(role)

    def leg_key(self, role: str) -> str:
        """
        Canonical string key for a role-bound leg.

        This is suitable for logging / audit / debug surfaces. It is NOT a rule id.
        """
        binding = self.legs[role]
        return f"{binding.product_id}.{binding.selector_rule_id}"


@dataclass(frozen=True, slots=True)
class SyntheticAsset:
    """
    Runtime wrapper for a Synthetic Asset instrument.

    In Session 24 this is intentionally thin: it carries only the spec.
    Derived surfaces (ContractSeries, weights, holdings) are attached by
    builders in later sessions.
    """

    spec: SyntheticAssetSpec
