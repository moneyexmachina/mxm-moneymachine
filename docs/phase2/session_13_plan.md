# MXM V1 — Session 13 Plan
## Product-level Market Data Meta-Orchestrator

**Session:** 13  
**Phase:** Phase 2 — Market Data Completion  
**Scope:** Product-level orchestration  
**Status at start:**  
- Dataset-level orchestrators complete and operational:
  - `instrument_definitions`
  - `instrument_definition_mappings`
  - `ohlcv_1d`
- Cost-gating, reset semantics, dry-run semantics validated (Session 12)

## 1. Session Objective

Build an **operations-grade product-level market data orchestrator** that composes the existing dataset orchestrators into a single, coherent workflow per product.

The result should allow an operator to issue **one command per product** to:

- **bootstrap** a product from empty to usable historical coverage
- **update** a product incrementally from watermarks and existing coverage
- enforce a **single run-level cost cap**
- produce a **coherent, auditable report** of what happened (and why)

This orchestrator is the final assembly layer for Phase 2 market data.

## 2. Core Deliverables

### 2.1 Product-level orchestrator module

Create a new orchestrator module, for example:

```
mxm/v1/marketdata/orchestrators/product_marketdata.py
```

Primary entry point:

```python
def ingest_product_marketdata(
    *,
    product_id: str,
    client,                  # databento.Historical (kept untyped)
    mode: Mode,              # bootstrap | update
    cost_cap_usd: float,
    max_windows: int | None = None,
    max_contracts: int | None = None,
    window_days: int = 31,
    overlap: str = "1d",
    reset: bool = False,         # destructive product-level reset
    reset_local: bool = False,   # pass-through to ohlcv only
    dry_run: bool = False,
    end: str | None = None,
) -> ProductMarketdataReport:
    ...
```

Responsibilities:
- Run **product-level gates**
- Invoke dataset-level orchestrators in the correct order
- Allocate and track **remaining budget**
- Stop deterministically when limits are hit
- Return a single, structured product-level report

### 2.2 Ops script (CLI entry point)

Create:

```
scripts/marketdata/ops/product_marketdata.py
```

CLI arguments (minimum):
- `--product-id`
- `--mode {bootstrap,update}`
- `--cost-cap-usd`
- `--max-contracts`
- `--max-windows`
- `--window-days`
- `--dry-run`
- `--reset`
- `--reset-local`
- `--end`

This should mirror the UX and logging style of existing dataset ops scripts.

### 2.3 Product-level attempt table (recommended)

Add a new SQLite table, e.g.:

```
marketdata_product_attempts
```

One row per **product run**, capturing:
- run timestamp / run id
- product_id
- mode, dry_run, reset, reset_local
- cost_cap_usd
- cost_used_total
- summary counters from sub-orchestrators
- stopped_reason

This provides a clean, auditable envelope around the existing dataset-level attempt tables.

## 3. Orchestration Ordering Contract

### 3.1 Bootstrap mode

Goal: establish a coherent historical base.

Execution order:
1. **instrument_definitions**
   - Ensure watermark exists
   - Bootstrap definitions history as required
2. **instrument_definition_mappings**
   - Ensure mappings exist for contracts in scope
3. **ohlcv_1d**
   - Bootstrap daily bars for mapped contracts
   - Respect `max_contracts`, `max_windows`, and remaining budget

### 3.2 Update mode

Goal: forward-fill incrementally.

Execution order:
1. **instrument_definitions** (update from watermark)
2. **instrument_definition_mappings** (new or changed instruments)
3. **ohlcv_1d** (only missing or newly required coverage)

Idempotency is expected when nothing has changed.

## 4. Budget Allocation Policy

Session 13 uses a **simple, deterministic budget allocator**:

- A single `remaining_usd` is maintained at product level
- Sub-orchestrators are called sequentially:
  1. definitions
  2. mappings
  3. ohlcv_1d
- Each sub-orchestrator receives the remaining budget
- `remaining_usd` is decremented by `cost_used_usd` returned
- If budget is exhausted, the run stops cleanly with a clear `stopped_reason`

No prioritisation or rebalancing logic is required in this session.

## 5. Dry-run Semantics (Product-level)

A product dry-run must:
- Perform **no vendor calls**
- Still:
  - read watermarks
  - scan coverage
  - derive expected windows
  - compute decisions
- Record attempt rows with `status = dry_run`
- Produce a full product-level report describing **what would happen**

Dry-run is a planning and verification tool, not a no-op.

## 6. Product-level States & Reporting

The product orchestrator does **not** introduce a new complex state machine.

Instead, it derives high-level outcomes from subreports, such as:
- `blocked_missing_definitions`
- `blocked_missing_mappings`
- `ohlcv_incomplete`
- `done`
- `dry_run`
- `stopped_budget`
- `stopped_limits`

All decisions remain traceable to dataset-level logic.

## 7. Exit Criteria (Session 13)

### 7.1 Functional
- One CLI command can bootstrap a product end-to-end
- One CLI command can update a product idempotently
- Cost cap is enforced at product level
- Dry-run behaves correctly and transparently

### 7.2 Operational Proof Surfaces
- Bootstrap dry-run produces coherent report
- Bootstrap real run with small caps fetches limited data
- Update run after bootstrap does no work
- SQLite evidence:
  - product-level attempt row
  - corresponding dataset-level attempt rows

## 8. Suggested Proof Commands

Bootstrap (dry-run):
```bash
poetry run python scripts/marketdata/ops/product_marketdata.py \
  --product-id cme_emini_snp500_futures \
  --mode bootstrap \
  --cost-cap-usd 0.10 \
  --max-contracts 5 \
  --dry-run
```

Bootstrap (real, small):
```bash
poetry run python scripts/marketdata/ops/product_marketdata.py \
  --product-id cme_emini_snp500_futures \
  --mode bootstrap \
  --cost-cap-usd 0.10 \
  --max-contracts 2
```

Update (dry-run):
```bash
poetry run python scripts/marketdata/ops/product_marketdata.py \
  --product-id cme_emini_snp500_futures \
  --mode update \
  --cost-cap-usd 0.10 \
  --dry-run
```

Update (real):
```bash
poetry run python scripts/marketdata/ops/product_marketdata.py \
  --product-id cme_emini_snp500_futures \
  --mode update \
  --cost-cap-usd 0.10
```

## 9. Explicit Non-goals (Deferred)

- Cache-hit-aware cost estimation in `mxm-dataio`
- Advanced scheduling or prioritisation heuristics
- Multi-product orchestration
- Parallel execution

These are consciously deferred beyond Session 13.

**Session 13 closes Phase 2 market data by delivering a single, stable, operator-facing entry point per product.**
