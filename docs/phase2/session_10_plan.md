# MXM V1 — Session 10 Plan
# Instrument-ID–Based OHLCV Ingestion (Databento)

**Status:** Planned  
**Pre-requisites:** Session 9 complete and merged  
**Phase:** Phase 2 — Market Data Completion  
**Proof ID:** 97

## 1. Objective (Single, Non-Negotiable)

Enable **instrument_id-based OHLCV-1D ingestion** from Databento, using the
Session-9 identity mapping layer as the sole resolution mechanism.

Concretely, this session delivers a correct, deterministic pipeline:

```
MXM FuturesContract
    → Databento (publisher_id, instrument_id)
        → OHLCV-1D bars
            → Parquet persistence keyed by instrument identity
```

No symbol-based addressing remains in the ingestion path.

## 2. Exit Criteria (All Must Be Met)

Session 10 is complete when:

1. A `FuturesContract` can be resolved deterministically to
   `(publisher_id, instrument_id)` via the mapping table.
2. Databento OHLCV-1D data can be fetched **by instrument_id** (not raw_symbol).
3. Daily bars are persisted to parquet using **instrument-identity keys**:
   ```
   marketdata/
     databento/
       ohlcv-1d/
         by_instrument/
           dataset=GLBX.MDP3/
             publisher_id=1/
               instrument_id=49278/
                 bars.parquet
   ```
4. The ingestion is **idempotent**:
   - repeated runs do not duplicate or corrupt data
5. A proof script demonstrates the full path end-to-end.

## 3. Scope (What We WILL Build)

### A) Instrument-ID Resolver API

Implement a resolver function, e.g.:

```
resolve_databento_instrument(
    contract: FuturesContract,
    *,
    as_of_dt: datetime | None = None
) -> (publisher_id, instrument_id)
```

Semantics:
- Uses `instrument_definition_mappings`
- Applies validity filtering:
  - `valid_from <= as_of_dt`
  - and (`valid_to IS NULL` or `as_of_dt <= valid_to`)
- Deterministic behaviour:
  - exactly one match → return
  - zero matches → explicit error
  - multiple matches → explicit ambiguity error

This function is the **only supported identity resolution path**.

### B) Databento OHLCV-1D Fetch by Instrument ID

Extend the Databento fetcher to:
- request daily bars using `(publisher_id, instrument_id)`
- preserve existing DataIO semantics (request identity, caching, cost awareness)
- avoid any reliance on raw_symbol addressing

### C) Instrument-Identity-Keyed Persistence

Update persistence logic so that:
- bars are written under `by_instrument/`
- identity keys are `(dataset, publisher_id, instrument_id)`
- writes are atomic (tmp → final)
- minimal provenance metadata is retained (ingested_at, request identity)

## 4. Explicit Non-Goals (Out of Scope)

Session 10 explicitly does **not** include:

- Backfill orchestration across all products
- Daily update scheduling / runners
- Roll logic or continuous contract chains
- Multi-vendor ingestion
- Signal, strategy, or portfolio logic
- UI or reporting layers

These belong to Sessions 11+.

## 5. Proof Surface (Proof 97)

A single proof script must demonstrate:

1. Selection of a known `FuturesContract` from refdata
2. Resolution to `(publisher_id, instrument_id)`
3. Successful OHLCV-1D fetch via Databento
4. Persistence to the expected parquet path
5. Idempotent re-run behaviour

Example invocation:

```
poetry run python scripts/marketdata/97_proof_fetch_bars_by_instrument_id.py
```

Proof output should print:
- resolved instrument identity
- request scope (dataset, date range)
- bar count and date range returned
- final parquet path
- second-run confirmation (no duplication)

## 6. Architectural Constraints (Must Hold)

- Mapping table remains the single source of truth for identity resolution
- No vendor semantics leak into strategy code
- Persistence is keyed by vendor instrument identity, not symbols
- SQLite remains the authoritative metadata store
- Parquet remains the authoritative bar data store

## 7. Expected Deliverables

By the end of Session 10, the following must exist:

- Instrument-ID resolver function (production code)
- Updated Databento OHLCV-1D fetch path
- Instrument-identity-keyed parquet persistence
- Proof 97 script
- Session 10 log documenting results and deviations

## 8. Next Sessions

- **Session 11:** Backfill orchestration (multi-contract, historical)
- **Session 12:** Incremental daily updates
- **Session 13+:** Roll-aware contract chains and strategy-level consumption

**Session 10 Mandate:**  
Address market data by *what the vendor actually trades*, not by symbols.
Nothing more, nothing less.
