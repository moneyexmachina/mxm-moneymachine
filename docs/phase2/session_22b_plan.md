# session_22b_plan.md — MXM V1
## Session 22b — statistics_1d: Product Orchestration, Inspection, Daily Settlement View

## Session intent

Session 22b completes the remaining operational integration work for `statistics_1d` after Session 22’s
hermetic idempotency validation.

We will:

1. Integrate `statistics_1d` as a **stage** in the product-level ingest orchestrator.
2. Extend inspection tooling to support `statistics_1d` (parallel to existing `ohlcv_1d` inspection).
3. Implement the first curated economic surface: a **daily settlement view** derived from the raw event stream.

This is a Session 22b “trust + usability” session: the goal is not new ingestion semantics, but
operational coherence and a first consumer-facing API.

## Context recap (Session 22 completed)

### What is now proved
We have a passing hermetic integration test proving behavioural idempotency of the orchestrator+store:

- first run ingests and writes canonical parquet
- second run no-ops and leaves stored artifact unchanged
- attempt ledger semantics are validated (ingest has `coverage_after`, noop has `coverage_before`, effective coverage stable)

This gives confidence that `statistics_1d` ingestion is reliable under repeat runs.

### What remains
- Product-level orchestration integration
- `inspect` tooling for `statistics_1d`
- Derived daily settlement view (`get_settlement_1d(...)`)

## Hard boundaries (explicit non-goals)

- No changes to weak completeness semantics.
- No refactor to shared base classes for attempts/coverage.
- No multi-stat daily surface beyond settlement (stat_type=3).
- No derived parquet caching yet (compute-on-demand for MVP).
- No economic “correctness” validation (this is a derived concern later).

## Pillar B — Integrate statistics_1d into product-level orchestration

### B1. Identify current product orchestrator surface
Locate the current product orchestrator (the one that currently runs):

- instrument_definitions
- mappings
- ohlcv_1d

Confirm:
- current stage interface shape (what “report”, “counts”, “cost_used_usd”, “stage_status” fields exist)
- where stage ordering is defined
- where budgets/caps are applied

### B2. Add a new stage: `statistics_1d`
Implement as the next stage after `ohlcv_1d` (or immediately after mappings), with explicit rationale:

**Recommended ordering (default):**
1. instrument_definitions (must exist)
2. mappings (must exist)
3. ohlcv_1d (baseline price)
4. statistics_1d (event stream; settlement source)

The stage should:
- call `ingest_statistics_1d_for_product(...)`
- accept the same top-level knobs:
  - mode (bootstrap/update)
  - cost caps and/or “stage caps” (if supported)
  - max_contracts (if meta orchestrator supports it)
  - dry_run, reset_local (if exposed)
- integrate into product report:
  - stage-level report object embedded
  - `counts` summary
  - `cost_used_usd`
  - `stage_status` / `stop_reason`

### B3. Stage reporting contract (Definition of Done)
- Product orchestrator run produces a report that includes:
  - stage summary for statistics_1d
  - stage cost and contract counts
  - stage status/stop reason
- Running product-level ingest triggers statistics_1d stage deterministically.
- Stage ordering is explicit and stable.

### B4. Tests (MVP)
- Add a small hermetic integration test asserting:
  - product orchestrator calls statistics_1d stage exactly once
  - stage report exists in the product-level report
  - stage cost/counters are propagated

(Use the existing `patch_statistics_1d_orchestrator_offline` and similar harness for other stages as needed.)

## Pillar C — Inspection tooling for statistics_1d

### C0. Principle
Inspection utilities must allow the operator to answer:

- “Do we have data?”
- “What is the coverage range?”
- “Is it plausibly shaped?”
- “Where are gaps or anomalies?”

without manually opening parquet.

### C1. File/module placement
Mirror existing inspection structure used for `ohlcv_1d`, e.g.:

- `mxm/v1/marketdata/inspect/statistics_1d.py`
- `scripts/marketdata/inspect/statistics_1d.py` (CLI entrypoint)

