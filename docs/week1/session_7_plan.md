# MXM V1 — Session 7 Plan  
**Topic:** Databento Instrument Definitions as a First-Class Metadata Dataset  
**Status:** Planned  
**Prerequisite:** Session 6 closed (refdata complete; mapping deferred by design)

## 1. Session Objective

Design and implement a **durable, cost-gated Databento metadata layer** that captures **instrument definition events** and makes them safely reusable for:

- contract → instrument mapping,
- lifecycle validation,
- future vendor abstractions.

At the end of this session, Databento instrument definitions should be:

- explicitly modeled as a dataset,
- locally cached,
- incrementally updatable,
- and queryable without repeated vendor calls.

## 2. Problem Statement (Recap)

Databento instrument definitions:

- are delivered via `schema="definition"` on the **timeseries API**,
- are **event-based** (add / modify / delete),
- require historical replay to reconstruct state,
- are **non-free** at scale (≈ USD 0.06 per product for full history),
- cannot be treated as ephemeral lookups.

Therefore:

> Instrument definitions are **not mapping glue** — they are **vendor reference data**.

## 3. Non-Goals (Strict)

This session will **not**:

- join MXM contracts to Databento instruments,
- create or persist mapping rows,
- touch price data ingestion,
- integrate with `mxm-dataio` beyond local scripts,
- attempt to “finish Session 6 retroactively”.

The only deliverable is a **clean metadata substrate**.

## 4. Architectural Decisions (Pre-Committed)

### 4.1 Storage

- One **Databento metadata SQLite store**, separate from:
  - daily bars,
  - Parquet data,
  - mapping tables.
- This store may contain multiple logical datasets over time:
  - `instrument_definitions` (Session 7),
  - mappings (later),
  - possibly other vendor metadata.

### 4.2 Data model

Instrument definition rows must preserve:

- `instrument_id` (primary stable key),
- `raw_symbol`,
- lifecycle timestamps:
  - `activation`,
  - `expiration`,
- maturity fields:
  - `maturity_year`,
  - `maturity_month`,
  - `maturity_day`,
- `instrument_class` (future vs spread),
- minimal raw metadata payload (JSON).

No premature normalization.

## 5. Planned Work Items

### 5.1 Define the dataset

- Name: **Databento Instrument Definitions**
- Source:
  ```python
  client.timeseries.get_range(
      dataset=...,
      schema="definition",
      symbols=parent,
      start=...,
      end=...
  )
  ```
- Semantics:
  - append-only event stream,
  - replayable to reconstruct state as-of any date.

### 5.2 SQLite schema design

Design a table (or tables) to support:

- idempotent inserts by `(instrument_id, ts_event)`,
- efficient lookup by:
  - `instrument_id`,
  - `raw_symbol`,
  - `(maturity_year, maturity_month)`,
- detection of last ingested event timestamp per product.

Deliverable:
- explicit schema SQL,
- no ORM,
- inspectable via `sqlite3`.

### 5.3 Bootstrap script

Create a script:

```
scripts/databento/30_bootstrap_instrument_definitions.py
```

Responsibilities:

- accept `product_id`,
- resolve Databento parent (existing mapping),
- estimate full-history cost **before fetching**,
- abort if above user-supplied threshold,
- fetch full definition history,
- persist events into SQLite,
- print summary:
  - rows fetched,
  - futures vs spreads,
  - earliest and latest timestamps.

This script is **run once per product**.

### 5.4 Incremental update script

Create a script:

```
scripts/databento/31_update_instrument_definitions.py
```

Responsibilities:

- read last ingested timestamp per product,
- query only new definition events,
- cost-gate the request,
- append to SQLite,
- be safe to run daily or weekly.

### 5.5 Validation queries

Provide minimal inspection utilities:

- count instruments by class,
- list futures only,
- show maturity coverage,
- verify monotonic event ingestion.

These can be inline in scripts; no CLI polish required.

## 6. Success Criteria

Session 7 is complete when:

- Databento instrument definitions are stored locally.
- No mapping logic depends on live Databento calls.
- Re-running scripts does **not** re-query historical data.
- Cost exposure is explicit, bounded, and logged.
- The metadata store can be trusted as a vendor-side reference source.

## 7. Explicit Handoff to Session 8

Session 8 may then:

- join MXM `FuturesContract(period_id, year, month)`
  to Databento `(instrument_id, maturity_year, maturity_month)`,
- persist mapping rows into the vendor mapping table,
- complete the original Session 6 objective on top of solid ground.

## 8. Session Framing

This session is deliberately **infrastructure-heavy** and **logic-light**.

The goal is not speed, but **removing ambiguity permanently**.

Once this layer exists:
- mapping becomes trivial,
- symbol conventions become irrelevant,
- and vendor churn is survivable.

