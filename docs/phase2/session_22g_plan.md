# Session 22g — Plan (Tidy-up + DailyStats Consumption Surface)

## Context

Session 22f delivered:

- A stable `statistics_1d` ingestion pipeline with correct intraday dataset-end semantics.
- A derived `daily_stats` surface built for all mapped contracts in a product.
- Integration of `daily_stats` as a downstream stage in `product_marketdata`.

Session 22g now has two clear objectives:

1. **Tidy-up / harden the control-plane:** make all tests green and ensure inspect coverage includes `daily_stats`.
2. **Make `daily_stats` actually usable:** implement a downstream API surface and produce first operator-grade plots/reports.

This session will treat “first usable output” as the target: the system should generate interpretable daily statistics plots at the contract and product level with minimal manual glue.

## Goal State (Acceptance Criteria)

### A. Tidy-up (must be green before building forward)
- `pytest` passes for the whole repo (or at minimum all `marketdata/orchestrators` tests).
- `product_marketdata` stage ordering and gating are correct and test-covered:
  - `daily_stats` executes only if `statistics_1d` is `OK`.
  - `daily_stats` consumes **no vendor budget** (cost_used_usd = 0.0).
  - Correct stop behavior when upstream halts/errors.
- `daily_stats` appears in inspection dispatch and can be invoked via `marketdata_inspect.py`.

### B. Downstream consumption (main deliverable)
- A stable **read API surface** for `daily_stats`:
  - contract-level retrieval with date slicing
  - product-level aggregation / roll-up
  - minimal but explicit semantics for day labels, missing fields, and provenance
- First plotting/report outputs exist:
  - per-contract plot (time series) for settlement + at least one additional field (e.g. open interest)
  - product-level plot or summary that aggregates across contracts (or a grid report)
  - outputs written as artifacts (e.g. `dev_plots/` or `reports/`) with deterministic filenames and metadata sidecars if appropriate

## Work Breakdown

### Phase 0 — Reproduce and localize failing tests (fast triage)
**Deliverables**
- Identify failing tests and categorize:
  1) stage ordering / gating mismatch
  2) StageEnvelope normalization mismatch
  3) expectations around `attempt_uid`, stop_reason, counts keys
  4) mocks/fixtures not updated for new stage
- Write a short “failure map” note (in the session log) listing each failure and cause.

**Actions**
- Run:
  - `pytest -q`
  - `pytest -q tests/.../product_marketdata* -k ...` (tight scope)
- For each failure, pin down whether it is:
  - a legitimate regression (logic wrong)
  - a test contract mismatch (expected stage list missing `daily_stats`)
  - an invariants change (e.g. `contracts_total` semantics changed)

**Acceptance**
- You can explain each failure in one sentence: “expected X, got Y, because Z.”

### Phase 1 — Make tests green (control-plane correctness)
**Deliverables**
- Updated tests reflecting the `daily_stats` stage.
- Additional tests ensuring correct gating and budget semantics.

**Required test cases (minimum set)**
1. **Happy path:** all upstream stages OK → daily_stats stage invoked.
2. **Upstream halt:** statistics_1d halted/error → daily_stats must not run.
3. **Budget exhaustion:** if budget exhausted before statistics_1d, stop earlier (unchanged behavior).
4. **Dry run semantics:** ensure stage behavior consistent (daily_stats should likely still run compute-only but not write if dry_run implies it; decide and enforce explicitly).
5. **Counts propagation:** stage envelope contains `counts` with expected keys for daily_stats (or at least stable minimal set).

**Implementation notes**
- If existing tests compare stage names exactly, update expected stage sequence.
- If tests assume `contracts_total` equals mapped, clarify semantics:
  - daily_stats orchestrator currently emits runs for unmapped as well (184 total, 84 mapped, 100 unmapped) — decide whether that is correct at stage-level reporting, and if not, fix now.
- Maintain “meta-orchestrator contract”:
  - `cost_used_usd`, `stage_status`, `stop_reason`, `counts` stable.

**Acceptance**
- `pytest` green (or at minimum: marketdata orchestration test suite green).

### Phase 2 — Add daily_stats to inspect layer (minimum viable, consistent UX)
**Deliverables**
- `marketdata_inspect.py` supports:
  - `daily_stats contract --contract-key ...`
  - `daily_stats product --product-id ...`
  - `daily_stats system`
  - optionally `daily_stats instrument --publisher-id --instrument-id --vendor-dataset ...` (parity with statistics instrument-level)
