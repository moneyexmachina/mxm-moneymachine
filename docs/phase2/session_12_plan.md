# session_12_plan.md
# MXM V1 — Session 12 Plan
# Topic: OHLCV-1D Accounting, Completeness Semantics, and Retry Policy
# Status: PLANNED
# Precondition: Session 11 closed (dataset orchestrators operational)

## 1. Purpose of Session 12

Session 12 formalises *auditable completeness* for the `ohlcv_1d` dataset.

The goal is **not** to redesign ingestion, nor to generalise prematurely across datasets.  
The goal is to make explicit, queryable, and testable:

- what OHLCV-1D data we *expected* from the vendor,
- what we *asked for*,
- what the vendor *returned*,
- what we have *materialised*,
- and what *status* we infer for each contract.

This session introduces a minimal accounting layer that allows the orchestrator to decide, deterministically and repeatably, whether a contract:
- should be requested again,
- is complete enough given vendor limits,
- or should be skipped permanently.

This is a prerequisite for any product-level meta-orchestrator.

## 2. Problem statement (current gap)

At the end of Session 11:

- Ingestion works.
- Vendor availability is respected.
- Parquet stores converge toward an eventually complete materialisation.

However:

- “incomplete” is an overloaded state.
- The orchestrator cannot distinguish:
  - retryable gaps,
  - vendor-limited completeness,
  - permanently unavailable history,
  - transient partial responses.
- Update mode cannot make principled decisions.
- There is no first-class, queryable “status surface” for downstream consumers.

Without this, higher-level orchestration will either:
- over-request data, or
- silently stall with ambiguous results.

## 3. Design principles for this session

**3.1 Minimalism (v1-appropriate)**  
We add only what is required to:
- reason about completeness,
- support retry policy,
- and explain outcomes.

No generic framework, no cross-dataset abstraction yet.

**3.2 Separation of truth surfaces**  
We explicitly distinguish three truths:
1. Vendor statements (what *could* exist)
2. Request / response history (what we *asked for* and *received*)
3. Materialised state (what we *have*)

**3.3 Deterministic derivation**  
Status is *derived*, not manually set.  
Given the same inputs, we must reach the same classification.

## 4. Target capabilities (what must be possible after Session 12)

For any `(product_id, contract_id)` in `ohlcv_1d`, the system must be able to answer:

1. What date range did we expect, after clamping to vendor availability?
2. What date ranges have we requested so far?
3. What data ranges have been observed in responses?
4. What coverage exists in parquet?
5. What is the inferred completeness status?
6. Should this contract be retried in the next run?

These answers must be available:
- to the orchestrator,
- and to a client-facing inspection API.

## 5. Proposed state model for OHLCV-1D (v1)

### 5.1 Expected window (derived, not stored)
For each contract:
- Start: `max(first_day_of_interest, vendor_dataset_start)`
- End: `min(last_trading_day + 1d, vendor_dataset_end)`

This is already computed; Session 12 makes it explicit as a named concept.

### 5.2 Observed materialisation (already exists)
From `OHLCV1DStore.scan_coverage`:
- `stored_min_ts`
- `stored_max_ts`
- `row_count`
- `bars_path`

### 5.3 New: Ingest attempt ledger (minimal)

Introduce a small SQLite table, scoped to `ohlcv_1d`, e.g.:

```
ohlcv_1d_ingest_attempts (
    product_id TEXT,
    contract_id TEXT,
    instrument_id INTEGER,
    vendor_start TEXT,
    vendor_end TEXT,
    requested_at TEXT,
    response_rows INTEGER,
    observed_min_ts TEXT,
    observed_max_ts TEXT,
    status TEXT
)
```

Properties:
- Append-only.
- One row per vendor call.
- Mirrors *what we asked for* and *what came back*, not what we store.

This does **not** duplicate dataio payload storage; it indexes it for reasoning.

## 6. Completeness classification (core of Session 12)

Define a small, explicit taxonomy for OHLCV-1D:

```
COMPLETE
VENDOR_LIMITED_COMPLETE
INCOMPLETE_RETRYABLE
INCOMPLETE_PERMANENT
UNMAPPED
```

### 6.1 Deterministic rules (draft)

| Condition | Status |
|---------|--------|
| Stored coverage fully spans expected window | COMPLETE |
| Stored coverage spans vendor-available sub-window exactly | VENDOR_LIMITED_COMPLETE |
| Gaps exist *and* recent ingest attempts returned partial data | INCOMPLETE_RETRYABLE |
| Gaps exist *and* no vendor data exists beyond observed range | INCOMPLETE_PERMANENT |
| No mapping to vendor instrument | UNMAPPED |

These rules will be refined during the session and encoded as pure functions.

## 7. Orchestrator changes (bounded)

The `ohlcv_1d` orchestrator will be updated to:

- Record ingest attempts into the ledger.
- Replace the current boolean `is_complete_level0` decision with:
  - `derive_ohlcv_1d_status(...)`
- Use status to decide:
  - request,
  - skip,
  - or stop retrying.

**Explicitly not in scope:**
- refactoring orchestrator structure wholesale,
- changing storage layout,
- generalising beyond ohlcv_1d.

## 8. Client-facing inspection API (thin)

Add read-only helpers under:

```
mxm.v1.marketdata.ohlcv_1d.status
```

Example capabilities:
- `get_contract_status(product_id, contract_id)`
- `list_incomplete_contracts(product_id)`
- `summarise_product_coverage(product_id)`

These functions compose existing store scans + the new ledger.

## 9. Deliverables / exit criteria

Session 12 is complete when:

1. A minimal ingest-attempt ledger exists and is populated by the orchestrator.
2. Completeness status is derived deterministically for each contract.
3. Update mode can skip contracts that are “as complete as they will ever be”.
4. A client-facing inspection surface exists for OHLCV-1D coverage.
5. No behaviour change is required in upstream datasets.

## 10. Explicit deferrals

- No product-level meta-orchestrator (Session 13).
- No general “dataset accounting framework”.
- No backfill acceleration or optimisation work.

## 11. Session framing note

Session 12 is an **accounting and semantics** session, not an ingestion session.

If successful, Session 13 can safely compose datasets into a product-level orchestrator without ambiguity or hidden retry loops.

