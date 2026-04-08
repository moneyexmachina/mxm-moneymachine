# session_33_plan.md

## Session 33 — Handling Degraded Market Data & Ensuring Full-History Backtest Stability

## Summary
 
Following Sessions 33a and 33b, the MXM system now has:

- a canonical timestamp model (`np.datetime64[ns]`, UTC, kernel/boundary separation)
- a first-class MXM business calendar defining the operating session domain
- a synthetic asset pipeline fully aligned to MXM business-session support

However, extending to full-history (~15 years) reveals a new class of failure:

> **Missing or degraded market data when projected onto MXM business-session support**

This is no longer a calendar problem, but a **data availability and valuation problem**.

Session 33 focuses on:

- defining how market data is projected onto MXM business sessions
- designing curated datasets (`daily_mark`, `daily_volume`)
- implementing explicit policies for degraded or missing data
- validating via full-history synthetic asset PnL runs

## Problem Statement

Failures occur when evaluating synthetic assets on MXM business-session support:

```
Missing mark price for contract_id=..., session=..., price_field='settle_px'
```

### Root cause

- MXM business sessions exist independently of trading-session availability
- `daily_stats` is:
  - trading-session aligned
  - incomplete on certain days (vendor degraded data)
- mapping from trading sessions → business sessions introduces gaps

Therefore:

> **MXM requires explicit policy for valuing assets on sessions where market data is missing or degraded**

## Key Insight

We now distinguish three distinct layers:

### 1. TradingCalendar (market-time reality)
- exchange trading sessions
- used for:
  - contract selection
  - LTD offsets
  - roll timing

### 2. MXMBusinessCalendar (machine-time reality)
- MXM operating / valuation sessions
- defines:
  - support of synthetic assets
  - support of target holdings
  - support of daily valuation

### 3. Curated daily datasets (Session 33 focus)
- `daily_mark`
- `daily_volume`

These datasets:

- live on MXM business-session support
- encode:
  - observed values
  - fallback logic
  - carry policy
  - data quality

## Objectives

### Primary objective

> Enable full-history (~15-year) synthetic asset PnL run without hard failures

### Secondary objectives

- define a clear **data-quality policy** for degraded days
- preserve **determinism and auditability**
- avoid silent corruption of economic results
- separate:
  - support definition
  - data availability
  - valuation policy

## Workstreams

### 1. Diagnostics & Classification

#### Goal

Build a clear classification of all failing `(contract_id, session)` pairs.

#### Tasks

For each failure:

- identify:
  - `contract_id`
  - `session` (MXM business session)

- check:
  - mapping to trading session (via `how="prev"`)
  - presence in `statistics_1d`
  - presence in `daily_stats`
  - vendor dataset condition (`available`, `degraded`, etc.)

#### Output

Diagnostic table:

```
session | contract_id | trading_session | stats_present | daily_stats_present | dataset_condition
```

#### Outcome

Clear separation into:

- pipeline gaps (fixable)
- vendor degraded data (policy-driven)

### 2. statistics_1d Policy

#### Question

What is the expected behaviour when upstream data is degraded?

#### Decision (v1)

- `statistics_1d` remains:
  - **raw**
  - **faithful**
  - **unaltered**

- no attempt to "repair" vendor data here

Optional:

- propagate dataset condition metadata downstream

#### Principle

> Raw data layer is descriptive, not corrective

### 3. daily_mark Dataset Design (replaces daily_stats repair)

#### Core decision point

How should MXM assign a mark price for each:

```
(session, contract_id)
```

on MXM business-session support?

#### Proposed dataset: `daily_mark`

Conceptual schema:

```
session
contract_id
instrument_id (optional)
mark_px
mark_source
mark_quality
is_markable
is_carried
carry_streak
source_session
source_dataset
```

#### Policy hierarchy (v1)

For each `(session, contract_id)`:

1. **Primary (preferred)**
   - use `settle_px` from `daily_stats`
   - `mark_source = "settle"`
   - `mark_quality = "final"`

2. **Fallback (observed)**
   - use alternative price (e.g. `close_px`)
   - `mark_source = "close"`
   - `mark_quality = "observed_fallback"`

3. **Carry-forward**
   - use previous valid mark
   - `mark_source = "carry"`
   - `mark_quality = "carried"`
   - track `carry_streak`

4. **Unavailable**
   - no valid source exists
   - `is_markable = False`
   - `mark_quality = "unavailable"`

#### Design principle

> **Separate support (session exists) from data availability (mark may be observed, fallback, carried, or unavailable)**

### 4. daily_volume Dataset (parallel)

#### Motivation

Execution and liquidity analysis require volume.

#### Proposed dataset: `daily_volume`

- same MXM business-session support
- similar projection and fallback logic
- explicit handling of:
  - zero volume (valid)
  - missing volume (data issue)

#### Policy (v1)

- prefer observed volume
- do not forward-fill volume by default
- allow explicit `is_missing` flag

### 5. Downstream Behaviour

#### Backtester / mark price accessor

Must:

- consume `daily_mark`, not raw `daily_stats`
- allow:
  - carried marks
  - fallback marks
- optionally:
  - log or count non-final marks

Must ensure:

- no NaNs for markable assets
- deterministic behaviour

#### Key principle

> Downstream systems consume curated data, not raw vendor data

### 6. Implementation Plan

#### Step 1 — Diagnostics

- enumerate all failing `(contract_id, session)` pairs
- classify failures

#### Step 2 — daily_mark builder

- implement:
  - business → trading session mapping (`how="prev"`)
  - mark selection hierarchy
  - carry-forward logic
  - quality flags

#### Step 3 — daily_volume builder (optional, parallel)

- similar projection logic
- explicit missing/zero distinction

#### Step 4 — price accessor refactor

- switch valuation to `daily_mark`
- remove direct dependency on `daily_stats`

#### Step 5 — validation

- assert:
  - no NaNs in markable rows
  - correct carry behaviour
  - correct quality labeling
  - stable deterministic output

#### Step 6 — full-history run

Run:

```
smoke_synthetic_asset_pnl.py
    start=2010-07-01
    end=2025-12-30
```

## Success Criteria

Session 33 is complete when:

- `daily_mark` dataset exists and is used for valuation
- synthetic asset PnL runs over full 15-year history without failure
- all non-final marks are:
  - explicitly labeled
  - auditable
- system behaviour remains deterministic

## Non-Goals

- perfect reconstruction of degraded vendor data
- cross-vendor reconciliation
- advanced statistical interpolation
- intraday modelling

These may be addressed in later sessions.

## Risks & Considerations

### Risk: silent data distortion

Mitigation:

- explicit quality flags
- diagnostic reporting
- auditability of mark source

### Risk: over-reliance on carry-forward

Mitigation:

- track:
  - frequency
  - duration (`carry_streak`)
- analyze impact later

### Risk: hidden structural issues

Mitigation:

- strict separation:
  - raw data layer (`statistics_1d`)
  - derived trading-session layer (`daily_stats`)
  - curated business-session layer (`daily_mark`)
  - execution layer

## Next Session (Session 34)

Once data robustness is achieved:

- resume performance work:
  - profiling backtests
  - scaling to longer horizons / larger universes
  - identifying bottlenecks

## Conclusion

Session 33 completes the transition from:

> **calendar correctness (Sessions 32–33a)**

to:

> **robust valuation under imperfect real-world data conditions**

The system evolves from:

> reacting to missing data

to:

> explicitly defining how MXM values the world when data is incomplete

This is the final step required to make MXM v1 capable of:

- full-history backtesting
- stable research iteration
- production-grade data handling
