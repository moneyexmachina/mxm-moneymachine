# session_22_plan.md — MXM V1  
## Session 22 — statistics_1d validation, product-orchestration integration, inspection, and daily views

## Session intent

Turn the Session 21 ingestion pipeline into an operationally trustworthy dataset by:

1) validating what we ingested (both at storage and semantic level),
2) integrating statistics_1d into the product-level orchestrator surface,
3) extending inspection tooling,
4) producing the first derived “daily” API surface (settlement-first).

This session explicitly separates:
- **raw ingestion correctness** (event stream preserved, idempotent, resumable)
from
- **curation correctness** (daily final vs preliminary selection, per-stat semantics).

## Pre-session checklist

- Confirm Session 21 bootstrap run completed (or rerun bootstrap with sufficient cap).
- Confirm local store root and SQLite migrated.
- Choose one representative product for validation: `cme_emini_snp500_futures`.

## Part A — Data validation (raw stream)

### A1) Storage/idempotency checks (one instrument)
For one chosen instrument_id with a large file:

- Read parquet and confirm:
  - schema coercion passes (`coerce_statistics_1d`)
  - `ts_event` is UTC tz-aware; `ts_ref` nullable
  - dedup invariant holds:
    - duplicates on `(instrument_id, stat_type, ts_event, sequence)` == 0
- Re-run ingestion for that single contract and confirm:
  - parquet size is stable (or increases only when new events exist),
  - attempt ledger records NOOP/complete where appropriate,
  - cost usage is near-zero for rerun.

### A2) Coverage sanity checks (product-level)
- Compare eligible contract set vs ohlcv_1d eligible set:
  - expected ~84 eligible for ES under current dataset range.
- Sample per-contract row counts:
  - order of magnitude and distribution look plausible (e.g. 10k–50k rows per contract depending on window).

### A3) Dataset-range alignment assertions
- Confirm raw dataset range end is non-midnight (expected).
- Confirm aligned day-window range is used consistently for:
  - contract eligibility filtering,
  - expected-window derivation,
  - attempt-row storage and formatting.

**Deliverable:** a short “validation notes” block appended to `session_21_log.md` or a new `proof_XX_statistics_1d_bootstrap.md` (optional).

## Part B — Product-level orchestrator integration

### Decision: expand existing product orchestrator vs add a separate one
**Recommendation (default): expand** the existing “product ingest” orchestrator to include `statistics_1d` as another stage:
- `instrument_definitions`
- `instrument_definition_mappings`
- `ohlcv_1d`
- `statistics_1d`  ✅

Rationale:
- shared gates (definitions watermark),
- shared mapping dependency,
- shared budget and stop semantics,
- consistent reporting surface.

Alternative: keep statistics separate temporarily if you want independent schedules/cost caps.

### Implementation plan
- Add a new stage enum / config entry for `statistics_1d`.
- Add invocation of `ingest_statistics_1d_for_product(...)`.
- Standardise per-stage report aggregation and stop_reason handling.

**Definition of Done (Part B):**
- One command runs the full product pipeline including statistics_1d with per-stage caps.
- Report JSON includes stage summaries for all stages.

## Part C — Inspection tooling for statistics_1d

### C1) Minimal inspect module (parallel to ohlcv_1d)
Implement `datasets/statistics_1d/inspect.py` (or equivalent) that can:

- list available instruments/files for a product (via mapping table),
- load a single instrument parquet and print:
  - date coverage (min/max ts_event),
  - presence/ratio of daily stat types (`{3,6,9,10}`),
  - settlement flag distribution (stat_flags, is_final/is_actual),
  - counts per `stat_type`.

### C2) Attempt ledger inspection
- show per-contract status distribution for the latest run,
- identify errors, unmapped, incomplete.

**Definition of Done (Part C):**
- A small set of CLI-friendly functions that give immediate confidence and help debug anomalies.

## Part D — Derived daily view + downstream API (first slice)

### D1) Settlement daily view (first)
Implement a derived view module (suggested location):
- `datasets/statistics_1d/views/settlement_1d.py`
or
- `datasets/statistics_1d/api.py` (if you prefer fewer files initially)

Logic (MVP):
- filter `stat_type == 3` and daily stat subset only,
- group by `(instrument_id, trading_date)` (or `ts_ref` date label),
- selection rule:
  1) choose final (`is_final == True`) if present,
  2) else choose the latest by `ts_event` (and `sequence` as tie-break),
- emit one row per trading_date:
  - `trading_date`, `settlement_price`, `is_final`, `is_actual`, `stat_flags`,
    plus identity columns and provenance.

### D2) Future views (not necessarily in Session 22)
- open interest (9), cleared volume (6), fixing price (10)
- session high/low / open/indicative open (if needed later)

**Definition of Done (Part D):**
- You can call `get_settlement_1d(...)` for an instrument and obtain a clean daily series
  aligned with MXM trading-date semantics.

## Session exit criteria

Session 22 ends when:
1) statistics_1d ingestion is validated (idempotent, ledger consistent),
2) product-level orchestrator includes statistics_1d as a stage (or a deliberate decision is recorded to keep separate),
3) inspection tooling exists for quick operator checks,
4) settlement daily view exists with an API callable by downstream components.

## Notes / known follow-ups

- Generic extraction candidates (later):
  - coverage semantics module shared between datasets,
  - attempts store base class with `path_before/after`,
  - shared contract window helper (currently in `ohlcv_1d/api.py`).
- Keep the raw event stream as the canonical storage; daily series are derived artifacts.

