# MXM V1 — Session 11 Plan  
## Product-Level Historical Backfill Orchestrator (Streaming)

**Phase:** Phase 2 — Market Data Completion  
**Session:** 11  
**Status:** Planned  
**Pre-requisites:** Sessions 7–10 completed and merged

## 1. Session Objective (Single Goal)

> Build a **product-level historical backfill orchestrator** that, for one `product_id`, deterministically backfills **ohlcv-1d bars** for all mapped futures contracts over their full lifecycle windows, using **instrument_id-based streaming ingestion**, with idempotent persistence, cost control, and coverage reporting.

This session establishes the first complete, end-to-end market-data pipeline for a futures product in MXM V1.

## 2. Scope (What We WILL Build)

### 2.1 Orchestrator Entry Point

A single script (or CLI entrypoint) that performs, for one `product_id`:

1. Ensure Databento instrument definition coverage is sufficient (bounded, deterministic policy).
2. Rebuild/update the mapping table deterministically.
3. Backfill OHLCV-1D bars contract-by-contract using instrument_id addressing.
4. Produce a coverage report summarizing:
   - mapping coverage (maturity range mapped)
   - bars coverage per contract (min/max ts_event, row count)
   - complete vs incomplete vs unmapped

Recommended location:

- `scripts/marketdata/99_backfill_product.py` (proof-grade, non-library)

### 2.2 Internal Step Boundaries

Although invoked as one orchestrator, implementation must preserve explicit steps with clean seams:

- `ensure_instrument_definitions_coverage(product_id, ...)`
- `build_or_update_mappings(product_id, ...)`
- `backfill_bars_for_product(product_id, ...)`

This ensures the orchestrator remains composable and will later support `mode="update"` in Session 12.

### 2.3 Delivery Mode Seam (Future-Proofing)

Introduce a `delivery_mode` seam in the Databento fetcher API:

- `delivery_mode="stream"` implemented (default)
- `delivery_mode="batch"` reserved; must fail explicitly with `NotImplementedError`

Session 11 uses streaming only.

## 3. Non-Goals (Explicitly Out of Scope)

Session 11 does **not** implement:

- batch download ingestion
- universe-wide orchestration across multiple product_ids
- daily update scheduling or “as-of” discipline (Session 12)
- roll logic / continuous chains
- multi-schema ingestion (only `ohlcv-1d`)
- signal/strategy/portfolio layers
- full reporting dashboard; only a proof-grade textual coverage report

## 4. Design Decisions and Invariants

### 4.1 Addressing and Identity

- All OHLCV ingestion must use `stype_in="instrument_id"`.
- Symbol-based addressing is forbidden at the orchestrator boundary.
- `resolve_databento_instrument(...) -> DatabentoInstrumentIdentity` is the only resolution mechanism.

### 4.2 Window Policy (Backfill Mode)

For each contract:

- `target_start = FuturesContract.first_day_of_interest`
- `target_end   = FuturesContract.last_trading_day`

The orchestrator must not ingest outside this window.

### 4.3 Idempotency and Safety

The orchestrator must be safe to re-run:

- instrument definition events are append-only
- mapping rebuild is deterministic + idempotent
- DataIO caching prevents duplicate paid streaming retrieval
- parquet merge-write ensures eventual completeness without duplicates

### 4.4 Determinism

- Contract iteration must be stable and deterministic (e.g., ascending maturity, then contract_id).
- Summary output must include stable counts and ranges.

## 5. Minimal “Cleverness” Required (Completion Tracking)

A backfill orchestrator must avoid aimless reprocessing. For Session 11 we implement a minimal completeness check (Level 0):

A contract is considered “complete” if:

- stored `min(ts_event) <= target_start`
- stored `max(ts_event) >= target_end`
- stored row count > 0

Calendar-true completeness is deferred (possible Session 12+).

Implementation options (choose one):

- **Option A (preferred):** store coverage status in SQLite (new small table)
- **Option B (acceptable MVP):** compute coverage by reading parquet each run

