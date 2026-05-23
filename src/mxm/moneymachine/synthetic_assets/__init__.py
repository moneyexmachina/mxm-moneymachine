"""
Synthetic Asset Instrument Definitions.

Position in Architecture
------------------------

This module defines the instrument-definition layer for synthetic assets.

Synthetic assets sit:

    Contracts  →  Synthetic Assets  →  Strategies

The contracts subsystem provides deterministic contract identity over
sessions via SelectorRule and ComponentContracts.

This module defines synthetic assets as deterministic replication
instruments composed of a fixed set of component bindings and a
product-agnostic weights rule.

Core Model
----------

A SyntheticAssetSpec consists of:

- asset_id
- canonical_id
- currency
- unit (semantic unit of one synthetic contract)
- size
- weights_rule_id (generic, product-agnostic)
- components: mapping component_id -> ComponentBinding

Each ComponentBinding binds a component to:

- product_id
- selector_rule_id (canonical relative id)

Components
----------

Synthetic-asset components are keyed by component_id (string identifiers).
Weights rules operate over components, not products. This allows weights
rules to remain generic and reusable across products, while synthetic asset
specifications bind those components to concrete product/selector pairs.

Separation of Concerns
----------------------

This module defines only static instrument specifications.

It does NOT implement:

- ComponentContracts realisation
- ComponentWeights realisation
- FX conversion
- Contract multiplier handling
- TargetHoldings
- Trade construction
- Execution
- P&L
- Storage pipelines

Time-indexed realised datasets (contracts, weights, holdings, trades) are
constructed in later sessions using builders that combine:

- SyntheticAssetSpec
- ComponentContracts
- Trading calendars
- Instrument metadata

Design Principles
-----------------

- Deterministic
- Strategy-agnostic
- Stateless
- Registry-driven
- Fully serialisable
- Explicit component binding

After Session 24, the identity of a synthetic asset is fixed.
Subsequent sessions may add derived realised datasets, but must not
change the instrument-definition model.
"""
