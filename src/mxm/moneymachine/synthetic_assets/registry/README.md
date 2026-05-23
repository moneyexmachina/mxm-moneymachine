# SyntheticAssetSpec Registry (MXM V1)

This directory documents the **SyntheticAssetSpec registry schema** used by MXM V1.

A `SyntheticAssetSpec` is a **static instrument definition** for a synthetic asset.
It defines **what the instrument is**, not how it is traded.

Synthetic assets sit above the contracts subsystem (SelectorRules / ComponentContrats) and below strategies.

## Scope and Non-Goals

This registry stores **specifications only**.

It does **not** store or define:
 
- time-indexed weights
- ComponentContracts realisations
- target holdings
- target trades
- execution
- P&L
- storage pipelines for derived surfaces


## Registry Layout (Runtime)

At runtime the registry is a filesystem-backed directory under the MXM root
(e.g. `~/.mxm/`), using one YAML file per synthetic asset id:

```
<mxm_root>/synthetic_assets/spec_registry/
  assets/
    <asset_id>.yaml
```

Temporary writer files may use the suffix `*.tmp.yaml` and are ignored by readers.

## YAML Schema

Each asset spec file **must** be a YAML mapping with the following keys:

- `asset_id: str`  
  Canonical synthetic asset identifier. Must match the MXM id conventions
  (lowercase, underscore-separated).

- `currency: str`  
  Settlement / reporting currency for the synthetic instrument (e.g. `USD`).

- `unit: str`  
  Semantic unit of one synthetic instrument (e.g. `contract`, `bbl`, `mwh`).
  This is informational in V1 and supports forward compatibility.

- `weights_rule_id: str`  
  Identifier for the weight rule used to realise time-indexed weights
  over the asset roles (defined in a separate weights-rule registry).

- `components: mapping`  
  Mapping from **component_id** to ComponentBinding. component_ids are stable identifiers used by
  weight rules. A leg binding must be a mapping with:

  - `product_id: str`  
    MXM product id (e.g. `cme_emini_snp500_futures`).

  - `selector_rule_id: str`  
    Canonical selector rule id. This identifies the relative contract intent
    (e.g. front month, second month) and is resolved later into a `ComponentContracts` series.

### Example

```yaml
asset_id: cme_es_front
currency: USD
unit: contract
weights_rule_id: roll.linear.ltd_end.window_5
components:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
  m2:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.second
```

## Semantics

### Components

Components are the *interface* between the static spec and generic weight rules.

- Components must be stable and deterministic.
- Weight rules refer to roles, not products.
- The spec binds component_ids to concrete `(product_id, selector_rule_id)` specifications.

### Selector Rules

`selector_rule_id` is a canonical relative identifier for a `SelectorRule`.
It is product-agnostic in principle, but may be namespaced by product in ids
for clarity and registry hygiene.

A leg’s contract identity over sessions is realised later as:

```
(product_id, selector_rule_id) -> ComponentContracts
```

### Currency and Units

`currency` is the synthetic instrument currency.

Contracts may have a native currency and physical unit owned by contract metadata.
Unit conversion is performed in later builders when deriving holdings.

## Validation

Loading a spec performs:

- JSON-safe normalisation of YAML values (rejects non-JSON YAML types)
- schema checks (required keys and shapes)
- model validation (id/role regexes, invariants)

## Authoring and Generation

For scale, concrete asset specs are expected to be **generated** from
product-universe inputs and asset templates. The runtime registry stores only the
compiled, concrete `SyntheticAssetSpec` YAML entries.
