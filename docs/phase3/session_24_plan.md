# session_24_plan.md — MXM V1  
## Session 24 — SyntheticAssetSpec (Instrument Definition Layer)

## Position in Architecture

Synthetic Assets sit above the contracts subsystem and below strategies.

The contract subsystem now provides:

- `SelectorRule` (relative contract definition / intent)
- `ContractSelectorEngine` (selection at a timestamp)
- `ContractSeries` (identity realised over session ranges)

Session 24 introduces the first-class **Synthetic Asset** concept as an **instrument definition**, not a strategy.

This session explicitly does **not** cover:

- dynamic weights
- target holdings
- target trades
- execution
- P&L
- storage pipelines

Those are Sessions 25–30.

Session 24 is a **model-clarification and specification session**: define the objects and their lifecycle.

## Objective

Define the *canonical model* for synthetic assets in MXM V1:

1. What a Synthetic Asset *is* (conceptually and structurally).
2. What the in-memory classes are (`SyntheticAssetSpec`, `SyntheticAsset`, and leg specs).
3. How synthetic assets are specified (configuration pattern).
4. How they are built/instantiated (builder and resolver interfaces).
5. How they are stored and discovered (registry layout and inspection surface), without implementing full storage pipelines yet.

At the end of Session 24, synthetic assets are:

- first-class
- uniquely identified
- reproducibly instantiated
- structurally validated
- discoverable via a minimal registry mechanism

## Part 1 — Clarify the Model (Design Lock)

### 1.1 Terminology

**Synthetic Asset (instrument):**  
A deterministic replication definition mapping a synthetic unit into exposures to one or more tradable legs.

**Leg:**  
A concrete tradable exposure defined by:
- a `product_id`
- a `SelectorRule` (or canonical rule id)
- a scaling rule from synthetic unit -> leg unit

**Weights:**  
Time-indexed quantities that vary over sessions (Session 25).  
Not part of the spec.

**Target Holdings:**  
Contract-level lots over time, derived from weights and contract identity (Session 26).  
Not part of the spec.

### 1.2 Separation of Concerns (Hard Boundary)

Session 24 defines *what the instrument is*, not how it is traded.

Synthetic Asset definitions must be:

- stable
- deterministic
- strategy-agnostic
- serialisable (or serialisable via a spec registry)
- free of state

No:
- vol targeting
- notional targeting
- FX hedging
- risk overlays

Those are strategy or portfolio layers.

## Part 2 — Core Types to Implement

### 2.1 `SyntheticAssetId`

Define a canonical identifier scheme.

Minimum:

- `asset_id: str` (stable, lowercase, underscore-separated)
- enforce via validation

Optionally:
- `namespace` (e.g. `mxm.v1.synthetic_assets`)
- version string (defer; not required for V1)

### 2.2 `SyntheticAssetSpec`

This is the authoritative specification.

Proposed minimal spec:

```python
@dataclass(frozen=True)
class SyntheticAssetSpec:
    asset_id: str
    base_currency: str
    unit: str
    legs: list[LegSpec]
```

Semantics:
- `asset_id` unique within registry scope
- `legs` non-empty
- stable deterministic ordering of legs
- base_currency/unit are informative for V1 (but included for forward compatibility)

### 2.3 `LegSpec`

A leg is an exposure definition, not a time series.

Proposed minimal:

```python
@dataclass(frozen=True)
class LegSpec:
    leg_id: str
    product_id: str
    rule_id: str            # canonical relative id for SelectorRule
    leg_unit: str | None    # optional; informational for V1
    scale: float            # mapping from synthetic unit -> leg "contract equivalents"
```

Notes:
- `rule_id` should be the canonical relative id, not a rule object.
- `scale` is intentionally simple in V1 (dimensionless scale factor).
- Do not embed weight dynamics here.

### 2.4 `SyntheticAsset` (In-memory Runtime Object)

Distinguish:

- `SyntheticAssetSpec` (pure definition)
- `SyntheticAsset` (resolved runtime object, with ready-to-use resolvers)

Proposed minimal runtime:

```python
@dataclass(frozen=True)
class SyntheticAsset:
    spec: SyntheticAssetSpec
```

At V1, `SyntheticAsset` may be a thin wrapper. The key is that it becomes the object passed to later builders.

Avoid adding:
- series
- weights
- holdings

Session 25–26 will attach those surfaces externally.

## Part 3 — Specification Pattern (Registry + Loading)

### 3.1 Registry Format

Define a stable on-disk location, e.g.:

```
mxm/v1/synthetic_assets/registry/
  assets/
    <asset_id>.yaml
  rules/
    selector_rules.yaml   (optional; if rule registry already exists, reference it)
```

For V1, each asset spec lives in its own YAML file.

### 3.2 YAML Shape (Proposed)

```yaml
asset_id: cme_es_front
base_currency: USD
unit: contract
legs:
  - leg_id: es_front
    product_id: cme_emini_snp500_futures
    rule_id: cme_emini_snp500_futures.front
    scale: 1.0
```

This keeps the spec minimal and defers dynamic weights.

### 3.3 Loader / Validator

Implement:

- `load_synthetic_asset_spec(path) -> SyntheticAssetSpec`
- `validate_synthetic_asset_spec(spec) -> None` (or in `__post_init__`)

Validation must ensure:
- asset_id sane
- legs non-empty
- unique leg_id
- rule_id present
- scale finite

## Part 4 — Instantiation Pattern (Builder + Resolvers)

### 4.1 Resolver Interfaces

Define a minimal “resolver” boundary for later sessions:

- `SyntheticAssetRegistry` that can:
  - list assets
  - load by id

- `SelectorRuleRegistry` (if not already present) that can:
  - resolve rule_id -> SelectorRule object

### 4.2 Build / Instantiate

Implement:

```python
def build_synthetic_asset(
    *,
    asset_id: str,
    asset_registry: SyntheticAssetRegistry,
    rule_registry: SelectorRuleRegistry,
) -> SyntheticAsset
```

The builder:
- loads spec
- validates
- (optionally) resolves rule ids and validates they exist (but does not build ContractSeries yet)

This gives you a clean “construction step” with explicit dependencies.

## Part 5 — Minimal Inspection Surface

Add:

```
scripts/synthetic_assets/ops/synthetic_asset_inspect.py
```

Capabilities:
- list available assets
- inspect one asset (print spec in canonical form)

No holdings, weights, or PnL yet.

## Tests (Required)

### Unit Tests

- Spec validation:
  - empty legs fails
  - duplicate leg_id fails
  - invalid asset_id fails
  - non-finite scale fails

- YAML load:
  - round-trip parse for a minimal example
  - missing required fields fails clearly

- Registry:
  - list assets from folder
  - load by id

### Integration Smoke

- Define one real asset YAML referencing a real rule_id.
- Instantiate `SyntheticAsset` via builder and confirm resolved.

## Deliverables

Session 24 is complete when:

- `SyntheticAssetSpec`, `LegSpec`, `SyntheticAsset` exist
- YAML-based asset registry format is defined and implemented
- Builder/registry interfaces exist and work
- Inspect script exists (list + inspect)
- Tests green

## Forward Link

This session unlocks:

- Session 25 — Dynamic weights over sessions, applied to legs
- Session 26 — Contract-level target holdings via ContractSeries
 Session 27 — Target trades
- Session 28 — Settlement executor
- Session 29 — P&L
- Session 30 — Plotting and inspection

The key constraint: after Session 24, the identity of “what an asset is” is fixed.
Session 25+ may add new time series surfaces, but must not change the core spec model.