- `inspect.dispatch.get_routes()` includes daily_stats routes.
- `_build_attempts_store` and/or `_build_data_store` updated for `daily_stats` as needed.

**Design constraints**
- Inspection remains read-only.
- Prefer meta-first summaries (coverage snapshots + provenance fields).
- Avoid dumping per-contract full records by default:
  - Provide a concise product rollup similar to ohlcv/statistics.
  - Provide `--json` for detailed output.

**Acceptance**
- One-liner works:
  - `poetry run python scripts/marketdata/ops/marketdata_inspect.py daily_stats product --product-id cme_emini_snp500_futures`
- Output includes:
  - contracts_total, ok_terminal, errors/unmapped
  - aggregate coverage window
  - percent of contracts with settle_px populated (optional but high value)

### Phase 3 — DailyStats API surface (downstream consumption)
**Deliverables**
A minimal but well-typed API module (example structure):

- `mxm/v1/marketdata/datasets/daily_stats/api.py` (or `views/daily_stats_api.py`)
  - `read_daily_stats_contract(contract_key, start=None, end=None, fields=None)`
  - `read_daily_stats_instrument(dataset, publisher_id, instrument_id, start=None, end=None)`
  - `read_daily_stats_product(product_id, start=None, end=None, roll="front"|"all")`
  - `list_available_contracts_with_daily_stats(product_id)` (optional)
- Semantics docstring blocks:
  - `session_date` is UTC-midnight day label
  - date slicing is `[start, end)` aligned to day labels
  - missing values for fields are expected; do not drop rows unless explicitly requested
  - provenance:
    - `source_content_sha256` propagated when available
    - if null, surface must state “provenance fallback mode” explicitly

**Acceptance**
- Downstream code can read a full contract’s daily stats in ~3 lines without touching stores directly.

### Phase 4 — First plots and reports (first proper outputs)
**Deliverables**
- A plotting script producing:
  1) **Per-contract report**
     - settle_px (and optionally open/high/low/fix)
     - open_interest_qty
     - cleared_volume_qty
  2) **Product-level report**
     - either:
       - a grid of contract settle series (small multiples), or
       - an aggregate series (e.g. front contract) plus annotations
- Saved artifacts:
  - PNGs in a deterministic directory (e.g. `dev_plots/daily_stats/`).
  - A small JSON meta for each plot (timestamp, inputs, contract key, date range).

**Implementation choices**
- Keep matplotlib simple (no seaborn).
- Prefer one figure per file, no subplots unless product-level grid requires it.
- Use contract-level plot filenames like:
  - `daily_stats__{product_id}__{yyyy_mm}__{start}_{end}.png` (exact naming flexible but deterministic).
- Start with one product: `cme_emini_snp500_futures`.

**Acceptance**
- Running one command produces plots without manual steps.
- Plots are interpretable and reflect real settlement evolution.

## Proposed Execution Order

1. **Triage failing tests → fix until green** (Phase 0–1).
2. **Add daily_stats inspect routes** (Phase 2).
3. **Implement daily_stats API surface** (Phase 3).
4. **Produce first plots/reports** (Phase 4).
5. End session by writing `session_22g_log.md` with:
   - test failures resolved list
   - inspect commands
   - API usage examples
   - plot commands + output paths

## Operator Commands (Target Incantations)

### Tests
- `pytest -q`
- `pytest -q tests/.../test_product_marketdata*.py`

### Inspect (after Phase 2)
- `poetry run python scripts/marketdata/ops/marketdata_inspect.py daily_stats product --product-id cme_emini_snp500_futures`
- `poetry run python scripts/marketdata/ops/marketdata_inspect.py daily_stats contract --contract-key cme_emini_snp500_futures:2010-06`

### API + plots (after Phase 3–4)
- `poetry run python scripts/marketdata/reports/daily_stats_contract_report.py --contract-key ... --start ... --end ...`
- `poetry run python scripts/marketdata/reports/daily_stats_product_report.py --product-id ... --mode front`

## Risks / Known Edge Cases

- `daily_stats` currently reports unmapped contracts in `runs` count; may confuse product-level rollups.
  - Decide whether to keep (explicit unmapped reporting) or suppress and report separately.
- Nullable `ts_ref` impacts settlement anchoring:
  - TradingCalendar mapping must be correct and deterministic for all rows.
- Provenance: if `source_content_sha256` is null, downstream should surface that clearly.

## Definition of Done

Session 22g is done when:

- tests are green,
- daily_stats is inspectable at product and contract level,
- there is a clean read API for downstream consumption,
- and at least one product produces contract-level and product-level plots as first proper outputs.