Session 11 must at minimum emit coverage (min/max/rows) per contract in the final report.

## 6. Session Plan (Step-by-Step)

### Step 1 — Orchestrator Skeleton + Configuration

- Add `scripts/marketdata/99_backfill_product.py`
- Parameters (proof-grade):
  - `--product-id` (default to a known product such as `cme_emini_snp500_futures`)
  - `--cap-usd` (strict)
  - `--max-contracts` (optional throttle)
  - `--dry-run` (optional: resolve + report only)
- Ensure deterministic ordering of contracts.

### Step 2 — Definitions Coverage Ensure (Minimal)

- Implement a bounded policy such as:
  - Ensure instrument definition events exist for the product root over a required time window that covers the earliest mapped maturity targeted by refdata backfill.
- If the required coverage is missing, call the existing definitions pull/ingest machinery to extend coverage.

This step must be safe to run repeatedly.

### Step 3 — Mappings Build/Update

- Reuse the Session 9 mapping builder:
  - build mappings for all maturities supported by overlap between refdata contracts and vendor definitions (current view).
- Emit mapping report (inserted/ignored/unmapped).
- This step is deterministic and idempotent.

### Step 4 — Bars Backfill Loop (Contract-by-Contract)

For each contract (deterministic order):

1. Resolve identity:
   - `ident = resolve_databento_instrument(backend, contract)`
2. Determine target window from refdata:
   - `[first_day_of_interest, last_trading_day]`
3. Check store coverage (skip if “complete”).
4. Cost gate:
   - estimate cost for the request window
   - enforce per-request and per-session caps
5. Pull via DataIO:
   - `pull_ohlcv_1d_by_instrument_id(..., instrument_id=ident.instrument_id, stype_in="instrument_id")`
6. Normalize with `raw_symbol=ident.raw_symbol`.
7. Persist via `write_daily_bars` merge-write.
8. Post-write: recompute coverage and record result.

Errors must be categorized:
- unmapped (coverage limitation, not fatal)
- cost cap hit (stop condition)
- vendor failure (continue/report)
- schema/validation failure (hard stop)

### Step 5 — Coverage Report + Proof Closure

Produce a final report including:

- product_id
- mapping coverage: min/max maturity mapped
- total refdata contracts
- mapped/unmapped counts
- bars:
  - complete count
  - incomplete count
  - per-contract coverage (min/max/rows) for incomplete ones
- cumulative estimated cost vs cap

## 7. Proof Surface (Proof 99)

Session 11 is complete when `scripts/marketdata/99_backfill_product.py` demonstrates, for one product:

1. Definitions coverage ensure step runs (or no-ops deterministically).
2. Mappings update runs and reports deterministically.
3. Bars are ingested by instrument_id for multiple contracts and persisted in canonical paths.
4. Rerun behavior:
   - already-complete contracts are skipped (or no additional rows appear)
   - DataIO shows cache hits where applicable
5. Final coverage report prints stable, auditable summary.

Proof artifacts:

- Console output log
- Stored parquet paths under:
  - `~/.mxm/marketdata/databento/ohlcv-1d/by_instrument/...`
- (Optional) a small JSON/CSV coverage report saved alongside the proof script output

## 8. Forward Seam for Session 12 (Daily Update Mode)

The orchestrator must be designed to support `mode="update"` later, without rewriting:

- Introduce a `mode` argument internally (even if only `backfill` is implemented now).
- Keep window selection in a dedicated function:
  - `compute_target_window(mode, contract, store_state, as_of_date)`
- Session 12 will:
  - add `as_of_date` discipline
  - implement incremental `target_start = stored_max + 1 trading day`
  - filter contracts to those active in interest window

## 9. Exit Criteria (Non-Negotiable)

Session 11 is closed when:

- Proof 99 runs successfully for one product_id
- multiple contracts are ingested via instrument_id and persisted
- rerun is safe and produces no uncontrolled duplication
- a coverage report exists and is interpretable
- delivery_mode seam exists in the fetcher (stream implemented, batch reserved)

