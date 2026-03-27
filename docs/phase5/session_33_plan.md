# session_33_plan.md

## Session 33 — Handling Degraded Market Data & Ensuring Full-History Backtest Stability

### Summary

Following Session 32, the MXM system is now structurally sound:

- MXM business calendar successfully separates **machine-time vs exchange-time**
- Synthetic asset pipeline is stable and aligned
- Multi-year backtests (5y) run successfully

However, extending to full-history (~15 years) reveals a new class of failure:

> **Vendor-level degraded data in `statistics_1d` and derived `daily_stats`**

Session 33 focuses on:
- formally defining this failure class
- designing a robust handling strategy
- implementing repair / mitigation mechanisms
- validating via full-history synthetic asset PnL run

## Problem Statement

We are encountering failures such as:

```
Missing mark price for contract_id=..., session=..., price_field='settle_px'
```

Root cause analysis indicates:

- upstream data provider flags certain days as `degraded`
- `statistics_1d` may have:
  - missing records
  - incomplete coverage
- `daily_stats` derived dataset therefore:
  - contains gaps or missing settlement prices
- downstream systems (backtester, mark pricing):
  - assume complete coverage
  - fail hard when data is missing

## Key Insight

We now distinguish three classes of data issues:

### 1. Calendar mismatch (resolved in Session 32)
- trading day exists but no settlement data expected
- fixed via MXM business calendar

### 2. Local ingestion / derivation gaps
- incomplete or missing datasets due to pipeline issues
- repairable via targeted rebuilds

### 3. Vendor degraded data (Session 33 focus)
- upstream data is explicitly marked degraded
- may remain incomplete even after rebuild
- requires **policy and system-level handling**

## Objectives

### Primary objective

> Enable full-history (~15-year) synthetic asset PnL run without hard failures

### Secondary objectives

- define a clear **data-quality policy** for degraded days
- preserve **determinism and auditability**
- avoid silent corruption of economic results

## Workstreams

### 1. Diagnostics & Classification

#### Goal

Build a clear classification of all failing sessions.

#### Tasks

- For each failure:
  - identify `(contract_id, session)`
  - check:
    - presence in `statistics_1d`
    - presence in `daily_stats`
    - Databento dataset condition (`available` vs `degraded`)
- Build a simple diagnostic output:

```
session | contract_id | stats_present | daily_stats_present | dataset_condition
```

#### Outcome

- full list of problematic sessions
- separation into:
  - pipeline gaps
  - vendor degraded data

### 2. statistics_1d Policy

#### Question

What is the expected behaviour when upstream data is degraded?

#### Options

1. **Strict (current)**
   - accept missing data
   - downstream must handle gaps

2. **Augmented ingestion**
   - attempt alternative fetch strategies (if possible)
   - likely limited impact (vendor-side issue)

3. **Annotate quality**
   - store dataset condition alongside data
   - propagate downstream

#### Proposed direction (v1)

- keep `statistics_1d` as **raw, faithful representation**
- do not attempt to "fix" degraded data here
- optionally:
  - enrich metadata with dataset condition

### 3. daily_stats Repair Strategy

#### Core decision point

How should `daily_stats` behave when settlement data is missing?

#### Candidate strategies

##### A. Hard fail (current)
- simple
- blocks full-history runs

##### B. Drop affected sessions
- breaks time continuity
- problematic for backtesting

##### C. Forward-fill (previous settle)
- preserves continuity
- introduces controlled approximation

##### D. Hybrid (recommended)

- If missing settlement:
  - forward-fill from last valid session
- Mark the row as:
  - `is_imputed = True`
- Preserve original fields where available

#### Design principle

> **Prefer continuity with explicit annotation over silent failure**

### 4. Downstream Behaviour

#### Backtester / mark price accessor

Currently:
- assumes price must exist
- raises error if missing

#### Required changes

- allow:
  - imputed prices from `daily_stats`
- optionally:
  - log when imputed values are used
- ensure:
  - no silent inconsistencies

### 5. Implementation Plan

#### Step 1 — Diagnostics
- build temporary inspection tool or logging
- enumerate all failing sessions

#### Step 2 — daily_stats enhancement
- implement forward-fill for missing settlement
- add explicit flag (e.g. `is_imputed_settle_px`)

#### Step 3 — price accessor update
- allow use of imputed prices
- optionally log / count usage

#### Step 4 — validation tests
- ensure:
  - no NaNs in required fields
  - monotonic session continuity preserved

#### Step 5 — rerun ingestion (if needed)
- rebuild affected contracts

#### Step 6 — full-history smoke test

Run:

```
smoke_synthetic_asset_pnl.py
    start=2010-07-01
    end=2025-12-30
```

## Success Criteria

Session 33 is complete when:

- synthetic asset PnL smoke script runs over full 15-year history
- no hard failures due to missing mark prices
- imputed data is:
  - explicitly identifiable
  - limited in scope
- system behaviour remains deterministic

## Non-Goals

- perfect reconstruction of degraded vendor data
- cross-vendor reconciliation
- advanced statistical interpolation

These may be addressed in later sessions.

## Risks & Considerations

### Risk: silent data distortion

Mitigation:
- explicit imputation flags
- diagnostic reporting

### Risk: over-reliance on forward-fill

Mitigation:
- track frequency and distribution of imputed days
- later analysis of impact

### Risk: hidden structural issues

Mitigation:
- maintain strict separation:
  - raw data layer
  - derived data layer
  - execution layer

## Next Session (Session 34)

Once data robustness is achieved:

- resume performance work:
  - profiling backtests
  - scaling to longer horizons / larger universes
  - identifying bottlenecks

## Conclusion

Session 33 shifts focus from:

> **calendar correctness (Session 32)**

to:

> **data robustness under imperfect real-world conditions**

This is the final step required to make MXM v1 capable of:

- full-history backtesting
- stable research iteration
- production-grade data handling