(Exact location to match current conventions.)

### C2. Per-instrument inspection (MVP)
Implement:

`inspect_statistics_1d_instrument(dataset, publisher_id, instrument_id, start=None, end=None) -> report`

Report fields (minimum):
- parquet path
- row_count
- min_ts_event, max_ts_event
- min_ts_recv, max_ts_recv
- stat_type counts (value_counts)
- settlement (stat_type=3) breakdown:
  - is_final counts
  - is_actual counts
  - stat_flags distribution (top-k)
- ts_ref null count (overall) + for daily stat types
- sample rows:
  - first N / last N by ts_event
  - optionally a small sample of preliminary → final transitions within a trading_date

Output should be JSON-serialisable.

### C3. Ledger inspection (MVP)
Implement:

`inspect_statistics_1d_attempts(product_id, since_run_ts=None, limit=200) -> report`

Include:
- status counts (value_counts)
- recent errors with error_type/message
- incomplete contracts
- “last attempt per contract” summary table

### C4. Tests
- Unit tests for inspection transforms (pure dataframe logic).
- One hermetic integration test:
  - ingest fixture events
  - run inspector
  - assert non-empty counts and expected columns appear

## Pillar D — Derived daily settlement view (first economic surface)

### D0. Principle
`statistics_1d` is an event stream. A daily view is a derived, curated surface.

MVP: settlement only.

### D1. API design (MVP)
Add:

`get_settlement_1d(*, store: Statistics1DStore, dataset: str, publisher_id: int, instrument_id: int, start: date|ts|None, end: date|ts|None) -> pd.DataFrame`

Return one row per `trading_date` with provenance.

### D2. Selection logic (locked)
Input:
- events filtered to `stat_type == 3`

Grouping key:
- `(instrument_id, trading_date)`

Selection:
1. If any row in group has `is_final == True` → pick that row
   - if multiple finals exist, pick the latest by `(ts_event, sequence)` deterministically
2. Else pick the latest by `(ts_event, sequence)`

Output columns (MVP):
- trading_date
- settlement_price (from `price`)
- is_final
- is_actual
- stat_flags
- ts_event (selected)
- ts_recv (selected)
- ts_ref (selected)
- sequence (selected)
- dataset, publisher_id, instrument_id, raw_symbol (provenance)
- selection_reason: `"final"` or `"latest"`

### D3. Semantics choices (MVP)
- No contiguity enforcement for trading dates (report missing days but do not fail).
- Do not assert that every expected trading date has a settlement event (this is an analysis concern later).
- Compute on demand only; no derived parquet yet.

### D4. Tests
- Pure unit tests on a small fixture frame:
  - final beats non-final
  - latest fallback works
  - deterministic tie-breaking
- One integration test:
  - ingest stats fixture
  - call `get_settlement_1d`
  - assert output row count and selected values match expectation

## Session sequencing (recommended)

1. **Product orchestrator integration** (B)
   - add stage, wire reporting, run once end-to-end (offline harness acceptable)
2. **Inspection tooling** (C)
   - implement per-instrument report + attempts report
   - add CLI entrypoint for operator convenience
3. **Daily settlement view** (D)
   - implement selection function
   - add tests
   - optional: add a CLI “view” command for quick inspection (nice-to-have)

## Definition of Done (Session 22b)

Session 22b is complete when:

1. Product-level ingest runs `statistics_1d` stage and reports it.
2. `inspect statistics_1d` exists for:
   - per-instrument parquet summaries
   - ledger summaries
3. `get_settlement_1d(...)` exists, with tests, and returns a deterministic daily settlement table.

## Notes / follow-ups (explicitly deferred)

- Broader daily surfaces: open/high/low/volume, open interest, etc.
- Derived storage and caching strategy for daily views.
- Richer settlement diagnostics (final transitions, null-set semantics).
- Shared attempts/coverage abstractions across datasets.
