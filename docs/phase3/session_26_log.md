# Session 26 – Refine Synthetic Asset Construction Policy

Status: ✅ Completed  
Date: 2026-03-XX  
Scope: Synthetic asset construction policy, selector naming semantics, policy compiler, and registry surface validation.

# 1. Objective

Session 26 restructured the **synthetic asset construction policy** to ensure that synthetic assets are only generated on **coherent contract selector families**.

The previous design implicitly treated the *listed chain* as a privileged structure and generated generic `L1..Ln` rolling assets for every product.

This approach was insufficient for products whose listing surfaces mix multiple contract families, such as:

- serial + quarterly contracts
- monthly front chains + long-dated semiannual chains
- agricultural seasonal delivery cycles

The new design replaces the “generic listed chain” concept with **explicitly authored PeriodFilter families** per product.

This ensures that:

- rolling chains correspond to real contract cycles
- selector ranks represent homogeneous distance-to-delivery steps
- generated synthetic assets are economically meaningful.

# 2. Core Design Principle

Synthetic assets must be constructed on **explicit selector families** defined via `PeriodFilter`.

Conceptually:

```
product
    → PeriodFilter family
        → ranked contract selection (N=1..k)
            → synthetic assets (CONT, TS, PS)
```

A family is defined by:

- a `PeriodFilter`
- the maximum CONT depth
- the maximum TS depth.

Examples of families:

| Family | Meaning |
|------|------|
| `M` | full calendar month ladder |
| `HMUZ` | quarterly cycle (Mar/Jun/Sep/Dec) |
| `HKNUZ` | grain seasonal cycle |
| `JunDec` | semiannual cycle |
| `Mar`, `Jul`, etc. | repeating single delivery month |

These families are authored directly in `construction_policy.py`.

# 3. Policy Authoring Changes

The construction policy module was rewritten to express **families explicitly**.

Old model:

```
product
    → listed chain
    → optional fixed months
```

New model:

```
product
    → list of PeriodFilter families
        → each with explicit CONT / TS depths
```

This allows different products to express their true contract structures.

Examples:

### Gold

- `M1..M22`
- `Jan1..Jan2` etc. for all months
- `JunDec1..JunDec5`

### Natural Gas

- `M1..M70`
- fixed calendar months `Jan1..Jan5`, etc.

### GBP

- `M1..M3` front serials
- `HMUZ1..HMUZ20`
- singleton `Mar`, `Jun`, `Sep`, `Dec` families

### ES

- `HMUZ1..HMUZ20`
- singleton quarterly months

### Corn

- `HKNUZ1..HKNUZ8`
- singleton seasonal months (`Mar`, `May`, `Jul`, `Sep`, `Dec`)

# 4. Selector Naming Improvements

The ergonomic selector naming logic (`short_rel_id`) was updated to support the new family semantics.

New rules for `CALENDAR_MONTHS` selectors:

| Cycle elements | Example | Output |
|------|------|------|
| none | listed chain | `L1` |
| all months | `{1..12}` | `M1` |
| one month | `{3}` | `Mar1` |
| two months | `{6,12}` | `JunDec1` |
| ≥3 months | `{3,6,9,12}` | `HMUZ1` |

For larger subsets, **futures month letters** are used:

| Elements | Output |
|------|------|
| `{3,6,9,12}` | `HMUZ` |
| `{3,5,7,9,12}` | `HKNUZ` |

This allows synthetic asset IDs to naturally reflect their contract cycle.

Example:

```
cbot_corn_futures_cont_jul1_wr_lr_3_1
```

# 5. Policy Compiler Refactor

`policy_compile.py` was rewritten to align with the new policy model.

Key changes:

- compiler now accepts **`FuturesProduct` directly**
- no duck-typed product wrappers
- no implicit listed-chain construction
- selector rules derived directly from authored `PeriodFilter` families.

Compilation steps:

1. Validate products referenced by policy.
2. For each product family:
   - generate CONT assets
   - generate TS assets
3. For each spread policy:
   - generate family-compatible PS assets.

Asset IDs are produced by `spec_builder.py` using `short_rel_id`.

# 6. Test Suite Updates

Several test modules were updated.

### `relative_ids` tests

Updated to reflect the new naming semantics:

New coverage:

- `M1`
- `Mar1`
- `JunDec1`
- `HMUZ1`
- `HKNUZ1`

Legacy fallback behaviour for unknown cycles remains tested.

### `policy_compile` tests

Tests were rewritten to:

- use real `FuturesProduct` objects
- use enum types (`Currency`, `ProductUnit`, `SettlementMethod`)
- validate deterministic compilation.

The new policy produces:

```
526 synthetic asset specifications
```

Breakdown:

| Product | Specs |
|------|------|
| Gold | 88 |
| Natural Gas | 247 |
| GBP | 80 |
| ES | 75 |
| Corn | 30 |
| Product spreads | 6 |
| **Total** | **526** |

# 7. Registry Build Verification

The registry build script was executed:

```
scripts/synthetic_assets/ops_build_registry.py --dry-run
```

Output confirmed:

```
done: 526 specs
```

Asset IDs reflect the new naming semantics.

Example:

```
nymex_natural_gas_futures_ts_m8_m9_wr_lr_3_1
cbot_corn_futures_cont_jul1_wr_lr_3_1
```

# 8. Synthetic Asset Inspection

The inspection tool successfully resolved selector bindings.

Example:

```
cbot_corn_futures_cont_jul1_wr_lr_3_1
```

Leg bindings:

```
cur -> RC::PT=MONTH::CYCLE=CALENDAR_MONTHS[7]::RANK=LTD::N=1
nxt -> RC::PT=MONTH::CYCLE=CALENDAR_MONTHS[7]::RANK=LTD::N=2
```

This corresponds to the **July delivery cycle**, rolling annually.

# 9. WeightsSeries Smoke Verification

Smoke tests confirmed correct contract realisation.

Example:

```
cbot_corn_futures_cont_jul1_wr_lr_3_1
```

Realised sequence:

```
Jul-2020
Jul-2021
Jul-2022
Jul-2023
Jul-2024
Jul-2025
```

Contract transitions occur exactly when the next delivery year becomes the front member of the July selector family.

The resulting series satisfies all invariants:

```
cur + nxt = 1
0 ≤ weights ≤ 1
```

# 10. Future Work Note – Roll Parameterisation

The current policy uses a **single roll rule**:

```
LINEAR_ROLL
roll_start_offset = 3
roll_duration = 1
```

This is appropriate for frequently rolling contracts.

However, some families roll **very infrequently**, for example:

- fixed-month annual families (`Jul1`, `Dec1`, etc.)
- seasonal agricultural cycles.

These may benefit from **different roll parameters**, such as:

- earlier roll start
- longer roll window
- potentially family-specific rules.

This refinement will likely occur during:

```
synthetic asset characterisation
strategy construction
```

when liquidity and execution considerations are evaluated.

For Session 26, a single rule was intentionally retained to keep the system simple and deterministic.

# 11. Outcome

Session 26 successfully:

- replaced generic listed-chain construction with **explicit selector families**
- improved selector naming semantics
- simplified the policy compiler
- aligned tests with authoritative refdata models
- validated the full registry build and weights realisation.

The synthetic asset layer now produces a **structurally correct asset universe aligned with real contract cycles**.

This completes the policy refactor and prepares the system for the next layer of development.
