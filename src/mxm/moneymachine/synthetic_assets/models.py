"""
mxm.v1.synthetic_assets.models
==============================

Domain models for Synthetic Asset instrument definitions (MXM V1).

This module defines the canonical, static specification objects for
synthetic assets. These models represent instrument definitions,
not time-indexed trading artefacts.

Architectural Position
----------------------

Contracts subsystem:
    SelectorRule
    ContractsSeries  (identity over sessions)

Synthetic Assets (this module):
    SyntheticAssetSpec
    Components
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
        - currency
        - unit (semantic synthetic unit)
        - weights_rule_id (product-agnostic rule identifier)
        - components: mapping component_id -> ComponentBinding

ComponentBinding
    Binds a component to a concrete expression, defined by:

        - product_id
        - selector_rule_id (canonical relative id)

    Contract identity over time is realised later as:
        (product_id, selector_rule_id) -> ComponentContracts

Components
----------

A component is keyed by component_id (string identifier). Weight rules operate
over components, not products. This allows weight rules to remain generic and
reusable across products, while the synthetic asset specification binds those
components to concrete products and selector rules.

Separation of Concerns
----------------------

These models are:

    - Deterministic
    - Stateless
    - Fully serialisable
    - Registry-backed

They do NOT contain:

    - ComponentContracts realisation
    - ComponentWeights time series
    - FX conversion
    - Contract multiplier logic
    - Target holdings
    - Trades
    - Execution
    - P&L
    - Storage pipelines

All time-indexed surfaces are constructed in later sessions by combining:

    - SyntheticAssetSpec
    - ComponentContracts per component
    - Trading calendars
    - Instrument metadata
"""

from __future__ import annotations

# mxm/v1/synthetic_assets/models.py
import re
from collections.abc import Mapping
from dataclasses import dataclass

from mxm.moneymachine.synthetic_assets.canonical_ids import (
    validate_synthetic_asset_canonical_id,
)

_ASSET_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")
_COMPONENT_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


def _validate_asset_id(value: str, *, field: str) -> None:
    if not _ASSET_ID_RE.fullmatch(value):
        raise ValueError(f"{field} must match {_ASSET_ID_RE.pattern}; got {value!r}")

    # Optional hygiene: avoid accidental namespace-like double underscores.
    if "__" in value:
        raise ValueError(f"{field} must not contain '__'; got {value!r}")


def _validate_component_id(component_id: str) -> None:
    if not _COMPONENT_ID_RE.fullmatch(component_id):
        raise ValueError(
            f"component_id {component_id!r} must match {_COMPONENT_ID_RE.pattern}"
        )

    if "__" in component_id:
        raise ValueError(f"component_id {component_id!r} must not contain '__'")


@dataclass(frozen=True, slots=True)
class ComponentBinding:
    """
    Static binding of a synthetic-asset component.

    A ComponentBinding binds a component_id to:

        - product_id
        - selector_rule_id

    Contract identity over time is realised later via ContractsSeries:

        (product_id, selector_rule_id) + sessions -> contract_id[session]
    """

    product_id: str
    selector_rule_id: str  # canonical_relative_id string

    @property
    def component_spec_id(self) -> str:
        return f"{self.product_id}.{self.selector_rule_id}"


@dataclass(frozen=True, slots=True)
class SyntheticAssetSpec:
    """
    Authoritative, static specification for a Synthetic Asset.

    Locked model:
        SyntheticAssetSpec(
            asset_id: str,
            canonical_id: str,
            currency: str,
            unit: str,
            size: float,
            weights_rule_id: str,
            components: Mapping[str, ComponentBinding]
        )

    Notes:
    - weights_rule_id is product-agnostic; it operates over components.
    - ComponentBindings bind component_ids to concrete
      (product_id, selector_rule_id) pairs.
    - No time series surfaces exist here
      (contracts/weights/holdings/trades/etc.).
    """

    asset_id: str
    canonical_id: str
    currency: str
    unit: str
    size: float
    weights_rule_id: str
    components: Mapping[str, ComponentBinding]

    def __post_init__(self) -> None:
        validate_synthetic_asset_canonical_id(self.canonical_id)
        _validate_asset_id(self.asset_id, field="SyntheticAssetSpec.asset_id")

        if len(self.components) == 0:
            raise ValueError("SyntheticAssetSpec.components must be non-empty")

        for component_id in self.components:
            _validate_component_id(component_id)


@dataclass(frozen=True, slots=True)
class SyntheticAsset:
    """
    Runtime wrapper for a Synthetic Asset instrument.

    At this stage this wrapper is intentionally thin: it carries only the spec.
    Derived realised datasets (ComponentContracts, ComponentWeights,
    TargetHoldings) are attached by builders in later sessions.
    """

    spec: SyntheticAssetSpec
