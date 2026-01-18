# MXM V1 — Session 8 Plan  
**Title:** Instrument Definition Persistence & Marketdata Storage Layer  
**Week:** 1  
**Session goal:** Design and implement the domain persistence layer for Databento instrument definitions, enabling a clean transition of OHLCV ingestion from `raw_symbol` to `instrument_id`.

## 1. Objective

The objective of Session 8 is to make **instrument definitions a first-class persisted dataset** in MXM V1.

Specifically, we will:

- Introduce a **SQLite-backed event log** for Databento instrument definitions, ingested from the time-series API.
- Materialise a **current instrument definition view** suitable for operational use.
- Establish **incremental ingestion semantics** using Databento’s point-in-time guarantees and `ts_recv` ordering.
- Lay the storage foundation required to:
  - build a robust `FuturesContract → Databento instrument_id` mapping in a later session, and
  - switch OHLCV ingestion from `stype_in="raw_symbol"` to `stype_in="instrument_id"`.

This session focuses on **persistence and correctness**, not on mapping logic or calendar-level completeness checks.

## 2. Context and Prior State

By the end of Session 7, the following are true:

- We can successfully query Databento **instrument definition data** via the time-series API using `mxm-dataio`, with request-keyed caching and cost gating.
- Script `94_smoke_ingest_instrument_definitions.py` demonstrates end-to-end retrieval of definition data for a product root over a date window.
- Instrument definitions arrive as a **point-in-time time series**, with:
  - `ts_event` (matching engine timestamp), and
  - `ts_recv` (Databento capture timestamp, currently exposed as the DataFrame index).
- Existing vendor mapping code under `marketdata/mapping/vendors/databento/` is a non-operational remnant and will be rebuilt later, after instrument definitions are properly persisted.
- OHLCV 1D data is already persisted in **Parquet** via a domain store, but still addressed via `raw_symbol`.

Session 8 introduces **SQLite** as the persistence backend for *metadata and event-like datasets*, complementing the existing Parquet fact store.

## 3. Scope

### In scope

- SQLite backend adapter for marketdata persistence.
- Databento instrument definition **event log** (append-only, idempotent).
- Ingestion **watermarking** using `ts_recv`.
- Materialised **current instrument definition view**.
- One or more smoke / proof scripts demonstrating persistence, idempotency, and queryability.

### Explicitly out of scope (deferred)

- FuturesContract → Databento instrument mapping logic.
- As-of reconstruction APIs beyond “current view”.
- Calendar-aware completeness checks.
- OHLCV ingestion refactor itself (will be enabled, not executed, by this session).

## 4. Design Decisions (Locked for Session 8)

1. **Two-layer persistence model**
   - One backend adapter per technology (SQLite, Parquet).
   - One domain store per dataset.

2. **Instrument definitions are stored as an event log**, even though they arrive via a time-series API.
   - Rationale: idempotency, replayability, watermarking, and derived views.

3. **SQLite is the authoritative store** for:
   - Databento instrument definition events.
   - Derived “current” instrument definition state.
   - Ingestion watermarks.

4. **`ts_recv` is the primary ordering and watermark field**
   - `ts_event` is retained for semantic correctness and joins.
   - Event ordering key is effectively `(ts_recv, ts_event, publisher_id, instrument_id)`.

5. **Idempotency via deterministic event UID**
   - Each ingested record produces a stable `event_uid` (hash of canonicalised payload including timestamps).
   - Database enforces uniqueness on `event_uid`.

## 5. Storage Model

### 5.1 SQLite backend

A new SQLite backend adapter will live under:

```
src/mxm/v1/marketdata/stores/sqlite/
```

Responsibilities:

- Connection management.
- Migration execution.
- Transaction handling.
- Basic helpers (execute, executemany, fetch).

A single SQLite database file will be owned by the **marketdata domain**.

### 5.2 Tables

#### A) Instrument definition event log (authoritative)

**Table:** `databento_instrument_def_events`

Core columns:

- `event_uid TEXT PRIMARY KEY`
- `publisher_id INTEGER NOT NULL`
- `instrument_id INTEGER NOT NULL`
- `ts_event INTEGER NOT NULL`
- `ts_recv INTEGER NOT NULL`
- `security_update_action TEXT NOT NULL`
- `raw_symbol TEXT`
- `payload_json TEXT NOT NULL`
- `ingested_at INTEGER NOT NULL`

Indexes:

- `(publisher_id, ts_recv)`
- `(instrument_id, ts_recv)`
- `(publisher_id, instrument_id, ts_event)`

#### B) Ingestion watermarks

**Table:** `ingestion_watermarks`

- `feed TEXT PRIMARY KEY`
- `ts_recv_last INTEGER NOT NULL`
- `updated_at INTEGER NOT NULL`

This table supports incremental ingestion and future intraday extension.

#### C) Current instrument definition view (derived)

**Table:** `databento_instrument_def_current`

- `publisher_id INTEGER NOT NULL`
- `instrument_id INTEGER NOT NULL`
- `ts_event_last INTEGER NOT NULL`
- `ts_recv_last INTEGER NOT NULL`
- `is_deleted INTEGER NOT NULL`
- Selected query-relevant fields (e.g. `raw_symbol`, `asset`, `exchange`, `instrument_class`, `security_type`, `maturity_year`, `maturity_month`, `expiration`, `activation`)
- Optionally `payload_json TEXT`

Primary key:

- `(publisher_id, instrument_id)`

Update rule:

- Upsert on newer `(ts_recv, ts_event)` only.

## 6. Domain Store

A new domain store will be introduced, conceptually:

```
marketdata/datasets/instrument_definitions/
```

Responsibilities:

- Accept DataFrame-like batches of Databento instrument definitions.
- Normalise input (ensure `ts_recv` column, canonical payload).
- Append events idempotently to SQLite.
- Maintain the current definition view transactionally.
- Read APIs:
  - `get_current(publisher_id, instrument_id)`
  - `list_current(publisher_id, filters=...)`

This store depends on:
- `vendors/databento/timeseries.py` for retrieval,
- the SQLite backend for persistence.

## 7. Implementation Steps

1. **SQLite backend adapter**
   - Create backend module.
   - Add minimal migration runner.
   - Add initial migration creating required tables.

2. **Event UID & normalisation**
   - Explicitly extract `ts_recv` from DataFrame index.
   - Canonicalise payload and compute deterministic `event_uid`.

3. **Instrument definition store**
   - Implement `append_events(df, feed_id)`:
     - load watermark
     - filter already-seen records
     - insert new events
     - update current view
     - advance watermark
   - Ensure full transactional safety.

4. **Smoke / proof script**
   - New script under `scripts/marketdata/`:
     - ingest a known window
     - re-run ingestion to prove idempotency
     - query and print current instrument counts and samples

5. **Documentation update**
   - Add a short note to `minimal_marketdata_system.md` describing the SQLite event store and its role.

## 8. Proof Criteria (Exit Conditions)

Session 8 is complete when:

- Instrument definition data can be ingested into SQLite from Databento.
- Re-running the same ingestion does **not** duplicate events.
- `databento_instrument_def_current` returns stable, sensible results.
- A clear programmatic path exists to:
  - build FuturesContract → instrument mappings, and
  - switch OHLCV ingestion to `stype_in="instrument_id"`.

## 9. Next Session Preview (Session 9)

Session 9 will:

- Build the FuturesContract → Databento instrument mapping on top of the persisted definitions.
- Validate mapping quality and edge cases (rolls, deletions, re-listings).
- Switch OHLCV ingestion to instrument-ID addressing and validate continuity.

