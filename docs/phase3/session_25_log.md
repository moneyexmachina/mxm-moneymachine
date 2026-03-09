# Session 25 – WeightsSeries and Roll Realisation

Status: ✅ Completed  
Date: 2026-03-XX  
Scope: Synthetic Asset roll realisation and diagnostic inspection

# 1. Objective

Session 25 implemented the **WeightsSeries realisation layer**.

Conceptually:

> A `WeightsSeries` converts a `SyntheticAssetSpec` into a **time-indexed series of role weights** over trading sessions.

It bridges the gap between:

```
SyntheticAssetSpec
      ↓
ContractSeries (per role)
      ↓
Roll model (weights_rule)
      ↓
WeightsSeries
```

The result is a deterministic surface:

```
(session, role) → weight
```

This layer completes the **synthetic asset identity → exposure mapping** required before target holdings and P&L can be constructed.

# 2. Core Design

## 2.1 Responsibilities

`build_weights_series(...)` performs the following steps:

1. Instantiate the **roll model** from `weights_rule_id`
2. Realise **ContractSeries per role**
3. Infer **role pairs** from the spec
4. Compute **business days to LTD** for the pacing contract
5. Apply the roll model to compute `(cur, nxt)` weights
6. Map those weights onto the appropriate roles
7. Return a `WeightsSeries`

Key invariant:

```
WeightsSeries must be fully deterministic
given:
  SyntheticAssetSpec
  session range
  selector engine
  reference data
```

# 3. ContractSeries-Driven Roll Anchoring

An important design clarification was made during this session.

Originally, roll timing could have been anchored by:

```
explicit reference series
```

However, this proved unnecessary.

Instead:

> The pacing reference is simply the **same SelectorRule but with N=1**.

Because contract ranks are determined by **distance to last trading day**, the expiry of the front contract naturally drives:

```
rank transitions
```

This means:

```
SelectorRule(N=1)
```

is the correct pacing reference for **all ranks of the same chain**.

Advantages:

- no additional configuration
- deterministic roll clock
- compatible with all contiguous contract chains

# 4. Handling Chain Structures

The roll mechanism works correctly for **contiguous contract chains**, including:

```
Monthly chains
Quarterly chains
Filtered month chains
Seasonal chains
```

The only problematic cases arise when listing structures contain **mixed frequencies**, such as:

```
front serial months
+ longer-dated quarterlies
```

These cases must be handled at the **policy level**, not the roll engine level.

This leads to the next session's task: defining explicit chain construction policies.

# 5. Smoke Testing Infrastructure

A dedicated inspection script was implemented:

```
scripts/synthetic_assets/smoke_weights_series.py
```

Purpose:

```
human inspection
not regression testing
```

The script:

1. loads a spec from the registry
2. builds a `WeightsSeries`
3. prints diagnostic summaries

Key diagnostics:

```
role weights head
active roll rows
invariants
```

# 6. Contract-Aggregated Weight Diagnostics

During inspection it became clear that **role weights alone can be misleading**.

Role weights may change due to:

```
role relabelling
contract rank shifts
```

without any actual change in economic exposure.

To resolve this, a second diagnostic surface was introduced:

```
(contract_id → aggregated weight)
```

Construction:

```
contract_weight(session, contract_id)
    = Σ role_weights(role, session)
      where role maps to that contract_id
```

This aggregation collapses the role layer and reveals the true economic exposure.

Example output:

```
2020-01-03
  Oct-2020 = +1
  Nov-2020 = -1

2020-01-24
  Nov-2020 = +1
  Dec-2020 = -1
```

This shows the expected **calendar spread rolling behaviour**.

# 7. Verification of Roll Behaviour

Using the contract-aggregated view confirmed:

```
spread exposure advances by one contract each roll
```

Example sequence:

```
Oct / Nov
Nov / Dec
Dec / Jan
Jan / Feb
...
```

This demonstrates that:

```
WeightsSeries realisation is economically correct
```

and that the previously confusing role resets were only a **labelling artefact**.

# 8. Invariant Validation

The smoke script also verifies structural invariants.

Example for time spreads:

```
near_cur + near_nxt = +1
far_cur  + far_nxt  = -1
total exposure      = 0
```

Observed deviations were effectively zero:

```
max error ≈ 1e-12
```

confirming correct weight construction.

# 9. Outcome

Session 25 successfully delivered:

```
WeightsSeries construction
roll timing anchored on front contract expiry
diagnostic inspection tooling
contract-aggregated exposure verification
```

This completes the **synthetic asset exposure layer**.

The system can now deterministically produce:

```
(session, role) → weight
```

for any SyntheticAssetSpec.

# 10. Next Step (Session 26)

The next task is to refine **Synthetic Asset construction policy**.

Current implementation assumes:

```
L1..Ln rolling for every product
```

However several products contain **mixed listing frequencies**, such as:

```
front serial months
+ long-dated quarterlies
```

Therefore Session 26 will:

1. analyse listing structures for each product
2. identify valid **contiguous chains**
3. update policy so synthetic assets are generated only on those chains

Examples:

```
Natural Gas → monthly chain
Gold        → monthly front + Jun/Dec chain
Corn        → seasonal grain chain
GBP         → quarterly chain
ES          → quarterly chain
```

This work affects only the **policy layer**, not the roll engine.

# 11. Session Summary

Session 25 completed the **WeightsSeries realisation layer** and validated the rolling logic with detailed diagnostic tooling.

The system now correctly translates synthetic asset definitions into deterministic exposure time series, ready for the next stage of the pipeline:

```
WeightsSeries
      ↓
Target Holdings
      ↓
Trades
      ↓
P&L
```

The remaining work before moving forward is to refine the **synthetic asset construction policy** to properly reflect the listing structures of each futures product.

Session 26 will address this policy layer.
