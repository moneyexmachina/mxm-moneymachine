# Session 24b – SyntheticAssetSpec Authoring & Registry Population

Status: ✅ Completed  
Date: 2026-03-05  
Scope: Complete SyntheticAssetSpec authoring layer, implement builders for CONT / TS / PS, define construction policy, implement policy compiler, and populate registry for the initial futures product universe.

# 1. Objective

Session 24b completed the **SyntheticAsset specification layer**.

The goal was to establish a deterministic system that:

1. Defines synthetic assets declaratively.
2. Compiles those definitions into `SyntheticAssetSpec` objects.
3. Persists them into a registry.
4. Allows inspection and reconstruction of all assets.

The session delivered a full pipeline:

```
RefData products
      ↓
Synthetic asset policy
      ↓
Policy compiler
      ↓
SyntheticAssetSpec objects
      ↓
Registry persistence
```

At completion, the **synthetic asset identity layer** is complete and populated.

# 2. SyntheticAssetSpec Model Finalization

The `SyntheticAssetSpec` model was extended and finalized.

New field added:

```
size: float
```

Full structure:

```
SyntheticAssetSpec
  asset_id
  canonical_id
  currency
  unit
  size
  weights_rule_id
  legs
```

Design notes:

- `size` represents the **synthetic contract size**.
- For V1, this is equal to the underlying product contract size.
- However, the field is explicitly stored to allow future transformations.

Example YAML structure:

```
asset_id: cbot_corn_futures_cont_l1_wr_roll_v1
currency: USD
unit: BUSHEL
size: 5000
weights_rule_id: roll_v1
legs:
  - role: cur
    product_id: cbot_corn_futures
    selector_rule_id: RC::PT=MONTH::N=1
  - role: nxt
    product_id: cbot_corn_futures
    selector_rule_id: RC::PT=MONTH::N=2
```

# 3. Spec Builder Layer

A deterministic builder module was implemented:

```
mxm/v1/synthetic_assets/spec_builder.py
```

Builders implemented:

### Continuous Roll

```
build_continuous_roll_spec(...)
```

Inputs:

- product_id
- currency
- unit
- size
- weights_rule_id
- cur: SelectorRule
- nxt: SelectorRule

Produces:

```
CONT Ln
```

### Time Spread

```
build_time_spread_spec(...)
```

Leg roles:

```
near_cur
near_nxt
far_cur
far_nxt
```

Produces:

```
TS Ln Ln+1
```

### Product Spread

```
build_product_spread_spec(...)
```

Leg roles:

```
a_cur
a_nxt
b_cur
b_nxt
```

Produces:

```
PS(A,B)
```

Example:

```
comex_gold_futures_ps_nymex_natural_gas_futures_l1_wr_roll_v1
```

# 4. Asset ID Grammar

The asset slug grammar was finalized.

General structure:

```
<product>_<kind>_<selector>_wr_<weights_rule>
```

Examples:

### Continuous

```
cbot_corn_futures_cont_l1_wr_roll_v1
```

### Fixed Month

```
cbot_corn_futures_cont_mar1_wr_roll_v1
```

### Time Spread

```
cbot_corn_futures_ts_l1_l2_wr_roll_v1
```

### Product Spread

```
cbot_corn_futures_ps_nymex_natural_gas_futures_l1_wr_roll_v1
```

Properties:

- deterministic
- machine safe
- human readable
- derived entirely from spec inputs

# 5. Construction Policy

A declarative policy layer was created:

```
mxm/v1/synthetic_assets/construction_policy.py
```

The policy defines **which assets should exist**, without describing how to build them.

Key policy decisions:

### Continuous Assets

For every product:

```
CONT L1..L12
```

These represent the **nth listed contracts**.

### Time Spreads

For each product:

```
TS Ln Ln+1
n ∈ [1, 11]
```

These allow term structure and curve analysis.

### Fixed Month Rolls

To support seasonality and liquidity studies:

```
CONT <month>1
```

Examples:

Corn:

```
Mar
May
Jul
Sep
Dec
```

Quarterly products:

