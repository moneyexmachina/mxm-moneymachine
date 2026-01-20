# MXM V1 — Session 9 Log  
**Session Title:** Instrument Definition → FuturesContract Mapping  
**Date:** 2026-01-20  
**Phase:** Phase 2 — Market Data Completion  
**Session Objective:**  
Establish a deterministic, persistent, and idempotent mapping between MXM FuturesContracts (refdata truth) and Databento instrument identifiers (vendor truth), suitable for downstream market-data retrieval and daily operation.

## 1. Session Mandate (from plan)

Session 9 was tasked with:

- Designing and implementing a **mapping table** that bridges:
  - MXM FuturesContract identity  
    `(product_id, contract_year, contract_month)`
  - to Databento instrument identity  
    `(publisher_id, instrument_id)`
- Building mappings **from vendor instrument_definition_current**, not from refdata heuristics.
- Ensuring:
  - Deterministic mapping keys
  - Idempotent rebuild semantics
  - Explicit validity windows
  - Clear operational boundaries for daily updates
- Producing a proof script demonstrating:
  - Correct overlap detection
  - Successful mapping
  - Idempotency on re-execution
  - Runtime resolution for downstream consumers

## 2. Design Decisions Locked In

### 2.1 Mapping Identity (MVP)

For MVP, mappings are keyed by:

- `product_id`
- `contract_year`
- `contract_month`

Notes:

- This deliberately restricts scope to **monthly outright futures**.
- Quarterly / non-monthly contracts are deferred by design.
- Schema and code are written so that a future migration is possible without semantic breakage.

### 2.2 Source-of-Truth Boundary

- **Vendor variability:** `instrument_definition_current`
- **MXM truth:** `mxm-refdata` FuturesContracts

Mapping construction rules:

- Iterate over MXM refdata contracts.
- Attempt to resolve only against **currently known vendor definitions**.
- Accept that refdata extends further into the future than vendor availability.
- Treat the vendor definition set as the natural daily boundary.

### 2.3 Persistence Model

- Append-only vendor events (`instrument_definition_events`)
- Materialised current view (`instrument_definition_current`)
- Deterministic mapping table (`instrument_definition_mappings`)
- Explicit validity windows (`valid_from`, `valid_to`)
- Mapping rows are **never mutated**, only added or ignored.

## 3. Schema Work Completed

### 3.1 New Migration

Added migration:

- `0002_instrument_definition_mappings.sql`

This introduces:

- `instrument_definition_mappings` table
- Deterministic primary key (`mapping_uid`)
- MXM contract identity fields
- Vendor identity fields
- Denormalised explainability fields
- Validity window semantics
- Supporting indexes for lookup and auditing

### 3.2 Migration Infrastructure

Confirmed working:

- `SQLiteBackend.ensure_migrated`
- Ordered, deterministic application
- `schema_migrations` bookkeeping
- Safe re-runs without duplication

## 4. Implementation Work

### 4.1 Mapping Builder

Implemented mapping logic that:

- Reads MXM FuturesContracts via `RefDataAPI`
- Reads vendor definitions via `instrument_definition_current`
- Filters to:
  - `security_type = FUT`
  - `instrument_class = F` (outright futures only)
- Matches on `(maturity_year, maturity_month)`
- Constructs stable mapping records
- Inserts only new mappings (idempotent semantics)

### 4.2 Code Structure Cleanup

- Removed legacy vendor-specific mapping store code.
- Retained `product_roots.py` as **code-versioned product → vendor root mapping**.
- Introduced new mapping logic at `mxm.v1.marketdata.mapping`.

## 5. Proof Surface

### 5.1 Proof Script

Executed:

```bash
poetry run python scripts/marketdata/96_proof_build_instrument_mappings.py
```

### 5.2 First Run (Insertion)

Output:

- Vendor outright maturities: `6`
- Refdata maturities: `184`
- Overlap attempted: `6`
- Inserted: `6`
- Ignored: `0`
- Unmapped: `0`

Runtime resolution example:

```json
resolve(2011-09): {
  "publisher_id": 1,
  "instrument_id": 49278,
  "raw_symbol": "ESU1",
  "valid_from": "2010-06-18T13:30:00.000000Z",
  "valid_to": "2011-09-16T13:30:00.000000Z"
}
```

### 5.3 Second Run (Idempotency)

Re-execution produced:

- Inserted: `0`
- Ignored: `6`
- Unmapped: `0`

This confirms strict idempotency.

### 5.4 Table Audit

Manual inspection via `sqlite3` confirmed:

- Exactly 6 mappings present
- Correct contract months and years
- Correct Databento instrument IDs
- Correct validity windows
- Deterministic ordering

## 6. Invariants Verified

- Vendor and refdata universes are cleanly separated.
- Mapping only occurs where vendor definitions exist.
- Mapping table is stable under re-execution.
- Downstream resolution is constant-time and unambiguous.
- No reliance on fragile symbol parsing.
- All state is inspectable via CLI tooling.

## 7. Session Outcome

**Session 9 is COMPLETE.**

The MXM system now has:

- A first-class, persistent bridge between refdata and vendor identifiers.
- A clean daily update model for mappings.
- A stable foundation for market-data ingestion and storage.

This unlocks:

- Deterministic daily bar updates
- Product-level market data queries
- Downstream signal and strategy work without vendor leakage

## 8. Deferred / Follow-Up Items

These are explicitly **out of scope for Session 9**, but identified during the work:

1. **mxm-refdata bugfix**
   - Period resolution convenience (period lookup by `period_id`)
   - To be addressed in a low-energy maintenance session.

2. **Migration hash discipline**
   - Current migration runner tracks names only.
   - Add optional content hash to `schema_migrations` to detect edited migrations.

Neither item blocks Phase 2 progress.

## 9. Confidence Assessment

High.

This session established a critical architectural boundary correctly, early, and with strong proof discipline. No shortcuts were taken, and no hidden coupling was introduced.

**Session 9 closed.**
