# session_22d_plan.md — MXM V1  
## Session 22d — Build `daily_stats` Derived Surface

## Context

By the end of Session 22c, the inspection layer has been fully modularised and extended to support `statistics_1d`.

We now have:

- Dataset-scoped inspection modules:
  - `ohlcv_1d`
  - `statistics_1d`
- Attempt-plane inspection (ledger-based) for both datasets.
- Data-plane inspection for `statistics_1d` (event stream diagnostics).
- Unified CLI dispatch for inspection.
- Clean separation of:
  - Dataset semantics
  - Attempt ledger truth
  - Inspection views

Critically:

- `statistics_1d` now exposes descriptive diagnostics for settlement events.
- We have visibility into per-trading-date settlement density and flags.
- We can inspect event-level structure before deriving surfaces.

This enables the next architectural step:

> Construct the deterministic `daily_stats` derived surface.

## Objective of Session 22d

Build a canonical, deterministic, reproducible daily settlement surface derived from `statistics_1d`.

The `daily_stats` dataset will:

- Be a daily surface (one row per trading date per instrument).
- Be derived exclusively from `statistics_1d`.
- Have its own attempt ledger.
- Support inspection at contract/product/system levels.
- Serve as the canonical settlement input for synthetic assets.

## Conceptual Model

### Input

`statistics_1d` event stream (per instrument):

- Contains multiple event types (`stat_type`).
- Settlement events are identified via `stat_type == 3`.
- May contain multiple events per trading date.
- May contain provisional vs final flags.
- May contain lifecycle-limited windows.

### Output

`daily_stats` surface:

- One row per trading_date per instrument.
- Deterministic selection rule.
- Half-open window semantics aligned with MXM coverage model.
- Coverage metadata recorded.

This mirrors `ohlcv_1d`, but derived rather than vendor-native.

## Architectural Constraints

The `daily_stats` layer must:

1. Be deterministic.
2. Be idempotent.
3. Be replayable.
4. Record selection diagnostics in its attempt row.
5. Never silently discard ambiguity.
6. Separate:
   - Data-plane selection
   - Surface construction
   - Attempt recording

No business logic in the CLI.
No selection logic in inspection.
No re-derivation of semantics in product/system rollups.

## High-Level Plan

### Phase 1 — Define Deterministic Selection Rule

We must formally define:

- What qualifies as a settlement candidate?
- How to select among multiple events per trading date?
- How to handle:
  - Multiple finals
  - No final present
  - Vendor-limited windows
  - Empty expected windows
  - Late-arriving corrections

Proposed initial rule (draft):

1. Filter `stat_type == 3`
2. Group by `trading_date`
3. Prefer `is_final == True`
4. If multiple finals:
   - Select highest `sequence`
   - Or latest `ts_event`
5. If no final:
   - Use latest event
   - Mark as non-final in derived row
6. Record diagnostics:
   - Multiple finals
   - Missing final
   - Zero settlement events for date

This rule must be explicitly codified and documented.

Deliverable: `daily_stats_selection.py`

### Phase 2 — Implement Instrument-Level Derivation

Module:

    mxm/v1/marketdata/datasets/daily_stats/

Components:

- `builder.py`
  - derive_daily_stats_from_events(df)
- `store.py`
  - parquet read/write
- `coverage.py`
  - daily surface coverage windows
- `attempts_store.py`
  - DailyStatsAttemptRow

DailyStatsAttemptRow should include:

- Identity (product_id, contract_key, instrument_id, dataset)
- Surfaces (interest, lifecycle, dataset bounds)
- Expected window
- Stored row count before/after
- Diagnostics:
  - dates_without_settlement
  - dates_multiple_finals
  - total_selected_rows
  - total_source_rows
- Vendor_final propagation logic
- Status

### Phase 3 — Coverage Semantics

`daily_stats` is a daily surface.

It should mirror OHLCV coverage semantics:

- interest window
- dataset window (from statistics availability)
- lifecycle window
- available window
- expected window
- stored window
- completeness flag

Completeness definition:

A daily_stats contract is complete if:

- For every expected trading_date,
  - exactly one selected settlement row exists,
  - and if vendor_final is required, the date is final.

Completeness must be computed in coverage layer, not in orchestrator.

### Phase 4 — Product-Level Orchestration

Add daily_stats orchestration:

- Loop contracts in product.
- Build daily_stats per contract.
- Record attempt rows.
- Respect cost gating if applicable (statistics already paid).
- Ensure idempotency.

This likely mirrors:

    statistics_1d orchestration pattern.

### Phase 5 — Inspection Integration

Add:

    inspect/daily_stats/

- contracts.py
- product.py
- system.py

These mirror OHLCV structure.

Add to dispatch.

Inspection should allow:

- Contract-level surface coverage.
- Product-level rollups.
- System summary.

## Idempotency & Determinism

Session 22d must ensure:

- Re-running daily_stats without upstream changes:
  - produces identical parquet.
  - does not change stored row counts.
  - does not mutate attempt ledger beyond metadata.
- Changing selection rule requires explicit version bump.

We should consider including:

- selection_rule_version field in attempt row.

## Diagnostics Strategy

Diagnostics recorded in attempt row should include:

- count_source_events
- count_settlement_events
- count_selected_rows
- dates_missing_settlement
- dates_multiple_finals
- min_ts_event
- max_ts_event

Inspection layer should expose these without re-reading parquet.

## CLI Plan

Extend unified CLI:

    marketdata_inspect.py daily_stats contract ...
    marketdata_inspect.py daily_stats product ...
    marketdata_inspect.py daily_stats system ...

Eventually:

    marketdata_build.py daily_stats product ...

But build CLI may remain separate.


## Deliverables for Session 22d

1. `daily_stats_selection.py` — deterministic rule
2. `daily_stats/store.py` — parquet IO
3. `daily_stats/attempts_store.py`
4. `daily_stats/coverage.py`
5. Product-level orchestration
6. Idempotency test
7. Inspection modules
8. CLI dispatch integration

## Definition of Done

Session 22d is complete when:

- Running daily_stats build for:
    cme_emini_snp500_futures
  produces deterministic daily surface.
- Attempt rows are recorded.
- Inspection reports reflect completeness.
- Idempotency test passes.
- Parquet output is stable across runs.

## Strategic Significance

This step transitions MXM V1 from:

> Raw vendor ingestion

to

> Canonical derived trading surface

`daily_stats` becomes the authoritative settlement layer for:

- InstrumentSeries
- Synthetic assets
- Portfolio construction
- Backtests

It is the semantic bridge between event streams and daily portfolio logic.

## Risk Considerations

Primary risks:

- Ambiguous settlement selection logic.
- Silent multi-final collapse.
- Late-arriving corrections.
- Lifecycle window misalignment.
- Overengineering selection semantics prematurely.

Mitigation:

- Keep rule explicit and simple.
- Record diagnostics.
- Make selection versioned.
- Defer complex heuristics.

## Session Framing

Session 22c built inspection infrastructure.

Session 22d builds the first derived dataset on top of it.

This marks the shift from ingestion plumbing to semantic construction.

