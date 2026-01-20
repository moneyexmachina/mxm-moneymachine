# MXM V1 — Session 9 Plan  
**Topic:** FuturesContract → Databento Instrument Mapping  
**Prerequisite:** Session 8 closed (instrument definitions persisted, current view + watermarks proven)  
**Status:** Draft plan

## 1. Session 9 Mandate

Session 9 exists to make **instrument identity resolution operational**.

By the end of Session 9, MXM V1 must be able to:

1. Construct and persist a **mapping table** from **MXM FuturesContract** → **Databento instrument identifiers**.
2. Keep the mapping **clean, updateable, and provenance-aware**, using the Session 8 instrument-definition store as authoritative input.
3. Provide a stable API that resolves:
   - `FuturesContract` → `DatabentoInstrumentKey` (at minimum: `(publisher_id, instrument_id)` plus key metadata).
4. Enable downstream market data ingestion to query Databento using **`stype_in="instrument_id"`** rather than raw symbols.

This session is about **identity and mapping correctness**, not OHLCV ingestion refactors (those come immediately after, but are not required for mapping proof).

## 2. Inputs and Invariants (Locked)

### 2.1 Inputs
- MXM reference data:
  - `FuturesProduct`
  - `FuturesContract` enumeration and lifecycle fields (expiry, maturity month/year, etc.)
- Session 8 instrument definitions store:
  - event log (append-only)
  - current view
  - feed-scoped watermarks and provenance

### 2.2 Invariants
- Session 8 tables remain the authoritative source for instrument definitions.
- Mapping layer does not mutate instrument definition history.
- Mapping must be reproducible:
  - deterministic given the same instrument definitions and refdata inputs
  - stable across re-runs
- Mapping must be feed-scoped:
  - mapping is specific to Databento dataset/symbol feed(s)

## 3. Out of Scope (Explicit)

- Switching OHLCV ingestion to `stype_in="instrument_id"` (this is Session 10 unless trivial).
- Calendar completeness checks.
- Multi-vendor mapping or reconciliation.
- Intraday data schemas.
- “As-of reconstruction” APIs beyond current view use.

## 4. Target Deliverables

### 4.1 SQLite mapping table (new dataset-level table)
Create a new table in `marketdata.sqlite3`, e.g.:

- `databento_contract_instrument_map`

Minimum fields (proposed):

- `product_id` (MXM product identifier string)
- `contract_id` (MXM FuturesContract stable identifier)
- `vendor` (constant: `databento`)
- `dataset` (e.g. `GLBX.MDP3`)
- `publisher_id`
- `instrument_id`
- `mapping_method` (e.g. `exact_symbol`, `metadata_match`, `manual_override`)
- `mapping_confidence` (integer or enum; minimally `high/medium/low`)
- `as_of_ts_recv` (the ts_recv in definitions used to produce mapping)
- `as_of_ts_event` (optional, for semantics)
- `created_at`, `updated_at`

Uniqueness constraint:
- `(vendor, dataset, contract_id)` unique
- optional additional uniqueness: `(vendor, dataset, publisher_id, instrument_id)` to prevent aliasing, depending on desired multiplicity

### 4.2 Mapping builder machinery
Introduce a mapping builder module that:

- reads:
  - MXM contract list for a product
  - Databento `instrument_definition_current` rows for the relevant feed(s)
- computes mappings deterministically
- writes mapping rows transactionally
- records the definition “as-of” watermark used to build mappings

### 4.3 Mapping API surface
Provide a minimal API:

- `resolve_contract(contract: FuturesContract, *, as_of: date|None = None) -> DatabentoInstrumentRef`
- `resolve_contracts(contracts: Sequence[FuturesContract], ...) -> dict[ContractId, DatabentoInstrumentRef]`
- `list_unmapped_contracts(product_id: str, ...) -> list[FuturesContract]`

Where `DatabentoInstrumentRef` minimally includes:
- `dataset`
- `publisher_id`
- `instrument_id`
- selected definition metadata: `raw_symbol`, `symbol`, `expiration`, `activation`, etc.

### 4.4 Proof surface (Session exit criteria)
Demonstrate:

1. For one product (e.g. `cme_emini_snp500_futures`), mappings are constructed for a target set of contracts.
2. Re-running the builder yields the same results (idempotent, stable).
3. Mapping rows reference a specific definition watermark (provenance).
4. Given a mapped contract, a Databento query can be formed using `instrument_id` addressing (even if not fully integrated into the OHLCV ingestion path yet).

## 5. Mapping Strategy (Recommended MVP)

Session 9 should aim for the *simplest robust mapping* that is correct enough for MVP.

### 5.1 Use “current” definitions as the primary input
- Work off `instrument_definition_current` (already materialised and queryable).
- Do not replay the full event log except for debugging.

### 5.2 Match key fields deterministically
Primary matching candidates (depending on availability and stability):

- `raw_symbol` and/or `symbol` (if they match MXM contract conventions)
- `maturity_year`, `maturity_month`, `maturity_day` where present
- `expiration`, `activation`
- product-level fields: `asset`, `exchange`, `group`, `underlying`, etc.

### 5.3 Explicit ambiguity handling
Mapping must detect and surface:

- zero matches (unmapped)
- multiple matches (ambiguous)
- low-confidence matches

These must be stored with explicit flags, not silently resolved.

### 5.4 Introduce override hooks (optional but advisable)
Even if not fully implemented, define the interface for:

- manual override table (small)
- allow marking a specific `(contract_id → instrument_id)` override with justification

This prevents future dead-ends.

## 6. Proposed Execution Steps

### Step A — Define schema + migration
- Add migration `0002_databento_contract_mapping.sql`
- Create mapping table + indexes
- Create (optional) manual overrides table

### Step B — Implement mapping store
- New dataset store: `datasets/mapping/databento_contract_map_store.py` or similar
- Responsibilities:
  - read existing mappings
  - upsert mappings
  - list unmapped/ambiguous mappings
  - keep provenance fields

### Step C — Implement mapping builder
- Input:
  - a product’s `FuturesContract` list (from `mxm-refdata`)
  - Databento current definitions for relevant feed (from Session 8 store)
- Output:
  - mapping rows
  - summary stats (mapped/unmapped/ambiguous)

### Step D — Implement mapping API
- Provide ergonomic resolution functions
- Ensure mapping API:
  - never calls vendor APIs
  - only reads local SQLite stores

### Step E — Proof script
Create `scripts/marketdata/96_smoke_build_contract_mappings.py`:

- Ensure instrument definitions exist (run Proof 95 beforehand if needed)
- Build mappings for `cme_emini_snp500_futures`
- Print mapping summary
- Demonstrate forming a Databento request using `instrument_id` for one mapped contract

## 7. Session 9 Exit Criteria (Must Pass)

Session 9 is successful only if:

1. A SQLite mapping table exists and is migrated deterministically.
2. A builder can populate it from local instrument definitions + refdata contracts.
3. The mapping process is stable across re-runs (idempotent outputs).
4. Ambiguities are detected and recorded (not hidden).
5. At least one contract can be resolved to `instrument_id` and used to form a Databento query.

## 8. Notes on Session 10 Preview

Session 10 will likely:

- switch OHLCV ingestion from raw symbols to `instrument_id`
- validate continuity across the addressing change
- prove the end-to-end “refdata → mapping → ingestion → store” loop

Session 9 should therefore focus on producing a mapping artifact that Session 10 can treat as stable input.