```
Mar
Jun
Sep
Dec
```

### Product Spreads

Three spreads were introduced primarily to test:

- unit transformations
- cross-product holdings
- portfolio normalization

Pairs chosen:

```
Gold vs Natural Gas
Corn vs Natural Gas
ES vs GBP
```

Levels:

```
L1
L2
L3
```

# 6. Policy Compiler

A compiler was implemented:

```
mxm/v1/synthetic_assets/policy_compile.py
```

Responsibilities:

```
policy + product metadata
        ↓
SyntheticAssetSpec list
```

Key steps:

1. Load products from `mxm-refdata`
2. Validate spread pairs
3. Compile rollings
4. Compile time spreads
5. Compile fixed month rolls
6. Compile product spreads
7. Produce deterministic spec list

Validation includes:

- product existence checks
- A != B enforcement for spreads
- period compatibility

# 7. Registry System

The registry system was finalized.

Location:

```
~/.mxm/synthetic_assets/registry/assets/
```

Registry module:

```
mxm/v1/synthetic_assets/spec_registry.py
```

Capabilities:

```
save()
load()
list_asset_ids()
```

Storage format:

```
YAML
```

Each asset stored as one file.

# 8. Registry Build Script

Ops script implemented:

```
scripts/synthetic_assets/ops/build_registry.py
```

Responsibilities:

1. Load refdata products
2. Compile policy
3. Build specs
4. Sort by asset_id
5. Persist to registry

CLI flags:

```
--dry-run
--overwrite
--product-id
--registry-root
```

Example usage:

```
poetry run python scripts/synthetic_assets/ops/build_registry.py --dry-run
```

# 9. Inspect Script

An inspect tool was created to demonstrate registry functionality.

Capabilities:

```
list assets
load specific spec
print structure
```

This confirms the registry round-trip behavior.

# 10. System Scale

With the current policy, the registry now produces:

```
161 synthetic assets
```

Across:

```
5 futures products
```

Breakdown:

- Continuous ladders
- Time spread ladders
- Fixed-month rolls
- Product spreads

All generated deterministically.

# 11. Implementation Fixes

Several adjustments were made during the session:

### Duplicate Leg Bindings

Originally:

```
SyntheticAssetSpec prevented duplicate selector bindings
```

This was removed because time spreads legitimately reuse legs.

Example:

```
L1-L2
L2-L3
```

Both reference `L2`.

### YAML Numeric Loading

Adding `size` required loader changes.

A helper was implemented:

```
_get_number(...)
```

to support YAML numeric parsing.

### Policy Compiler Validation Fix

Unit tests revealed a validation failure for partial product sets.

Fix:

```
product spread validation now respects available products
```

This resolved failing tests.

# 12. Testing

All tests pass.

Additional tests added:

```
test_policy_compile.py
```

Coverage includes:

- product validation
- spread construction
- GBP quarterly month logic
- spec construction integrity

Final status:

```
215 tests passing
```

# 13. Result

Session 24b successfully delivered the full **SyntheticAsset specification system**.

We now have:

```
Relative contract rules
        ↓
SyntheticAssetSpec
        ↓
Policy compiler
        ↓
Synthetic asset registry
```

The system now produces a **deterministic universe of synthetic assets**.

This marks the completion of the **synthetic asset identity layer**.

# 14. Next Step

Next session:

```
Session 25 – Weights Rules
```

This will implement:

```
weights_rule_id
      ↓
weights series through time
```

Allowing synthetic assets to produce:

```
target holdings
synthetic price
synthetic PnL
```

Once implemented, the pipeline becomes:

```
ContractSeries
      +
WeightsRule
      ↓
SyntheticAsset time series
```

This will complete the runtime realization layer of synthetic assets.

# 15. Closing Notes

This session demonstrated a strong example of MXM architecture design:

- clear separation of identity and runtime layers
- declarative policy → deterministic compilation
- registry-based persistence
- reproducible asset universe generation

The resulting system surface is:

```
clean
inspectable
deterministic
extensible
```

and provides a robust foundation for the next stage of the Money Ex Machina system.
