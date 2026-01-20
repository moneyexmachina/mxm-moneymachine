# MXM V1 — Session 10 Log  
## Instrument-ID–Based OHLCV Ingestion (Databento)

**Date:** 2026-01-20  
**Phase:** Phase 2 — Market Data Completion  
**Branch:** feat/databento-ohlcv-by-instrument-id  
**Status:** **Closed**

## 1. Session Objective

Session 10 moved MXM market-data ingestion from *symbol-based addressing* to **vendor-native instrument identity**.

The non-negotiable objective was:

> Enable **instrument_id–based OHLCV-1D ingestion** from Databento, with parquet persistence keyed by `(dataset, publisher_id, instrument_id)`.

This session establishes the first correct end-to-end ingestion path from MXM refdata to persisted market data.

## 2. What Was Built

### 2.1 Databento Instrument Resolver (Authoritative)

A new resolver API was introduced:

- `resolve_databento_instrument(backend, contract, *, as_of_dt=None) -> DatabentoInstrumentIdentity`

Where `DatabentoInstrumentIdentity` includes:

- `dataset: str`
- `publisher_id: int`
- `instrument_id: int`
- `raw_symbol: str`

Resolution semantics:

- Queries only `instrument_definition_mappings`
- Keys by `(product_id, contract_year, contract_month)` derived from `FuturesContract.period_id`
- Deterministic strictness:
  - exactly one row → return identity
  - zero rows → `InstrumentNotMappedError`
  - multiple rows → `InstrumentAmbiguityError`

This function is now the only supported identity-resolution boundary for Databento OHLCV ingestion in MXM V1.

### 2.2 Databento OHLCV-1D Pull by Instrument ID

OHLCV-1D ingestion was migrated to use Databento addressing by instrument identity:

- `stype_in="instrument_id"`
- `symbols=<instrument_id>`

A convenience wrapper was added:

- `pull_ohlcv_1d_by_instrument_id(...)`

DataIO request hashing remains stable and idempotent because the canonical request params now include:

- `dataset`, `schema="ohlcv-1d"`, `symbols=<instrument_id>`, `stype_in="instrument_id"`, `start`, `end`

### 2.3 Normalization Uses Mapping-Provided raw_symbol

Normalization is performed via:

- `normalize_ohlcv_1d(df_raw, dataset=..., raw_symbol=...)`

`raw_symbol` is injected from the mapping table (via the resolver), avoiding reliance on Databento payload symbol fields.

### 2.4 Instrument-Identity-Keyed Parquet Persistence

Bars are persisted under the canonical identity-keyed store:

```
~/.mxm/marketdata/
  databento/
    ohlcv-1d/
      by_instrument/
        dataset=<DATASET>/
          publisher_id=<PUBLISHER_ID>/
            instrument_id=<INSTRUMENT_ID>/
              bars.parquet
```

Writes use the existing canonical store API:

- `write_daily_bars(...)` (merge/dedup on `ts_event`)
- `read_daily_bars(...)`

SQLite remains authoritative for metadata; parquet remains authoritative for bar data.

## 3. Proof Surface

### 3.1 Proof 97 (Slice): Contract → Instrument Identity

Script:

- `scripts/marketdata/97_contract_resolution.py`

Demonstrated:

1. Selecting a concrete `FuturesContract` from refdata  
2. Resolving to a unique Databento identity via `instrument_definition_mappings`

Example output:

- `resolved: dataset=GLBX.MDP3 publisher_id=1 instrument_id=6640 raw_symbol=ESM0`

### 3.2 Proof 98 (Closure): Instrument-ID OHLCV Pull → Normalize → Persist → Idempotent Rerun

Script:

- `scripts/marketdata/98_proof_ohlcv_by_instrument_id.py`

Demonstrated end-to-end:

1. `FuturesContract` selected from refdata  
2. Identity resolved via mapping table (`instrument_id` is now the addressing primitive)  
3. OHLCV-1D bars fetched from Databento using `stype_in="instrument_id"`  
4. Bars normalized using mapping-provided `raw_symbol`  
5. Bars persisted to the instrument-keyed parquet path  
6. In-process rerun proved:
   - DataIO cache hit (no Databento call on second run)
   - store merge idempotency (row-count stable)

Key evidence:

- Run 1 contained a `[DATABENTO CALL] ... stype_in=instrument_id ...`
- Run 2 had no Databento call and reused the same DataIO response artifact
- Parquet store path matched the canonical identity layout
- Stored row count remained stable across rerun

## 4. Outcomes and Invariants

Session 10 establishes the first correct ingestion atom for MXM V1:

```
FuturesContract
  → DatabentoInstrumentIdentity (dataset, publisher_id, instrument_id, raw_symbol)
    → OHLCV pull by instrument_id
      → normalize (raw_symbol injected)
        → parquet persistence (identity-keyed, merge-idempotent)
```

Invariants reinforced:

- Mapping table is the single source of truth for identity resolution
- Symbols are no longer an addressing primitive for ingestion
- SQLite is authoritative for identity/metadata
- Parquet is authoritative for OHLCV bars

## 5. Next Steps

### 5.1 Orchestration Layer (Backfill + Daily Update)

Build orchestration over the Session 10 ingestion atom:

- Backfill across products, maturities, and date windows
- Apply cost caps and audit logging
- Implement incremental daily update:
  - infer last stored `ts_event`
  - pull forward only missing days
  - merge-write idempotently

### 5.2 Dataset Consumer API (Read-Side)

Implement a clean read-side interface for downstream use and verification:

- `get_daily_bars(dataset, publisher_id, instrument_id, start, end, ...)`
- optional convenience entrypoints:
  - by `FuturesContract` (resolve then read)
  - by `product_id` + maturity
- ensure predictable sorting, schema validation, and slicing

This is required to confirm data quality and to support the next layers (signals, strategies, risk).

### 5.3 Minimal Viewing / Plotting Layer

Add a simple viewing utility to inspect stored bars quickly.

Initial MVP options:

- A script that reads `bars.parquet` and plots:
  - close series
  - candlestick (optional)
  - volume (optional)

Databento reference example uses `mplfinance` candlesticks; MXM should provide an equivalent viewer over the canonical stored dataset (not over the raw fetch output), so that operators can validate what is persisted.

A minimal deliverable would be:

- `scripts/marketdata/plot_ohlcv_1d.py --dataset ... --publisher-id ... --instrument-id ...`

Later iterations can standardize plotting style and integrate into reporting.

## 6. Session Close

Session 10 is closed on the basis of Proof 98:

- Instrument-id addressing is implemented and proven end-to-end
- DataIO caching and parquet persistence are proven on rerun
- The resulting ingestion atom is now ready to be composed into backfills and daily updates
