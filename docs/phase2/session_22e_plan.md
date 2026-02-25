# Session 22e — Plan: daily_stats Builder & Orchestration

## Context

Session 22d delivered the **pure selection layer** for `daily_stats`:

- Deterministic per-stat selection rules
- Canonical session_date normalisation
- Calendar-aware event-time mapping
- Outer-joined daily surface
- Full unit test coverage
- Clean merge into `main`

We now move from:

> pure transformation logic

to:

> a persisted, orchestrated, ledger-aware derived dataset.

Session 22e defines the builder and orchestration layer that operationalises `daily_stats`.

# High-Level Goal

Create a new derived dataset:

```
daily_stats
```

that:

- Is constructed from `statistics_1d`
- Is deterministic and idempotent
- Is computed per instrument (contract)
- Is orchestrated per product
- Can serve as downstream input for:
  - synthetic assets
  - analytics
  - evaluation layers
  - plotting/reporting

# Architecture Principles

## 1. Keep selection pure

`daily_stats/selection.py` remains:

- pure
- I/O-free
- stateless
- fully unit-tested

No orchestration logic is added there.

## 2. Builder pattern (like other datasets)

We introduce:

```
mxm.v1.marketdata.datasets.daily_stats.builder
```

Responsibilities:

- Load statistics_1d rows for a contract
- Inject session_date mapper (via TradingCalendarService)
- Call build_daily_stats_surface(...)
- Persist derived surface
- Record attempt metadata (ledger row)

## 3. Dataset Layering

```
refdata
    ↓
statistics_1d
    ↓
daily_stats
```

daily_stats is:

- strictly derived
- non-authoritative
- reproducible
- re-buildable

It does not create new truth — only reshapes existing truth.

# Scope of Session 22e

## Phase 1 — Dataset Definition

Define:

```
mxm.v1.marketdata.datasets.daily_stats/
    ├── builder.py
    ├── store.py
    ├── schema.py
    ├── api.py
```

### 1. Schema

Define canonical columns:

Required:
- session_date (datetime64[D])
- instrument_id
- publisher_id
- dataset
- raw_symbol

Value columns:
- settle_px
- open_px
- high_px
- low_px
- volume_qty
- open_interest_qty
- cleared_volume_qty
- etc.

Constraints:
- one row per (instrument_id, session_date)
- strictly increasing session_date

## Phase 2 — Store

Like other parquet stores:

```
marketdata/stores/parquet/daily_stats.py
```

Responsibilities:

- write_surface()
- load_surface()
- compute sha256
- deterministic file naming
- idempotent overwrite semantics

We decide:

- partition by instrument_id
- one parquet per contract
- sorted by session_date

## Phase 3 — Builder (Contract Level)

```
build_daily_stats_for_instrument(...)
```

Steps:

1. Load statistics_1d for instrument.
2. Resolve calendar:
   - via TradingCalendarService
   - product_id → FuturesProduct → calendar_id
3. Construct vectorised session_date mapper:
   ```
   lambda ts_series:
       calendar.as_of_session(ts_series)
   ```
   (or vectorised wrapper)
4. Call:
   ```
   build_daily_stats_surface(...)
   ```
5. Validate invariants:
   - no duplicate session_date
   - no session_date gaps inside observed coverage (optional)
6. Persist parquet.
7. Record ledger attempt.

## Phase 4 — Product-Level Orchestrator

Extend existing product orchestrator:

```
product_marketdata.py
```

Currently handles:
- instrument_definitions
- mappings
- ohlcv_1d
- statistics_1d

Add:

```
daily_stats
```

Flow per product:

```
for contract in product.contracts:
    ensure_statistics_1d(contract)
    ensure_daily_stats(contract)
```

Rules:

- daily_stats depends on statistics_1d completeness.
- daily_stats build only runs if:
    - statistics coverage changed
    - forced rebuild
    - derived coverage incomplete

# Ledger Semantics

Define attempt row:

```
DailyStatsAttemptRow
```

Fields:

- attempt_uid
- instrument_id
- dataset
- run_id
- source_statistics_coverage_start
- source_statistics_coverage_end
- derived_coverage_start
- derived_coverage_end
- rows_written
- sha256
- cost fields (likely zero)
- idempotency fields

Important:

If statistics_1d unchanged → daily_stats unchanged → no rewrite.

# Open Design Questions

## 1. Coverage Semantics

Should daily_stats coverage:

A) exactly mirror statistics_1d coverage?

or

B) reflect calendar observed coverage?

Initial plan:
- Mirror statistics coverage.
- Do not invent days.
- Do not project.

## 2. Rebuild Strategy

Options:

A) Always rebuild full contract surface
B) Incremental append
C) Coverage diff and rebuild missing region only

Initial implementation:
- Full rebuild per contract
- Idempotent overwrite
- Later optimise

## 3. Missing Stat Handling

What if settlement exists but open missing?

Policy (V1):
- Outer join
- Missing values allowed
- Diagnostics stored

No forward-filling in builder layer.

# Testing Strategy

## Unit Tests

Already done for selection layer.

Add:

- builder unit tests with small synthetic statistics_1d frame
- calendar injection test
- ensure 1 row per day invariant

## Integration Tests

Extend integration suite:

- bootstrap statistics_1d
- build daily_stats
- inspect output

Assertions:
- row count equals unique session_dates
- no duplicates
- sorted session_date

# Deliverables of 22e

By end of Session 22e:

- daily_stats dataset formally defined
- builder implemented
- contract-level orchestration complete
- product-level orchestration updated
- tests green
- inspect support (optional)
- session_22e_log.md written

# Why This Matters

daily_stats is:

- The canonical price surface for synthetic assets
- The evaluation layer for MXM returns modelling
- The human-readable summary of market state

It is the first "derived surface" sitting above vendor data.

Once stable, synthetic assets can depend solely on:

```
daily_stats
```

instead of raw vendor structures.

# Execution Plan

1. Define schema.
2. Implement store.
3. Implement contract-level builder.
4. Write unit tests.
5. Integrate into product orchestrator.
6. Run full pipeline on small product.
7. Validate idempotency.
8. Write log.

# Summary

Session 22e transitions from:

> selecting daily stats

to

> operationalising daily stats as a first-class dataset.

This completes the statistics onboarding arc and prepares the ground for synthetic asset construction.
