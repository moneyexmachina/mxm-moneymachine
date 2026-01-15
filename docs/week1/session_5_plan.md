# MXM V1 — Session 5 Plan  
**Topic:** DataIO Integration for Databento (Request-Keyed Caching)  
**Planned Time:** 11:00–12:30  
**Date:** 2026-01-14

## Session Objective

Integrate Databento daily-bar pulls with **`mxm-dataio`** so that:

> **Identical Databento requests are never executed more than once**,  
> and subsequent runs are served from a cached response.

This must be achieved **without changing**:
- the canonical daily-bar schema,
- the Parquet marketdata store,
- or the offline serving logic proven in Session 4.

## Position in Week 1

Session 5 builds directly on Session 4.

- Session 4 established **data correctness**:
  - ingest → canonicalise → store → serve
- Session 5 establishes **cost correctness**:
  - request-keyed caching
  - safe re-runs of ingestion logic

After Session 5, MXM V1 can scale ingestion confidently.

## Scope (Strict)

### Included

- Wrap Databento `ohlcv-1d` pulls using **non-volatile** `mxm-dataio`
- Define a request identity that uniquely represents a Databento query
- Serve cached responses on repeated identical requests
- Preserve identical downstream behaviour (same DataFrame, same store state)

### Explicitly Excluded

- Instrument identity resolution or refdata integration
- Volatile/as-of bucketing logic
- Marketdata serving API
- Multi-instrument orchestration
- Backfill strategy or budgeting
- Store schema or layout changes

Any work in these areas must be logged as deferred.

## Core Architectural Decision

### Databento Volatility Model (Session 5)

- Databento daily bars are treated as **non-volatile** in DataIO
- Request identity includes explicit date range (`start`, `end`)
- No `as_of` bucketing is used in Session 5
- Explicit refresh (e.g. `force_refresh`) may be supported but is optional

Rationale:
- Databento queries are explicitly time-scoped
- “Do not ask the same question twice” is a request-level invariant
- Recent-edge volatility policies are deferred

## Request Identity Definition

A Databento `ohlcv-1d` request is uniquely identified by:

- `dataset` (e.g. `GLBX.MDP3`)
- `schema` (`ohlcv-1d`)
- `symbol`
- `stype_in`
- `start`
- `end`

This identity is used verbatim by `mxm-dataio` for cache lookup.

## Implementation Tasks

### 1) DataIO-backed pull wrapper

Create a new wrapper function, conceptually:

```
pull_ohlcv_1d_via_dataio(...)
```

Responsibilities:
- construct request identity
- consult `mxm-dataio` cache
- on cache miss:
  - execute Databento pull
  - store raw response in DataIO
- return the same DataFrame shape as the existing pull

This wrapper **replaces** the direct Databento pull used in Session 4.

### 2) Integrate wrapper into ingest flow

Modify the ingest path so that:

- cost estimation remains unchanged
- normalization remains unchanged
- Parquet store remains unchanged
- only the pull step is replaced by the DataIO-backed wrapper

This ensures:
- minimal surface-area change
- clean isolation of caching behaviour

### 3) Proof script (DataIO smoke)

Add a new proof script, e.g.:

```
93_smoke_ingest_esh6_via_dataio.py
```

This script must:

1. Run the ingest once:
   - Databento is called
   - DataIO cache is populated
2. Run the ingest again:
   - Databento is **not** called
   - DataIO cache is hit
3. Produce:
   - identical Parquet store state
   - identical read output

The script should print explicit log lines indicating:
- cache miss vs cache hit

## Success Criteria (Must Be Provable)

Session 5 is successful if and only if:

- Running the same ingest script twice:
  - hits Databento once
  - hits DataIO cache on the second run
- The Parquet store content is identical after both runs
- No changes were required to:
  - schema enforcement
  - store logic
  - read logic

## Documentation Deliverables

By the end of Session 5:

- `session_5_log.md` summarising outcomes and proof scripts
- Updates to `todo_postponed.md` for any newly deferred items
- (Optional) a short note added to `minimal_marketdata_system.md` clarifying the DataIO boundary

## Session End Condition

The session ends when:

- the DataIO-backed ingest proof script passes,
- and the cost-safety invariant (“do not ask the same question twice”) is demonstrated.

At that point, MXM V1 market data ingestion is both **correct** and **safe**.

