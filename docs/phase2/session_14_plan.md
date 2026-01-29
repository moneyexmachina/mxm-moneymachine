# MXM V1 — Session 14 Plan
## Market Data Observability, Coverage & Reporting

**Session:** 14  
**Phase:** Phase 2 — Market Data Completion (Tail)  
**Status at start:**  
- Product-level meta-orchestrator (`product_marketdata`) complete and operational  
- Dataset-level attempts and product-level attempts persisted in SQLite  
- OHLCV parquet stores populated for a subset of contracts  
- Coverage logic exists implicitly but is not yet exposed or queryable  

## 1. Session Objective

Introduce a **first-class observability and reporting layer** over the market data system.

Session 14 is about *making the system legible* to an operator:

- What data do we have?
- For which products / contracts?
- Over what time ranges?
- What is complete, incomplete, vendor-final, or blocked?
- What happened in recent runs?

This session explicitly **does not** add new ingestion logic.  
It surfaces and formalises what already exists.

## 2. Motivation & Rationale

At this point in Phase 2:

- The ingestion machinery works
- The orchestration logic is sound
- The remaining risk is *operational opacity*

Before introducing:
- multi-product orchestration
- scheduled deployment
- or Phase 3 synthetic assets

We need **operator-grade visibility** into:
- coverage
- completeness
- history
- and current state

Session 14 turns market data from a *black box* into an *inspectable system*.

## 3. Core Deliverables

### 3.1 Market Data Query / Access Layer

Introduce a small, explicit API layer for *reading* market data state.

Location (suggested):

```
mxm/v1/marketdata/reporting/
```

Initial modules (indicative):
- `coverage.py`
- `products.py`
- `contracts.py`
- `attempts.py`

This layer:
- reads from SQLite + parquet
- performs **no ingestion**
- performs **no mutation**

It is safe, read-only, and operator-facing.

### 3.2 Coverage Model (Formalised)

Define a **canonical coverage representation** for OHLCV:

Per contract:
- vendor dataset range
- stored min / max timestamp
- expected target range
- completeness status:
  - `complete`
  - `incomplete`
  - `vendor_final`
  - `empty`
  - `unavailable`

This logic already exists implicitly in `ohlcv_1d`;  
Session 14 **extracts and formalises it**.

Deliverable:
- `CoverageSnapshot` (or similar) as a stable, reusable structure.

### 3.3 Product-Level Coverage Report

Produce a **product-level coverage summary**, answering:

- How many contracts exist?
- How many are mapped?
- How many are complete?
- How many are incomplete?
- How many are vendor-final but partial?
- Earliest / latest coverage across product

Output forms:
- Python object
- JSON
- Pretty terminal output (via `rich`)

### 3.4 Ops / CLI Reporting Scripts

Add one or more *read-only* ops scripts, for example:

```
scripts/marketdata/ops/report_product_coverage.py
scripts/marketdata/ops/report_contract_coverage.py
scripts/marketdata/ops/report_recent_attempts.py
```

Example CLI usage:

```bash
poetry run python scripts/marketdata/ops/report_product_coverage.py \
  --product-id cme_emini_snp500_futures
```

```bash
poetry run python scripts/marketdata/ops/report_recent_attempts.py \
  --product-id cme_emini_snp500_futures \
  --limit 10
```

These scripts:
- never touch vendors
- never mutate state
- are safe to run anytime

### 3.5 Coverage Proof Surfaces

Session 14 must produce **human-legible proof** that the system state is understood.

Minimum proofs:
- Coverage summary for at least 3 products (manually run)
- Clear distinction between:
  - complete contracts
  - incomplete contracts
  - vendor-final contracts
- Correlation between:
  - product attempts
  - dataset attempts
  - resulting coverage

## 4. Explicit Non-goals (Session 14)

The following are **out of scope** and explicitly deferred:

- Multi-product (`product_universe`) orchestrator
- Scheduled / cron-based execution
- Deployment to monolith
- Cross-machine sync
- Phase 3 (synthetic assets)

Session 14 is about **visibility, not scale**.

## 5. Exit Criteria

Session 14 is complete when:

### Functional
- Operator can query coverage without reading parquet manually
- Operator can see *why* coverage is incomplete
- Operator can inspect recent runs and outcomes cleanly

### Operational
- Reports are consistent with known ingestion behaviour
- No new ingestion bugs are introduced
- No state mutation occurs during reporting

### Psychological (important)
- The system “feels real”
- Coverage is no longer abstract
- Confidence exists to proceed to deployment

## 6. Suggested Proof Commands

```bash
# Product coverage
poetry run python scripts/marketdata/ops/report_product_coverage.py \
  --product-id cme_emini_snp500_futures

# Per-contract inspection
poetry run python scripts/marketdata/ops/report_contract_coverage.py \
  --product-id cme_emini_snp500_futures \
  --limit 10

# Recent orchestration history
poetry run python scripts/marketdata/ops/report_recent_attempts.py \
  --product-id cme_emini_snp500_futures \
  --limit 5
```

## 7. Why This Comes Before Universe Orchestration

This session deliberately precedes:
- `product_universe` orchestration
- deployment
- scheduling

Because:
- scaling a system you cannot *see* is reckless
- observability reduces future design churn
- it creates confidence for irreversible steps (cron, prod)

