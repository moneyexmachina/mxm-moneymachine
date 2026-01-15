
## Week 1 — Remaining Plan (post Session 3)

### Status (completed)
- Dataset identified and confirmed: `GLBX.MDP3`
- Schema confirmed: `ohlcv-1d`
- Cost gating established (`metadata.get_cost`)
- Successful daily-bar retrieval for an active contract (`ESH6`)
- Technical capability proven: instrument-by-instrument daily OHLCV pull with identity fields

---

### Next Steps (in order)

#### 1) Daily-bar semantics and calendar alignment
Goal: understand precisely what `ohlcv-1d` represents.
- Confirm the aggregation boundary implied by `ts_event` (00:00 UTC) versus Globex session boundaries.
- Determine whether bars correspond to:
  - calendar day UTC,
  - Globex trading day,
  - settlement-derived day,
  - or vendor-specific conventions.
- Validate against:
  - CME session calendars / holidays,
  - expected weekend gaps,
  - spot-check vs another source (IB or CME settlement where feasible).

Deliverable:
- `docs/week1/daily_bar_semantics.md` (or section in `databento_notes.md`) stating the adopted interpretation and known caveats.

---

#### 2) Backfill economics
Goal: quantify the billable cost of building 15y history for the intended universe.
- Use `metadata.get_billable_size` and `metadata.get_cost` to estimate:
  - one contract × full history,
  - one product chain × full history (once chain definition is chosen),
  - extrapolate to 30-product universe and later 100+ products.
- Decide backfill policy:
  - full history vs staged, incremental backfill,
  - contract coverage (all months vs quarterly only),
  - whether to backfill expired contracts or only build continuous research series.

Deliverable:
- `docs/week1/backfill_budget.md` with concrete $ estimates and chosen backfill policy.

---

#### 3) Ref-data ↔ market-data boundary decision
Goal: formalise what lives in `mxm-refdata` versus what is sourced from Databento.
- Default stance: retain `mxm-refdata` as canonical for product/contract definitions.
- Define how Databento identifiers map onto MXM identifiers:
  - store `dataset`, `publisher_id`, `instrument_id`, and `raw_symbol` mapping.
- Define reconciliation approach:
  - contract list consistency checks,
  - contract metadata discrepancies,
  - escalation if mismatch exists.

Deliverable:
- `docs/week1/refdata_marketdata_boundary.md` defining authority and mapping rules.

---

#### 4) Idempotency, persistence, caching
Goal: establish reliable storage and update mechanics for daily bars.
- Define storage format and partitioning (e.g. parquet per instrument or per product).
- Define idempotent pull semantics:
  - same query yields same output and overwrites safely,
  - deterministic daily update window and schedule.
- Define caching:
  - local cache keyed by (dataset, schema, symbol/instrument_id, start, end),
  - cost-gate before cache miss pulls.

Deliverable:
- minimal ingestion spec + v0 implementation plan (no premature abstractions).

---

#### 5) Complete the initial 30-futures universe (Week 1 deliverable)
Goal: finish the Week 1 “inputs” milestone.
- Integrate 30 futures products into `mxm-refdata` universe file(s).
- Create valid Databento identifiers for each:
  - confirm symbol conventions,
  - ensure at least one active contract symbol exists per product.
- Reconcile instrument information between MXM and Databento (unless refdata authority changes).
- Backfill, store, and serve daily bars for the universe under the chosen semantics and alignment rules.
- Define the daily update procedure and “latest available” logic.

Done condition:
- A complete, internally consistent 30-product universe with stored daily bars and a repeatable daily update process.
