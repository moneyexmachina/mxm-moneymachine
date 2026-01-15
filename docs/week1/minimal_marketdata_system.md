# Minimal Market Data System — MXM V1

## Purpose and Scope

This document describes the **minimal market data system** implemented for MXM V1.

Its purpose is to:
- ingest daily market data from an external vendor (Databento),
- materialise that data into an opinionated, canonical internal form,
- serve it deterministically to downstream applications,
- and do so in a way that is cost-aware, reproducible, and evolvable.

This is **not** a general market data platform.  
It is the smallest system that can support MXM V1 reliably.

Scope for V1:
- daily bars only (`ohlcv-1d`)
- Databento as the sole data vendor
- explicit futures contracts (no rolls, no spreads, no intraday data)

## Architectural Overview

The system is explicitly split into **two layers**, each with a different responsibility and notion of identity:

1. **Request / Response Layer (DataIO)** — immutable
2. **Market Data Store (this system)** — materialised, canonical

This separation is intentional and fundamental.

## Layer 1: Request / Response (DataIO)

**Responsibility:**  
Record *every* interaction with an external data provider.

**Identity:**  
A request is identified by its **query parameters**, e.g.:

- dataset
- schema
- symbol or instrument identifier
- start date
- end date
- query mode / symbology

**Properties:**
- append-only
- immutable once written
- may contain overlapping, partial, empty, or revised responses
- does not attempt to decide which data is “good” or “final”

**Purpose:**
- avoid paying twice for the same query
- enable replay, audit, and debugging
- preserve exact vendor replies

The DataIO layer is **content-blind** and **domain-agnostic**.

## Layer 2: Market Data Store (this document)

**Responsibility:**  
Construct and maintain a **single canonical time series** per instrument for downstream use.

**Identity:**  
A stored dataset is identified by **instrument identity**, not by query parameters.

Canonical store key:
- `dataset`
- `schema` (fixed as `ohlcv-1d` in V1)
- `publisher_id`
- `instrument_id`

This identity corresponds to *one financial instrument’s daily bar history*.

**Purpose:**
- collate data from many overlapping vendor queries
- present a clean, stable “best known” view of history
- decouple downstream logic from vendor APIs and costs

## Canonical Daily Bar Schema (`ohlcv-1d`)

The market data store enforces a **frozen canonical schema** for daily bars.

### Columns and Meaning

| Column | Type | Description |
|------|------|-------------|
| `ts_event` | `datetime64[ns, UTC]` | Canonical bar timestamp (vendor-defined label) |
| `open` | numeric | Open price |
| `high` | numeric | High price |
| `low` | numeric | Low price |
| `close` | numeric | Close price |
| `volume` | numeric | Volume (dtype not over-constrained in V1) |
| `dataset` | string | Vendor dataset (e.g. `GLBX.MDP3`) |
| `schema` | string | Always `ohlcv-1d` |
| `publisher_id` | int32 | Vendor publisher identifier |
| `instrument_id` | int64 | Stable vendor instrument identity |
| `raw_symbol` | string | Vendor query symbol used |

### Enforcement

The schema is enforced operationally via:
- a coercion step (`coerce_ohlcv_1d`)
- a validation step (`validate_ohlcv_1d`)

Validation rules (V1):
- all required columns must be present
- `ts_event` must be timezone-aware UTC
- identity fields must be non-null
- price and volume fields must be numeric

Schema drift is treated as a **hard error**.

## Storage Model

### Storage Unit

One Parquet file represents **one instrument’s complete known daily bar history**.

There is exactly one file per:

```
(dataset, schema, publisher_id, instrument_id)
```

### Filesystem Layout

Under the MXM state root (`~/.mxm/`):

```
~/.mxm/
  marketdata/
    databento/
      ohlcv-1d/
        by_instrument/
          dataset=GLBX.MDP3/
            publisher_id=1/
              instrument_id=42140878/
                bars.parquet
```

This layout encodes the identity directly into the path and avoids ambiguity.

## Write Semantics (Idempotent Merge-Write)

The market data store uses an **idempotent merge-write** model.

### Primary Key
- `ts_event` is the primary key (one bar per day label)

### Merge Algorithm
When writing new data for an existing instrument:

1. Load existing bars (if any)
2. Concatenate with newly ingested bars
3. Deduplicate on `ts_event`
4. Resolve overlaps by **keeping the newer write**
5. Sort by `ts_event`
6. Write the full dataset atomically

### Meaning of “Idempotent”

Idempotency here means:

> Re-running the same ingestion (or overlapping ingestions) converges to a stable dataset state.

It does **not** mean:
- no file rewrite occurs
- the filesystem timestamp is unchanged

It means:
- no duplicate rows accumulate
- overlapping data is resolved deterministically
- the stored dataset represents the current “best known” history

## Relationship to Vendor Queries

Vendor queries are **range-based**:

```
(symbol or instrument_id, start, end)
```

These ranges are **not identity**; they are just a way to retrieve data.

The market data store:
- ignores query boundaries after ingestion
- collates all retrieved bars into a single canonical series per instrument
- serves slices of that series on demand via local reads

This allows:
- gap filling
- conservative overlapping updates
- vendor corrections to overwrite earlier values

## Provenance Model (V1)

The Parquet store is a **materialised current-state view**.

Provenance is handled separately:
- at the pull / ingestion level (e.g. pull ledgers)
- not at the row level

This keeps the served dataset clean and simple, while still allowing audit and replay when required.

## What This System Intentionally Does Not Do (V1)

- multi-vendor reconciliation
- continuous contracts or roll logic
- spread or synthetic instrument construction
- intraday data handling
- session or holiday semantics enforcement
- FX conversion

These are explicitly deferred.

## Summary

The MXM V1 market data system:

- separates request logging from canonical data materialisation
- enforces a clear, opinionated daily bar schema
- stores exactly one unified history per instrument
- supports safe re-ingestion and overlap handling
- decouples downstream logic from vendor APIs and costs

This provides a stable foundation for MXM V1 and a clear extraction path to a future `mxm-marketdata` package.
