# Session 31 – Marketdata Identity and Coverage Repair

Status: 🟡 Planned  
Date: 2026-03-XX  
Scope: Marketdata identity mapping, `daily_stats` coverage, Databento integration

## 1. Objective

The objective of Session 31 is to:

- diagnose and repair **incorrect or incomplete marketdata identity mapping**
- ensure **complete and correct `daily_stats` coverage** for all contracts used in MXM V1
- restore the **end-to-end synthetic asset PnL smoke pipeline**

This session focuses on the **marketdata layer**, not execution or temporal semantics.

## 2. Problem Statement

### 2.1 Observed Failure

During the Session 30 smoke run:

```text
Missing execution price for:
contract_id = cme_emini_snp500_futures.Mar-2025
session     = 2025-01-02
price_field = settle_px
```

### 2.2 Diagnostic Evidence

Inspection of `daily_stats` revealed:

```text
rows for contract_id = cme_emini_snp500_futures.Mar-2025 → 3 rows total

dates:
  2025-03-19
  2025-03-20
  2025-03-21

raw_symbol = "5002"
instrument_id = 5002
```

Expected:

- continuous daily coverage leading up to expiry
- standard CME symbol (e.g. ESH5)

Observed:

- minimal coverage (3 rows)
- non-standard symbol
- likely incorrect instrument mapping

### 2.3 Conclusion

The failure is caused by:

> ❌ Incorrect or incomplete mapping from MXM refdata `contract_id`  
> → Databento instrument identity  
> → stored `daily_stats` surface

This is **not**:

- an execution bug
- a temporal modelling issue
- a backtester issue

## 3. Suspected Root Cause

The most likely failure point is:

```python
resolve_databento_instrument(...)
```

Specifically:

- incorrect mapping table entry
- incomplete mapping coverage for the contract
- fallback or default mapping being used
- incorrect join between:
  - contract metadata (expiry, symbol)
  - Databento instrument definitions

Result:

```text
Mar-2025 contract → instrument_id 5002 (incorrect)
```

instead of the correct ES March 2025 instrument.

## 4. Investigation Strategy

The investigation proceeds top-down along the identity pipeline.

### 4.1 Step 1 – Inspect Refdata Contract

Goal:

- confirm correctness of the MXM contract definition

Actions:

- retrieve contract via:
  ```python
  RefDataAPI.get_contract_by_id(...)
  ```
- inspect:
  - product_id
  - expiry
  - symbol components
  - last_trading_day

Expected:

- contract metadata is correct and complete

### 4.2 Step 2 – Inspect Databento Resolution

Goal:

- verify what `resolve_databento_instrument(...)` returns

Actions:

- call resolver explicitly for the failing contract
- print:
  - resolved instrument_id
  - dataset
  - publisher
  - raw_symbol (if available)
  - any matching keys used (symbol, expiry, etc.)

Key question:

```text
Why does Mar-2025 resolve to instrument_id = 5002?
```

### 4.3 Step 3 – Inspect Mapping Table

Goal:

- validate mapping source

Actions:

- inspect underlying mapping dataset (e.g. instrument definitions)
- check for:
  - multiple matches
  - missing entries
  - incorrect joins
  - fallback logic

Specifically:

- does a correct mapping for ES Mar-2025 exist?
- is it being ignored or overridden?

### 4.4 Step 4 – Inspect Stored Data Coverage

Goal:

- confirm whether correct data exists in the store

Actions:

- query store directly for:
  - expected instrument id for ES Mar-2025
- verify:
  - number of rows
  - date coverage
  - price fields

Key distinction:

```text
mapping wrong   → wrong instrument selected
data missing    → correct instrument, but no data
```

### 4.5 Step 5 – Cross-check Contract Identity

Goal:

- ensure consistency between layers

Check alignment between:

| Layer            | Identity                      |
|------------------|------------------------------|
| Refdata          | contract_id                  |
| Mapping          | instrument_id / symbol       |
| Marketdata store | instrument_id + dataset      |
| Canonical layer  | contract_id reassignment     |

Any mismatch here is a bug.

## 5. Repair Strategy

Depending on findings, apply one of:

### 5.1 Mapping Fix (Most Likely)

- correct resolver logic
- fix mapping table entries
- ensure correct join keys:
  - symbol
  - expiry
  - exchange
  - contract code

### 5.2 Coverage Fix

If mapping is correct but data missing:

- re-run ingestion for missing contracts
- verify:
  - OHLCV → statistics → daily_stats pipeline
- ensure no gaps for active contract periods

### 5.3 Validation Layer (Optional)

Introduce validation:

- assert minimum coverage for contracts
- detect suspicious cases:
  ```text
  < 10 rows for a futures contract → invalid
  ```

This is optional but useful.

## 6. Verification Plan

After repair:

### 6.1 Unit-level checks

- resolve contract → correct instrument_id
- read daily_stats → correct row count and date range

### 6.2 Product-level checks

- full product surface:
  - contains all active contracts
  - correct overlap across roll periods

### 6.3 Smoke pipeline

Re-run:

```bash
poetry run python scripts/pnl/smoke_synthetic_asset_pnl.py \
  --asset-id cme_emini_snp500_futures_cont_hmuz1_wr_lr_3_1 \
  --start 2025-01-02 \
  --end 2025-01-16 \
  --price-field settle_px
```

Expected:

- no missing execution prices
- successful backtest
- successful PnL construction
- output plots and metadata

## 7. Success Criteria

Session 31 is complete when:

- correct Databento identity is resolved for all contracts
- `daily_stats` coverage is complete for active periods
- smoke PnL pipeline runs end-to-end without failure
- no weakening of execution-layer guarantees was required

## 8. Non-Goals

This session does **not**:

- modify execution logic
- change temporal semantics
- introduce timestamp-based modelling
- alter PnL construction logic

## 9. Summary

Session 31 addresses a **data-layer correctness issue** exposed by Session 30.

The system is now structurally sound, and the focus shifts to:

```text
identity correctness
→ data coverage completeness
→ reliable economic evaluation
```

This is a natural and expected progression.
