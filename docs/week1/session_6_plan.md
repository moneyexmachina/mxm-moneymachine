# MXM V1 — Session 6 Plan  
**Topic:** Futures Contract Enumeration and Databento Mapping  
**Planned Time:** 09:00–12:30  
**Date:** 2026-01-15

## Session Objective

Session 6 exists to establish a **clean, stable identity boundary** between:

- **MXM internal truth** (`mxm-refdata`), and
- **Databento vendor requests** (`mxm.v1.marketdata.databento`).

Specifically, by the end of this session:

> **MXM can enumerate all futures contracts it intends to trade and map each contract deterministically to a Databento request identity.**

This makes historical backfills and daily updates *inevitable and boring*, rather than bespoke.

## Position in Week 1

Week 1 goal:

> **The system knows what it trades and has reliable historical price data.**

Progress so far:

- Session 4: data correctness (canonical schema, store, idempotent writes)
- Session 5: cost correctness (request-keyed caching via DataIO)

Session 6 addresses the remaining foundational gap:

- **instrument identity and coverage**

Without this, backfill and update scripts cannot be written safely.

## Scope (Strict)

### Included

- Extend `mxm-refdata` queries to enumerate:
  - all futures contracts for a product (historical + active),
  - currently active contracts,
  - full futures chains ordered by expiry.
- Define and implement a **Databento mapping layer** that:
  - consumes `FuturesContract` objects,
  - produces Databento request parameters deterministically.
- Demonstrate the mapping with a small proof (enumeration + printed requests).

### Explicitly Excluded

- Historical data backfills
- Daily update orchestration
- Market data storage changes
- DataIO changes
- Plotting, analytics, or synthetic asset construction
- Adding large numbers of new products (mechanical work deferred)

Any work outside the included scope must be logged as deferred.

## Architectural Boundary (Non-Negotiable)

### `mxm-refdata` owns:
- Products, contracts, calendars, and lifecycle semantics
- Queries such as:
  - “all contracts for this product”
  - “currently active contracts”
  - “full futures chain”
- Vendor-agnostic identifiers and attributes:
  - exchange
  - root symbol
  - expiry year / month
  - contract code (internal)

### `mxm.v1.marketdata.databento` owns:
- How MXM contracts are translated into Databento requests
- Dataset selection and schema (`ohlcv-1d`)
- Symbology modes and encoding quirks
- Construction of Databento request parameters

**Databento-specific logic must not leak into `mxm-refdata`.**

## Concrete Tasks

### 1) Refdata Query Extensions

Extend `mxm-refdata` so it can answer the following questions cleanly and explicitly:

- Given a `FuturesProduct`:
  - return **all known contracts** (historical + future),
  - return **currently active contracts** (not just “delivering”),
  - return the **full futures chain**, ordered by expiry.

Deliverable:
- New or extended refdata query functions with clear semantics and docstrings.
- No vendor assumptions.

### 2) Databento Mapping Function

Implement a single, explicit mapping function in:

```
mxm.v1.marketdata.databento
```

Conceptually:

```
def databento_request_for_contract(contract: FuturesContract) -> DatabentoRequest
```

Responsibilities:
- take a `FuturesContract` as input,
- construct Databento request parameters:
  - dataset
  - symbol or identifier
  - symbology mode
- normalise all fields so the resulting request identity is stable.

This function becomes the **only supported path** from contracts to Databento.

Deliverable:
- Mapping function + documentation of the mapping choice.
- No data ingestion yet.

### 3) Minimal Proof (Enumeration + Mapping)

Create a lightweight proof (script or REPL-driven):

- Select one or two futures products.
- Enumerate:
  - full contract list,
  - active contracts,
  - ordered chain.
- For each contract:
  - produce and print the Databento request parameters.

Success criteria:
- Enumeration is complete and ordered.
- Mapping is deterministic and reproducible.
- No Databento calls are made.

## Success Criteria (Must Be Provable)

Session 6 is successful if and only if:

- MXM can enumerate all contracts for a product programmatically.
- Each `FuturesContract` maps to exactly one Databento request identity.
- The mapping logic is isolated to the Databento module.
- No ingestion or storage logic was required to achieve this.

## Deliverables

By the end of Session 6:

- Extended refdata query API for futures contracts
- Databento mapping function implemented and documented
- A small proof script demonstrating enumeration and mapping
- `session_6_log.md` summarising outcomes and deferred items

## Session End Condition

The session ends when:

> Given a futures product, MXM can list the contracts it trades and show exactly how each one would be queried from Databento.

At that point, historical backfills and daily update scripts can be written mechanically in subsequent sessions.
