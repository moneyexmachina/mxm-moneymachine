# session_21_plan.md — MXM V1
## Session 21 — Databento Statistics `statistics_1d` (Settlement-First Ingestion)

## Phase
P2 — Marketdata Completion (return from P3 synthetic assets)

## Status
planned

## Session intent

Session 21 introduces a new MarketData dataset:

> `datasets/statistics_1d/`

sourced from Databento:

- dataset: `GLBX.MDP3`
- schema: `statistics`
- rtype: 24

The primary objective is to establish a reliable **daily settlement surface**
(`stat_type=3`) suitable for:

- mark-to-market series
- risk and return diagnostics
- synthetic asset validation
- roll sanity checks
- research workflows

This session prioritises **momentum and correctness over architectural generalisation**.

We will:
- copy the working `ohlcv_1d` ingestion skeleton,
- adapt it for `statistics`,
- validate semantics empirically,
- defer refactoring until behaviour is proven.

## Scope

### In scope

1. Create dataset module:
   `mxm/v1/marketdata/datasets/statistics_1d/`

2. Implement:
   - deterministic expected window generation
   - DataIO pull for `schema=statistics`
   - Parquet persistence (raw rows)
   - SQLite attempts store
   - minimal coverage snapshot
   - proof script

3. Settlement-first validation:
   - confirm presence of `stat_type=3`
   - validate `ts_ref → trading_date`
   - confirm dedupe key stability

### Out of scope

- Generic multi-dataset controller refactor
- Market-state wide daily table
- Full decoding of `stat_flags`
- Venue timezone reinterpretation
- Final/preliminary settlement logic refinement
- Cross-product analytics

## Naming

Dataset name:

> `statistics_1d`

Rationale:
- daily, trading-date keyed
- aligned with `ohlcv_1d`
- explicit that this is not a raw tick stream

## V1 Semantics

### Primary statistic

- `stat_type = 3` — Settlement (primary)

Additional types ingested but not completeness-critical:

- `stat_type = 9` — Open interest
- `stat_type = 6` — Cleared volume
- `stat_type = 11` — Close price

All stat types are stored raw.

## Trading Date Derivation (V1)

Definition:

```
trading_date := date(ts_ref in UTC)
```

Persist:
- raw `ts_ref`
- derived `trading_date`

No timezone reinterpretation yet.
Raw timestamps allow future correction.

## Price Handling

Databento price scale:

```
price (int64) → price_f = price * 1e-9
```

Persist:
- raw `price`
- derived `price_f` (optional but recommended for inspect convenience)

Sentinels:
- stored raw unchanged
- cleaning handled in inspect layer only

## Deduplication Key (Initial Candidate)

```
(instrument_id, stat_type, ts_ref, sequence)
```

This will be validated in proof script.

No aggressive dedupe logic in Session 21.
If duplicates occur, they are detected and reported.

## Implementation Plan

### Step 0 — Copy Skeleton

Copy structure from:

```
datasets/ohlcv_1d/
```

Create:

- expected.py
- ingest.py
- orchestrator.py
- attempts_store.py
- coverage_store.py
- inspect.py
- schema.py (constants only)
- __init__.py

Keep changes minimal and local.

### Step 1 — Expected Windows

Reuse OHLCV chunking logic (monthly windows unless proven inadequate).

Statistics emits multiple rows per day, but windowing remains time-based.

### Step 2 — DataIO Pull

Request parameters:

- adapter: databento
- dataset: GLBX.MDP3
- schema: statistics
- stype_in: consistent with product-root conventions
- symbol: product-root scope
- time range: window bounds

Ensure:
- rtype == 24 for all stored rows

### Step 3 — Parse and Derive

From returned records:

- derive `trading_date`
- optionally compute `price_f`
- validate rtype

### Step 4 — Parquet Persistence

Raw columns:

- ts_recv
- ts_event
- ts_ref
- sequence
- ts_in_delta
- rtype
- stat_type
- publisher_id
- channel_id
- instrument_id
- update_action
- stat_flags
- price
- quantity
- symbol
- trading_date
- price_f (optional)

Partitioning:
- follow OHLCV style
- minimum: product scope + year/month

Session 21 allows append-style writes.
Partition rewrite optimisation deferred.

### Step 5 — Attempts Store

Create:

```
statistics_1d_attempts
```

Fields:

- attempt_id
- ts_created
- scope identifiers
- window start/end
- request hash
- status
- status_detail
- row_count
- error fields
- optional dataset_version

### Step 6 — Coverage Snapshot

Create:

```
statistics_1d_coverage
```

Fields:

- product_id
- min_trading_date
- max_trading_date
- row_count

Simple min/max aggregation sufficient for Session 21.

### Step 7 — Orchestrator

Modes:

- bootstrap
- update

Minimal V1 update rule:
- always refresh last N days (e.g. 5)
- older data assumed stable

Completeness (V1):

A trading_date is complete if:
- at least one `stat_type=3` exists per instrument in scope

Final/preliminary distinction deferred.

## Proof Script

Create:

```
scripts/marketdata/96_smoke_persist_statistics_1d.py
```

Script must:

1. Optionally reset DB
2. Ingest short window (e.g. 10 trading days for ES)
3. Print:

   - total rows
   - rows by stat_type
   - sample settlement rows
   - distinct trading dates
   - distinct instrument_ids
   - duplicates under dedupe key
   - distribution of ts_ref hour (sanity)

4. Re-run same window and confirm no uncontrolled duplication

## Definition of Done

Session 21 is complete when:

1. Proof script persists statistics rows to Parquet.
2. Settlement rows (`stat_type=3`) are present and printable.
3. Coverage snapshot reflects correct min/max trading_date.
4. Attempts store records successful ingestion.
5. Re-run of same window does not explode row counts.
6. Dedupe key stability validated.

## Follow-On (Session 22+)

- Extract shared orchestration between OHLCV and statistics.
- Decode `stat_flags` prelim/final.
- Create curated settlement view.
- Add health/completeness reporting.
- Consider partition rewrite strategy.

## Git

Branch:
`feature/statistics-1d-ingestion`

Commit structure:
1. skeleton
2. ingest + persistence
3. proof + validation
