# Session 27 – Target Holdings and SyntheticAsset Runtime

Status: ✅ Completed  
Date: 2026-03-10  
Scope: Synthetic asset realisation layer (ComponentContracts → ComponentWeights → TargetHoldings → SyntheticAsset)

## 1. Objective

Session 27 completed the final step of the **synthetic asset realisation pipeline** by implementing **TargetHoldings** and introducing the **SyntheticAsset runtime object**.

This closes the core construction chain:

```
SyntheticAssetSpec
    ↓
ComponentContracts
    ↓
ComponentWeights
    ↓
TargetHoldings
    ↓
SyntheticAsset (runtime wrapper)
```

The system can now construct a fully realised synthetic asset over a session range using real refdata, contract selection, and roll rules.

A smoke script confirms correct behaviour end-to-end.

## 2. Major Deliverables

### 2.1 TargetHoldings

New module:

```
mxm.v1.synthetic_assets.target_holdings
```

Purpose:

Convert component-level contract selections and weights into **actual contract quantities** required to replicate one synthetic asset unit.

Conceptually:

```
(session, contract_id) → target_holding
```

Where:

```
target_holding =
    component_weight
  × unit_conversion
  × synthetic_asset_size
  ÷ contract_size
```

Key properties:

* MultiIndex `(session, contract_id)`
* deterministic aggregation across components
* schema validation guarantees
* compatible with downstream trade derivation

Example output:

```
session        contract_id                  target_holding
2020-01-03     cbot_corn_futures.Mar-2020   1.0
               cbot_corn_futures.May-2020   0.0
```

### 2.2 Unit Conversion Layer

New module:

```
mxm.v1.synthetic_assets.unit_conversion
```

Introduced `UnitConverter`.

Responsibilities:

* convert between `ProductUnit` values
* support both `ProductUnit` enum and string inputs
* explicit conversion table
* fail loudly on unsupported conversions
* provide vectorised conversion helpers

Initial conversions implemented for physically compatible units only.

Future expansion may migrate this logic into `mxm-refdata`.

### 2.3 SyntheticAsset Runtime Object

New module:

```
mxm.v1.synthetic_assets.runtime
```

Defines the realised runtime object:

```
SyntheticAsset
```

Structure:

```
SyntheticAsset
    spec
    component_contracts
    component_weights
    target_holdings
```

Responsibilities:

* bundle all realised asset surfaces
* validate internal alignment
* provide a canonical runtime representation

Builder:

```
build_synthetic_asset(...)
```

Pipeline:

```
SyntheticAssetSpec
    → build_component_contracts
    → build_component_weights
    → build_target_holdings
    → SyntheticAsset
```

This object becomes the **primary interaction point** for the synthetic asset layer.

### 2.4 Smoke Script

New script:

```
scripts/synthetic_assets/smoke_synthetic_asset_build.py
```

Purpose:

Human inspection of full asset realisation.

Example:

```
poetry run python scripts/synthetic_assets/smoke_synthetic_asset_build.py \
    --asset-id cbot_corn_futures_cont_hknuz1_wr_lr_3_1 \
    --start 2020-01-03 \
    --end 2025-01-31
```

Displays:

* SyntheticAssetSpec summary
* Component bindings
* ComponentContracts head
* ComponentWeights head
* TargetHoldings head
* active holdings summary
* invariants

This confirms correct end-to-end construction.

### 2.5 Registry Maintenance Improvements

Improved registry build script:

```
scripts/synthetic_assets/build_registry.py
```

Added new CLI option:

```
--prune
```

Purpose:

Synchronise registry contents with compiled synthetic asset specs.

Behaviour:

```
compiled_ids = specs_from_policy
existing_ids = registry.list_asset_ids()

stale = existing_ids − compiled_ids
```

`--prune` removes stale entries.

Safety guard:

```
--prune cannot be used together with --product-id
```

to avoid accidental deletion when compiling a subset of products.

Also:

```
--prune ⇒ overwrite
```

ensuring registry consistency during sync operations.

## 3. Test Suite Updates

### Updated tests

Refactored to align with the new architecture:

```
test_component_contracts.py
test_component_weights.py
test_target_holdings.py
```

Key coverage:

* component pairing logic
* session alignment invariants
* aggregation across components
* unit conversion behaviour
* schema validation
* error handling

All tests passing.

## 4. Architectural Outcome

The **synthetic asset layer is now fully operational**.

Final structure:

```
synthetic_assets/

models.py
component_contracts.py
component_weights.py
target_holdings.py
unit_conversion.py
runtime.py
```

Realisation pipeline:

```
SyntheticAssetSpec
        ↓
ComponentContracts
        ↓
ComponentWeights
        ↓
TargetHoldings
        ↓
SyntheticAsset
```

Each stage produces a deterministic, validated data surface.

## 5. Important Observations

### TargetHoldings contract universe

The `TargetHoldings` surface introduces an important future concept:

* **current exposure** vs **reachable contract universe**

Example:

```
ComponentContracts rows = 1311
TargetHoldings rows     = 2622
```

Each session produces holdings for **both component contracts**, even when weight = 0.

This is correct and necessary because:

* contracts may appear/disappear across sessions
* target trades must reconcile previous and new holdings
* executor must know which contracts belong to the asset universe

This distinction will become important for:

```
target_trades
execution attribution
backtest executor
```

## 6. Testing Philosophy Discussion

Session 27 also included a design discussion on testing strategy.

Key conclusions:

Tests serve as **executable behavioural commitments** rather than mere correctness checks.

Recommended structure for MXM:

```
Static analysis
    ↓
Unit tests
    ↓
Integration tests
    ↓
Smoke scripts
```

Additionally:

Future MXM versions may introduce **curated domain fixtures** owned by upstream modules to avoid fixture drift.

## 7. Next Step (Session 28)

With the synthetic asset fully realised, the next logical step is:

```
TargetTrades
```

Transform:

```
TargetHoldings(t)
TargetHoldings(t-1)
```

into:

```
TargetTrades(t)
```

This introduces the first layer of **intent-to-execution translation** and prepares the system for the backtest executor.

## 8. Summary

Session 27 completes the **core synthetic asset realisation system**.

The system can now:

* compile synthetic asset specs
* realise contract selections
* compute rolling weights
* convert units
* produce concrete contract holdings
* assemble a runtime asset object
* inspect behaviour via smoke scripts

This establishes a clean and deterministic foundation for the **execution layer** in the upcoming sessions.

