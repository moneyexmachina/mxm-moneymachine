# Session 27 – Target Holdings Construction for Synthetic Assets

Status: Planned  
Scope: Convert `WeightsSeries` into concrete **contract target holdings**

# 1. Objective

Session 27 introduces the layer that converts a **SyntheticAssetSpec + WeightsSeries**
into **target holdings of concrete contracts**.

Up to Session 26 the system can:

1. Define synthetic assets (`SyntheticAssetSpec`)
2. Resolve their contract legs (`SelectorRule`)
3. Build a time series of **role weights** (`WeightsSeries`)
4. Realise those weights onto **actual contract IDs**

What does not yet exist is the mapping from these weights to **actual contract
quantities**.

This session implements that mapping.

# 2. Conceptual Model

A synthetic asset represents exposure equivalent to **one synthetic contract**.

That synthetic contract has:

```
(currency, unit, size)
```

Example:

```
currency = USD
unit     = BUSHEL
size     = 5000
```

To replicate this exposure using actual futures contracts we must transform:

```
WeightsSeries
```

into

```
TargetHoldingsSeries
```

where the holdings are **contract quantities per session**.

The transformation must account for:

1. **leg weights**
2. **sign conventions**
3. **unit conversions**
4. **size scaling**
5. **currency conversion**

# 3. Target Holdings Equation

For a given session and contract:

```
contracts =
    synthetic_quantity
  × leg_weight
  × unit_conversion_factor
  × fx_conversion_factor
  × synthetic_size
  ÷ underlying_contract_size
```

Where:

```
synthetic_quantity = 1
```

because we compute the holdings corresponding to **one synthetic contract**.

# 4. Transformations Required

## 4.1 FX Conversion

If synthetic asset currency differs from the underlying product currency,
an FX conversion is required.

For Session 27:

```
FXConverter
```

will exist only as an **interface / stub**.

Behaviour:

```
if synthetic_currency == product_currency:
    factor = 1
else:
    raise NotImplementedError
```

FX support will be implemented later when FX products are integrated.

## 4.2 Unit Conversion

Contracts may express physical size in different units.

Examples:

| Asset | Unit |
|------|------|
| Gold | TROY_OUNCE |
| Natural Gas | MMBTU |
| Power | MWH |

Synthetic assets may choose a different unit representation.

Therefore we introduce:

```
UnitConverter
```

Capabilities:

```
conversion_factor(from_unit, to_unit) -> float
```

Constraints:

- conversions are **explicit and family-scoped**
- unsupported conversions must **fail loudly**

Example families:

Energy
```
MMBTU
THERM
MWH
```

Metals
```
TROY_OUNCE
GRAM
KILOGRAM
```

Agriculture
```
BUSHEL
TONNE
POUND
```

## 4.3 Contract Size Scaling

Synthetic assets define their own contract size.

Example:

```
synthetic_size = 10000
underlying_contract_size = 5000
```

This implies:

```
1 synthetic contract = 2 underlying contracts
```

Therefore contract holdings must be scaled accordingly.

This scaling is independent of weights.

# 5. Sign Semantics by Asset Type

WeightsSeries expresses **role weights**, not position direction.

Direction must be applied according to synthetic asset type.

## Continuous Roll (CONT)

```
+ cur
+ nxt
```

Weights sum to 1.

## Time Spread (TS)

```
+ near
- far
```

Each leg is itself a rolling basket:

```
+ near_cur
+ near_nxt
- far_cur
- far_nxt
```

## Product Spread (PS)

```
+ product A
- product B
```

Each side contains its own roll basket.

# 6. New Output Object

Introduce:

```
TargetHoldingsSeries
```

Concept:

```
index   : trading session
columns : contract_id
values  : contract quantities
```

Example:

| session | NGH2025 | NGJ2025 |
|-------|--------|--------|
| t1 | 0.7 | 0.3 |
| t2 | 0.5 | 0.5 |
| t3 | 0.2 | 0.8 |

Values represent **contracts to hold** to replicate one synthetic asset.

# 7. Core Builder

Primary entry point:

```
build_target_holdings_series(...)
```

Inputs:

```
SyntheticAssetSpec
WeightsSeries
Contract metadata lookup
UnitConverter
FXConverter
```

Responsibilities:

1. Resolve realised contracts from weights
2. Compute scaling factors
3. Apply sign conventions
4. Produce session-indexed contract holdings

The function should remain **pure**.

# 8. Contract Metadata Requirements

The builder must access authoritative contract information:

```
contract_id
currency
unit
contract_size
```

This should come from the contract registry layer.

For V1 most products share unit/currency at product level, but the
builder should use **contract-level metadata** where available.

# 9. Invariants

Target holdings must satisfy:

### Weight Conservation

For CONT:

```
sum(role_weights) = 1
```

For spreads:

```
sum(long_weights) = sum(short_weights)
```

### Contract Consistency

```
target holdings must reference only realised contracts
```

### Exposure Consistency

Holding the computed contract basket must replicate exactly
one synthetic asset exposure:

```
synthetic exposure = contract exposure
```

# 10. Testing Strategy

New test module:

```
test_target_holdings.py
```

Test cases:

### Continuous roll

Verify:

```
weights → contract quantities
```

Example:

```
synthetic_size = underlying_size
```

Expected:

```
cur=0.7
nxt=0.3
```

### Size scaling

Test:

```
synthetic_size = 2 × contract_size
```

Expected:

```
cur=1.4
nxt=0.6
```

### Unit conversion

Example:

```
synthetic_unit = MWH
contract_unit  = MMBTU
```

Check conversion applied correctly.

### FX mismatch

Verify builder raises:

```
NotImplementedError
```

when currencies differ.

# 11. Expected Outcome

After Session 27 the system will support:

```
SyntheticAssetSpec
        ↓
WeightsSeries
        ↓
TargetHoldingsSeries
```

This enables the next major layer:

```
trade derivation
execution
PnL calculation
```

because synthetic assets will now correspond to **explicit tradable
contract baskets**.

# 12. Deliverables

New modules:

```
synthetic_assets/
    target_holdings.py
    unit_conversion.py
    fx_converter.py
```

New model:

```
TargetHoldingsSeries
```

New builder:

```
build_target_holdings_series(...)
```

New tests:

```
tests/.../test_target_holdings.py
```

# 13. Design Principle

This layer establishes the key invariant of the synthetic asset system:

> One synthetic contract must correspond to a deterministic basket of
> underlying contracts whose combined exposure exactly matches the
> synthetic asset definition.

This invariant is what allows synthetic assets to behave exactly like
tradable instruments within the broader MXM system.
