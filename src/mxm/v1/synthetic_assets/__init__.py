"""
mxm.v1.synthetic_assets
=======================

Synthetic Asset Instrument Definitions (MXM V1).

Position in Architecture
------------------------

This module defines the *instrument-definition layer* for synthetic assets.

Synthetic assets sit:

    Contracts  →  Synthetic Assets  →  Strategies

The contracts subsystem provides deterministic contract identity over
sessions via SelectorRule and ContractSeries.

This module defines synthetic assets as *deterministic replication
instruments* composed of a fixed set of role-bound legs and a
product-agnostic weight rule.

Core Model
----------

A SyntheticAssetSpec consists of:

- asset_id
- base_currency
- unit (semantic unit of one synthetic unit)
- weights_rule_id (generic, product-agnostic)
- legs: mapping role -> LegBinding

Each LegBinding binds a role to:

- product_id
- selector_rule_id (canonical relative id)

Roles
-----

Legs are keyed by *role* (string identifiers). Weight rules operate over
roles, not products. This allows weight rules to remain generic and reusable
across products, while synthetic asset specs bind those roles to concrete
product/selector combinations.

Separation of Concerns
----------------------

This module defines only static instrument specifications.

It does NOT implement:

- ContractSeries realisation
- Weight time series
- FX conversion
- Contract multiplier handling
- Target holdings
- Trade construction
- Execution
- P&L
- Storage pipelines

Time-indexed surfaces (weights, holdings, trades) are constructed in later
sessions using builders that combine:

- SyntheticAssetSpec
- ContractSeries (per role)
- Trading calendars
- Instrument metadata (e.g. LTD, multiplier, currency)

Design Principles
-----------------

- Deterministic
- Strategy-agnostic
- Stateless
- Registry-driven
- Fully serialisable
- Explicit role binding

After Session 24, the identity of a synthetic asset is fixed.
Subsequent sessions may add derived time-series layers, but must not
change the instrument-definition model.
"""
