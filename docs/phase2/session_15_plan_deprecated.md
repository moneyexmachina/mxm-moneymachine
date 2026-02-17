# session_15_plan.md

## Session 15 — Ingest Databento Statistics (GLBX.MDP3) for daily settlements (V1)

### Objective
Add a new MarketData dataset for Databento **Statistics** (`schema=statistics`, `rtype=24`) for **GLBX.MDP3**, with initial V1 focus on **Settlement price** (stat_type=3) and optional support for a small set of additional stats (OI, volume, close) for diagnostics.

This dataset will sit alongside:
- `datasets/instrument_definitions/`
- `datasets/instrument_definition_mappings/`
- `datasets/ohlcv_1d/`

and will follow the same MXM-V1 ingestion patterns:
- deterministic expected-window generation
- DataIO caching keyed by request
- attempts store for auditability and cost-awareness
- coverage snapshot + completeness semantics
- an inspect/report surface consistent with the rest of marketdata

### Deliverable Summary
By end of session:
1. A new dataset directory: `mxm/v1/marketdata/datasets/statistics_1d/` (name to be finalised; see Naming)
2. A working orchestrator that ingests a date window for one product scope (e.g. ES futures) and persists:
   - raw statistics rows (Parquet)
   - metadata / attempts / coverage (SQLite)
3. A minimal “proof” script analogous to `95_smoke_*` that:
   - resets db
   - ingests a known window
   - prints a coverage report and a sample of settlement rows

## Naming and Scope

### Dataset naming decision
We have two plausible names:

- **Option A (preferred):** `statistics_1d`
  - Semantics: “official statistics keyed by trading date; daily-aggregated state facts”.
  - Matches other daily datasets in `datasets/`.

- **Option B:** `statistics`
  - Semantics: raw event stream; less explicit about daily use.

For V1 we are ingesting daily statistics by trading date; therefore use:

> `datasets/statistics_1d/`

### V1 stat types to ingest
We will ingest all received stat types into the raw Parquet, but we will define **completeness** and primary reporting around:

- `stat_type=3` Settlement price (primary mark for modelling)
- `stat_type=9` Open interest (optional; useful)
- `stat_type=6` Cleared volume (optional; useful)
- `stat_type=11` Close price (optional QC / comparison)

We will not build market modelling or the derived `market_state_1d` layer in this session; only ingestion and coverage/proofs.

## Key Semantics to Nail Down (V1)

### Trading date derivation
Statistics messages have:
- `ts_ref` (reference timestamp; venue-defined anchor)
- `ts_event`, `ts_recv` (publication / capture timestamps)

For V1 we define:

- `trading_date := date(ts_ref in UTC)` (initial)
- store `ts_ref` and `trading_date` in persisted rows

Note: If later we discover `ts_ref` needs venue timezone conversion, we will update the derivation logic; do not over-engineer now. The storage should retain raw `ts_ref` so we can re-derive.

### Price scaling
Databento `price` is an int64 with 1e-9 scale.

We will:
- persist raw `price` as int64 in Parquet
- persist a derived `price_f` float64 for convenience (optional)
- centralise conversion via a shared helper (or local helper in dataset module)

### Null / missing encoding
Inapplicable values use max-of-type sentinels. We will:
- normalise sentinels to `None` in our parsed rows (for derived views)
- keep raw values unchanged in persisted raw Parquet to preserve provenance

For ingestion and storage, we can keep raw values and offer a “clean view” function for inspection.

## Implementation Plan

### 0) Copy the OHLCV ingestion skeleton
Use `datasets/ohlcv_1d/` as the structural reference and replicate the patterns:

- `expected.py` — defines expected windows
- `ingest.py` — fetch from DataIO and persist
- `orchestrator.py` — state machine: bootstrap/update, attempt tracking, completeness
- `attempts_store.py` — audit table for requests + outcomes
- `coverage_store.py` — quick min/max/rows coverage snapshot per scope
- `inspect.py` — summary report utilities
- `types.py` — TypedDict/dataclass for parsed rows (optional, keep lightweight)
- `__init__.py`

The goal is to minimise novelty: same lifecycle, different schema.

