# Phase 2 — Market Data Completion

**Project:** MXM V1 MVP  
**Phase:** 2  
**Primary focus:** Futures market data substrate (Databento, daily OHLCV)  
**Status:** Planned

## 1. Phase objective

Complete the futures market-data substrate such that the MXM system can:

* deterministically reconstruct the full observable daily market history of the MVP futures universe, and
* keep that history up to date operationally with no manual intervention.

This phase explicitly closes the market-data foundation. All downstream work (synthetic assets, P&L simulation, portfolios) depends on this phase being complete.

## 2. Scope and non-scope

### In scope

* FuturesProducts and FuturesContracts in the MVP universe
* Databento as the sole market-data vendor
* Daily OHLCV (1D bars) only
* Historical backfill and daily incremental updates
* Persistent storage and deterministic retrieval

### Explicitly out of scope

* Synthetic assets
* P&L simulation
* Portfolios, strategies, or signals
* Intraday data
* Additional vendors or asset classes

## 3. Exit criteria (non-negotiable)

Phase 2 is complete if and only if **all** criteria below are satisfied.

### A. Universe and contract truth

For each MVP `FuturesProduct` (`product_id`):

1. All historical `FuturesContracts` required for the product’s full tradable history are identified.
2. Contract enumeration respects lifecycle rules (`first_day_of_interest`, `last_trading_day`) defined in `mxm-refdata`.

### B. Vendor identity completeness

3. Each `FuturesContract` is mapped to exactly one Databento `instrument_id`.
4. The mapping is persisted in the marketdata store and reproducible (not computed ad hoc).

### C. OHLCV completeness and persistence

5. All available daily OHLCV bars for each mapped contract are persisted.
6. Data can be retrieved deterministically by:
   * `product_id`
   * `contract_id`
   * `date_range`

Retrieval must not depend on network access or runtime state once data is persisted.

### D. Data quality accounting

7. Any missing or unavailable data is:
   * enumerated (which contracts, which dates),
   * justified (vendor unavailable, contract not listed, expected holiday gap, etc.),
   * explicit (logged and/or persisted), not accidental.

Silent gaps are not permitted.

### E. Operational orchestration

8. A **backfill orchestrator** exists:
   * accepts a `product_id` universe,
   * is idempotent and resumable,
   * produces a clear run summary.

9. A **daily update orchestrator** exists:
   * updates a `product_id` universe incrementally “to current”,
   * is idempotent,
   * produces a clear daily run summary.

10. The daily update orchestrator is:
    * deployed via cron (or equivalent scheduler), **or**
    * explicitly documented as deployment-blocked with prerequisites listed.

## 4. Phase invariants

The following invariants must hold throughout Phase 2:

* No synthetic or derived instruments are introduced.
* Vendor data is treated as immutable once persisted.
* All persistence is idempotent.
* All scripts are safe to re-run.
* All decisions are recorded in logs or documentation.

## 5. Session breakdown (indicative)

Session counts are estimates; sessions are atomic and proof-driven.

### Session 9 — Instrument mapping table

**Objective**
* Design and implement the persistent mapping:
  `FuturesContract → Databento instrument_id`.

**Key tasks**
* Define mapping table schema.
* Populate mapping using Databento instrument definitions.
* Validate one-to-one mapping and lifecycle alignment.

**Proof surface**
* Mapping table exists and is populated for the full MVP universe.
* Scripted lookup from `contract_id` to `instrument_id` works deterministically.

### Session 10 — OHLCV backfill orchestrator

**Objective**
* Implement a reusable backfill orchestrator for a product universe.

**Key tasks**
* Iterate contracts and date windows.
* Fetch daily OHLCV bars.
* Persist idempotently.
* Capture gaps and metadata.

**Proof surface**
* Backfill can be run for at least one full FuturesProduct.
* Re-running the orchestrator produces no duplicate data.
* Run summary clearly reports rows written and gaps detected.

### Session 11 — Full universe backfill and validation

**Objective**
* Execute the backfill for the full MVP universe.

**Key tasks**
* Run orchestrator across all products.
* Monitor cost, duration, and error behaviour.
* Enumerate and justify all gaps.

**Proof surface**
* All MVP products have complete historical OHLCV on disk.
* Gap ledger exists and is reviewed.

### Session 12 — Daily update orchestrator

**Objective**
* Implement incremental daily update logic.

**Key tasks**
* Determine last persisted date per contract.
* Fetch only missing bars.
* Ensure idempotency and robustness.

**Proof surface**
* Daily update script can be run repeatedly with stable results.
* Clear daily run summary produced.

### Session 13 — Operational deployment

**Objective**
* Make daily updates operational.

**Key tasks**
* Deploy daily update via cron or scheduler.
* Ensure environment and credentials are correct.
* Capture logs persistently.

**Proof surface**
* Cron entry (or equivalent) documented.
* At least one observed successful scheduled run, **or**
* Explicitly documented deployment blocker.


### Session 14 — Reporting and visual verification

**Objective**  
Provide lightweight, deterministic visual inspection tooling to verify completeness, continuity, and sanity of persisted daily OHLCV data.

This session exists explicitly to reduce downstream ambiguity and debugging cost.

**Key tasks**

* Script A — Contract history plot
  * Inputs:
    * `contract_id`
    * optional `date_range`
  * Behaviour:
    * reads OHLCV exclusively from the persisted marketdata store
    * produces a saved plot (PNG) of daily close prices
    * optionally overlays high–low range and/or volume if trivial
  * Purpose:
    * visually confirm continuity, listing start, and absence of silent gaps

* Script B — Product-level contract plot
  * Inputs:
    * `product_id`
    * optional `date_range`
    * display mode flag (`overlay` or `stacked`)
  * Behaviour:
    * renders all contracts belonging to the product
    * makes roll structure, overlaps, and gaps visually obvious
  * Purpose:
    * verify full contract coverage and expected handoff behaviour

**Proof surface**

* At least one FuturesContract plot renders correctly from persisted data.
* At least one FuturesProduct plot renders multiple contracts.
* Visual inspection confirms:
  * no unexpected discontinuities
  * no silent multi-day or multi-week gaps
  * expected listing start dates and known holiday gaps only

#### Addendum to exit criteria (verification surface)

* A minimal, script-driven visual verification surface exists to inspect
  daily OHLCV histories by:
  * individual FuturesContract, and
  * full FuturesProduct contract set.

This surface is CLI-invoked, non-interactive by default, and intended for
on-demand inspection rather than continuous monitoring.

#### Addendum to artifacts produced

* Contract-level OHLCV plotting script
* Product-level OHLCV plotting script
* Saved example plots demonstrating successful visual verification

## 6. Artifacts produced in Phase 2

By the end of this phase, the following artifacts must exist:

* Marketdata database with:
  * instrument definition table
  * contract → instrument mapping table
  * daily OHLCV tables
  * gap / metadata records
* Backfill orchestrator script
* Daily update orchestrator script
* Logs demonstrating successful runs
* This plan marked as **COMPLETED**

## 7. Phase completion statement

Phase 2 is complete when the MXM system can state, truthfully and defensibly:

> “We can reconstruct the full daily market history of our MVP futures universe and keep it current, deterministically and operationally.”

Only after that statement is true does Phase 3 begin.
