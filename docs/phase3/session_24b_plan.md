# Session 24b – SyntheticAssetSpec Authoring & Registry Population

Status: 🔜 Planned  
Scope: Complete SyntheticAssetSpec authoring layer, implement builders for CONT / TS / PS, and populate registry for initial product universe (5 products).

## 1. Objective

Session 24b completes the **SyntheticAsset specification layer** by:

1. Implementing deterministic builders for:
   - Rolling continuous futures (CONT)
   - Time spreads (TS)
   - Product spreads (PS)

2. Defining:
   - Slug grammar for `asset_id`
   - Parsing for `selector_rule_id` → `SelectorRule`

3. Designing:
   - A declarative “construction policy” per product
   - A batch authoring mechanism

4. Populating:
   - `~/.mxm/synthetic_assets/registry/assets/`
   - For the 5 products currently in mxm-refdata

At completion:

> SyntheticAsset specification layer is formally complete and populated.

## 2. Missing Core Pieces

### 2.1 SelectorRule Revival

We currently store:

- `selector_rule_id = canonical_relative_id(rule)` (RC::...)

We must implement:

```
parse_canonical_relative_id(str) -> SelectorRule
```

Location:
```
mxm/v1/contracts/selectors.py
```

Responsibilities:
- Parse PT
- Parse CYCLE
- Parse N
- Reconstruct PeriodFilter
- Reconstruct SelectorRule

This enables:

- Full revival of spec definitions
- Deterministic reconstruction of legs
- No separate selector rule registry

This is required before moving forward.

## 3. Asset Builders

### 3.1 spec_builder.py

Create:
```
mxm/v1/synthetic_assets/spec_builder.py
```

Builders:

#### 3.1.1 Continuous Roll

```
build_continuous_roll_spec(...)
```

Inputs:
- product_id
- currency
- unit
- weights_rule_id
- cur: SelectorRule
- nxt: SelectorRule

Responsibilities:
- Construct canonical_id (CONT grammar)
- Construct slug asset_id
- Bind legs with canonical_relative_id
- Return SyntheticAssetSpec

#### 3.1.2 Time Spread

```
build_time_spread_spec(...)
```

Inputs:
- product_id
- currency
- unit
- weights_rule_id
- near_cur
- near_nxt
- far_cur
- far_nxt

Leg roles:
- near_cur
- near_nxt
- far_cur
- far_nxt

Canonical id grammar:
SA::KIND=TS::...

#### 3.1.3 Product Spread

```
build_product_spread_spec(...)
```

Inputs:
- product_a
- product_b
- currency
- unit
- weights_rule_id
- a_cur, a_nxt
- b_cur, b_nxt

Leg roles:
- a_cur
- a_nxt
- b_cur
- b_nxt

Canonical id grammar:
SA::KIND=PS::...

## 4. Asset ID Slug Grammar (To Lock)

Requirements:

- Deterministic
- Machine safe
- Human readable
- Derived from inputs
- No manual injection

Proposed patterns:

### CONT
```
<product_id>__cont__<short_rel_id(cur)>
```

Example:
```
cme_emini_snp500_futures__cont__L1
```

### TS
```
<product_id>__ts__<short_rel_id(near)>_<short_rel_id(far)>
```

### PS
```
<product_a>__ps__<product_b>__<short_rel_id(cur)>
```

This will be finalised and documented.

## 5. Construction Policy Layer

We need a declarative mechanism defining:

For each product_id:

- Which rolling assets?
- Which time spreads?
- Which product spreads?

Create:
```
synthetic_assets/construction_policy.py
```

Structure:

```python
@dataclass(frozen=True)
class RollingPolicy:
    n_values: list[int]
    period_type: PeriodType
    cycle_id: str | None
    cycle_elements: frozenset[int] | None
    weights_rule_id: str


@dataclass(frozen=True)
class ProductAssetPolicy:
    rollings: list[RollingPolicy]
    timespreads: list[...]
    product_spreads: list[...]
```

Or simpler:

Dictionary keyed by product_id.

Example (initial version):

- For each product:
  - Rolling L1 (monthly)
  - Rolling L2
  - Time spread L1/L2
  - Product spreads only between selected pairs

Keep v1 minimal.

## 6. Registry Population Script

Create:

```
scripts/synthetic_assets/build_registry.py
```

Responsibilities:

1. Load product list from mxm-refdata
2. Apply construction_policy
3. Build SyntheticAssetSpec objects
4. Save into registry
5. Optionally dry-run mode
6. Optionally overwrite mode

CLI flags:

- --dry-run
- --overwrite
- --product-id (optional filter)

This script becomes the official registry population mechanism.

## 7. Initial Product Universe

We will populate for:

- 5 products currently in mxm-refdata

For each:

- CONT L1
- CONT L2
- TS L1/L2
- Selected product spreads (define explicitly)

Resulting scale:

- ~2–4 assets per product
- ~10–20 total initial registry entries

## 8. Completion Criteria

SyntheticAsset specification layer is complete when:

- [ ] canonical relative id parser implemented
- [ ] CONT builder implemented + tested
- [ ] TS builder implemented + tested
- [ ] PS builder implemented + tested
- [ ] slug grammar locked and documented
- [ ] construction_policy defined
- [ ] registry build script implemented
- [ ] registry populated for 5 products
- [ ] inspect script shows populated assets
- [ ] save/load roundtrip verified
- [ ] No Pyright errors
- [ ] All tests passing

## 9. Post-Completion State

After Session 24b:

We will have:

- Fully declarative SyntheticAsset layer
- Deterministic construction of hundreds of assets
- No manual YAML editing required
- Registry populated via code
- Full reversible identity grammar
- Clean separation between:
  - Relative rules
  - Leg bindings
  - Weights rules
  - Asset specification

This marks the end of the **static identity layer** for synthetic assets.

Next layer after this will be:

> SyntheticAsset runtime realisation (ContractSeries + WeightsSeries → TargetHoldings)

But that is Session 25+.