## 1) Create dataset module structure
Create:

- `mxm/v1/marketdata/datasets/statistics_1d/__init__.py`
- `mxm/v1/marketdata/datasets/statistics_1d/expected.py`
- `mxm/v1/marketdata/datasets/statistics_1d/ingest.py`
- `mxm/v1/marketdata/datasets/statistics_1d/orchestrator.py`
- `mxm/v1/marketdata/datasets/statistics_1d/attempts_store.py`
- `mxm/v1/marketdata/datasets/statistics_1d/coverage_store.py`
- `mxm/v1/marketdata/datasets/statistics_1d/inspect.py`
- `mxm/v1/marketdata/datasets/statistics_1d/schema.py` (optional, for constants)

Add any required exports / entry points consistent with other datasets.

## 2) Define expected windows (`expected.py`)
### Inputs
- start/end date window (UTC date)
- product scope (product_id, dataset_id, symbol/stype_in conventions)

### Output
- list of `ExpectedWindow` objects (or dataset-equivalent) covering the date range in chunks
  - choose same chunk size policy as OHLCV (e.g. monthly windows) unless proven too large/small

### Notes
Statistics may emit multiple rows per instrument per day; expected windows are still time-based.

## 3) Define persistence formats

### 3.1 Parquet raw table
Partition suggestion:
- partition by `product_id` and `trading_date` (or year/month) depending on existing conventions
- keep consistent with OHLCV partition style

Schema columns to persist (raw):
- `ts_recv` (int64 ns)
- `ts_event` (int64 ns)
- `ts_ref` (int64 ns)
- `sequence` (int32 or int64)
- `ts_in_delta` (int32)
- `rtype` (uint8)
- `stat_type` (uint16)
- `publisher_id` (uint16)
- `channel_id` (uint16)
- `instrument_id` (uint32)
- `update_action` (uint8)
- `stat_flags` (uint8)
- `price` (int64)
- `quantity` (int64)
- `symbol` (string)
- derived:
  - `trading_date` (date) (derived from ts_ref, V1 UTC)
  - `price_f` (float64) (optional convenience; deterministic conversion)

### 3.2 SQLite metadata tables
Follow OHLCV pattern:
- attempts table
- coverage snapshot table (min/max ts_ref or trading_date, row counts)
- optionally: window-level status records if you have a generic dataset status model

## 4) Implement attempts store (`attempts_store.py`)
Define:
- `TABLE = "statistics_1d_attempts"`

Record fields (minimum):
- `attempt_id` (uuid)
- `ts_created`
- scope identifiers: `product_id`, `dataset_id`, `schema="statistics"`, `stype_in`, `symbol`
- window: `start_ts`, `end_ts` (or start_date/end_date)
- request hash / DataIO request key
- outcome: success/fail, error summary, row count, billable size/cost estimate if available
- completeness marker: `has_settlement`, `has_final_settlement` (optional at attempt time)
- status tags consistent with the marketdata semantic hardening work:
  - `status` (coarse)
  - `status_detail` (fine)

Implementation target: match OHLCV attempt store style and keep it simple.

## 5) Implement coverage snapshot store (`coverage_store.py`)
Define:
- `TABLE = "statistics_1d_coverage"`

Coverage snapshot fields (minimum):
- scope identifiers (product_id, dataset_id, symbol, stype_in)
- `min_trading_date`, `max_trading_date`
- `row_count`
- optionally: counts by stat_type (but that may belong in inspect/report)

Start simple:
- min/max trading_date from stored Parquet metadata index or by querying SQLite if you store summaries there.

## 6) Implement ingest (`ingest.py`)
### 6.1 DataIO request construction
- adapter: databento
- dataset: `GLBX.MDP3`
- schema: `statistics`
- symbol/stype_in: same scope as instrument definitions / OHLCV (likely `stype_in=parent`, symbol root / parent)
- time window: based on expected windows

### 6.2 Response handling
- parse records into a DataFrame
- derive:
  - `trading_date` from `ts_ref`
  - `price_f` from `price` if you want the convenience column
- persist to Parquet store
- update attempts and coverage

