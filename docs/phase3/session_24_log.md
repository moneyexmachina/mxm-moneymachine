# Session 24 – SyntheticAssetSpec Registry & Canonical Identity Layer

Status: ✅ In Progress (Foundational Layer Complete)  
Scope: Synthetic Asset specification modelling, canonical identity design, registry infrastructure, and initial builder semantics.

## 1. Objective

Session 24 introduces the **SyntheticAssetSpec layer**.

Conceptually:

> A `SyntheticAssetSpec` is a static, declarative definition of a synthetic asset.
> It binds:
> - roles → (product_id, selector_rule_id)
> - a weights_rule_id
> - a currency and unit
> - and a canonical_id describing the full construction recipe.

It is **not**:
- A time-series object
- A ContractSeries
- A WeightsSeries
- A holdings surface
- A P&L artefact

It is a *pure specification* that can later be materialised into dynamic artefacts.

This clean separation mirrors earlier MXM design patterns:
- Refdata vs runtime objects
- Dataset specs vs dataset artefacts
- SelectorRule vs ContractSeries

## 2. Architectural Decisions Locked

### 2.1 Leg Binding Semantics

A `LegBinding` binds:

- `product_id`
- `selector_rule_id` (canonical relative id)

Important clarifications:

- `SelectorRule` is product-agnostic.
- `selector_rule_id` is the canonical relative id (`RC::...`).
- Product binding occurs at the `LegBinding` level.
- We do **not** embed product_id inside selector_rule_id.

This preserves:

- Separation of concerns
- Reusability of SelectorRule across products
- Clean role-based composition

### 2.2 Canonical Identity for Synthetic Assets

We introduced explicit canonical id grammars:

#### Continuous Roll

```
SA::KIND=CONT
  ::P0=<product_id>
  ::CUR=<selector_canonical_relative_id>
  ::NXT=<selector_canonical_relative_id>
  ::WR=<weights_rule_id>
```

#### Time Spread

```
SA::KIND=TS
  ::P0=<product_id>
  ::NEAR_CUR=<...>
  ::NEAR_NXT=<...>
  ::FAR_CUR=<...>
  ::FAR_NXT=<...>
  ::WR=<weights_rule_id>
```

#### Product Spread

```
SA::KIND=PS
  ::P0=<product_a>
  ::P1=<product_b>
  ::A_CUR=<...>
  ::A_NXT=<...>
  ::B_CUR=<...>
  ::B_NXT=<...>
  ::WR=<weights_rule_id>
```

Properties:

- Fully machine-readable
- Deterministic
- Encodes full recipe
- Unambiguous
- No duplication of information

We intentionally did **not** introduce multiple identity layers beyond:

- `asset_id` (slug)
- `canonical_id` (machine grammar)
- `short_rel_id` (selector ergonomics)

No proliferation of id types.

### 2.3 Models

`SyntheticAssetSpec` now includes:

- asset_id
- canonical_id
- currency
- unit
- weights_rule_id
- legs: dict[str, LegBinding]

Validation strategy:

- Regex validation for asset_id and role keys
- Dedicated canonical_id validator
- Schema validation in loader
- No redundant runtime type checks (Pyright-enforced typing preferred)

### 2.4 Registry Layer

Implemented:

- `spec_registry_layout.py`
- `spec_registry.py`
- `SyntheticAssetSpecRegistry`
- `save(...)`
- `load(...)`
- `list_asset_ids(...)`

Characteristics:

- Filesystem-backed
- One YAML per asset_id
- `.tmp.yaml` safety pattern
- Deterministic sorted listing
- Strict JSON normalisation using `json_value_from_obj`

Tests:

- Schema validation tests
- Model-level validation tests
- Registry load/list tests
- Save/load roundtrip tests

All tests passing.

### 2.5 Builder Direction

Agreed pattern:

Builder inputs:
- product_id(s)
- SelectorRule objects
- weights_rule_id
- currency
- unit

Builder responsibilities:
- Construct canonical_id via canonical_ids.py
- Derive selector_rule_id using canonical_relative_id(rule)
- Bind legs with (product_id, selector_rule_id)
- Construct deterministic asset_id slug

We explicitly rejected:
- Product-bound selector_rule_ids
- Duplicating product inside rule id
- Mixing leg binding and weights rule logic

## 3. Open Design Threads

### 3.1 SelectorRule Revival

Because we store only `selector_rule_id` (canonical relative id string),
we must implement:

```
parse_selector_rule_id(str) -> SelectorRule
```

in `contracts/selectors.py`.

This will allow:

- Reconstructing SelectorRule from registry spec
- Full deterministic reconstruction of asset semantics
- Avoiding separate selector rule registries

This is the next required piece.

### 3.2 Asset ID Slug Grammar

Still to formalise:

- Slug format for CONT / TS / PS
- Stable, parseable, short
- Avoid redundancy
- Deterministic from inputs

Candidate pattern:

```
<product_id>__cont__<short_rel_id>
```

but not yet locked.

### 3.3 Spec Authoring Mechanism

We now have:

- Spec model
- Canonical id grammar
- Registry save/load

We still need:

- `spec_builder.py`
- Parametric asset template dispatch
- Batch generation for all products

This is the transition from:

> “Registry infrastructure complete”

to

> “Automated authoring pipeline”

## 4. Key Conceptual Clarifications Achieved

1. SelectorRule is product-agnostic.
2. LegBinding binds product to relative selector.
3. Weights rules are generic across products.
4. Canonical identity must encode full recipe.
5. SyntheticAssetSpec is static definition only.
6. Registry is static config, not artefact storage.
7. Builder takes minimal parameters only.

This establishes a clean separation between:

- Specification
- Construction
- Runtime realisation

## 5. System Maturity Check

Compared to earlier sessions:

- No over-expansion of abstractions
- Minimal new object surface
- Identity grammar clearly defined
- Registry implemented and tested
- No premature optimisation
- No engine-level leakage

Session 24 is progressing in a controlled, layered manner consistent with:

> Clarity first → minimal objects → test → extend.

## 6. Next Step

Immediate next technical milestone:

- Implement `parse_selector_rule_id` in contracts/selectors.py.

Then:

- Finalise CONT builder.
- Lock slug grammar.
- Add builder tests.
- Generate first real specs.
- Populate registry.

End of Session 24 log (phase 1).