### 6.3 Idempotency
- use DataIO cache key to avoid repeated vendor pulls
- ensure Parquet persistence is stable under re-runs
- if duplicates can occur, dedupe by a stable key (see below)

#### Deduplication key (candidate)
For statistics, a stable uniqueness key is typically:
- `(instrument_id, stat_type, ts_ref, sequence)` or
- `(instrument_id, stat_type, ts_ref, ts_event)` if sequence is unreliable

Start with:
- `(instrument_id, stat_type, ts_ref, sequence)`

and confirm in practice with a small sample.

## 7) Implement orchestrator (`orchestrator.py`)
Follow the product-level dataset orchestrator pattern:

Modes:
- `--bootstrap`: ingest all windows in range regardless of existing coverage
- `--update`: ingest only windows not complete or where final settlement may have updated

V1 update logic (minimal):
- always re-check the most recent N days (e.g., last 5 trading days) to capture preliminary→final settlement updates
- everything older treated as stable unless explicitly missing

Completeness definition (V1):
- “complete” for a trading_date means: at least one `stat_type=3` exists for each instrument in scope
- “final complete” means: settlement exists with flags indicating final (if we decode flags in V1; else postpone to a later session and track prelim vs final in inspect)

For session 15, we can:
- implement completeness as “settlement present”
- store flags for later “final” refinement

## 8) Implement inspect and proof scripts (`inspect.py` + `scripts/`)
Add:
- `scripts/marketdata/96_smoke_persist_statistics_1d.py` (or next free number)
  - reset DB option
  - ingest a known window for a known scope (e.g. ES futures around Jan 2022)
  - print:
    - coverage snapshot
    - count of rows by stat_type
    - sample of settlement rows (stat_type=3)
    - count of distinct trading dates
    - count of distinct instrument_ids
    - any duplicates detected by dedupe key

Add:
- an inspect function to summarise:
  - per trading_date: count settlements, OI, volume
  - per stat_type: row counts
  - per symbol/instrument_id: coverage

## 9) Specific tests / invariants (V1)
### Invariants
- all stored rows have `rtype == 24`
- `publisher_id` consistent with GLBX.MDP3 for the scope
- `trading_date` monotonic within windows (sanity)
- `price_f == price * 1e-9` where price is not sentinel
- `stat_type` limited to known set (for GLBX.MDP3 many types exist; record unknowns but flag)

### Completeness checks (V1)
- settlement exists for each trading date within the requested window for the primary instruments
- if settlement missing, window marked incomplete and retained in attempts store

## 10) Session execution steps (tomorrow morning)
1. Create dataset directory + boilerplate modules.
2. Implement `expected.py` window generation (copy OHLCV approach).
3. Implement raw ingest path: DataIO → DataFrame → Parquet.
4. Implement attempts store writes and minimal coverage snapshot.
5. Add proof script and run a short window (e.g. 10 trading days) for ES.
6. Validate:
   - settlement rows exist (`stat_type=3`)
   - `ts_ref` → `trading_date` mapping looks sensible
   - no duplicate explosion
7. Expand to a larger window (e.g. 3 months) and confirm performance and storage.
8. Commit with a clean branch and message.

## Open Questions (explicitly deferred unless trivial)
1. Decode `stat_flags` for final vs preliminary settlement.
2. Venue timezone / trading date mapping nuance beyond `date(ts_ref in UTC)`.
3. A derived `market_state_1d` dataset that collapses statistics into a single row per instrument per date.
4. Cross-product close-group metadata and lead/lag scan reports (risk layer).

## Suggested Git hygiene
Branch name:
- `feature/statistics-1d-ingestion`

Commit message (first commit):
- `marketdata: add statistics_1d dataset ingestion skeleton`

Commit message (proof + orchestration):
- `marketdata: persist databento statistics for settlement (GLBX.MDP3)`

## Session “Definition of Done”
- Running the proof script produces stored Parquet rows for statistics for a chosen scope and window.
- Coverage snapshot shows correct min/max trading dates and row counts.
- Inspect output confirms presence of settlement (`stat_type=3`) rows.
- Attempts store records success/failure with request hashes and row counts.
- Re-running the same window does not duplicate rows (or duplicates are deduped deterministically).

