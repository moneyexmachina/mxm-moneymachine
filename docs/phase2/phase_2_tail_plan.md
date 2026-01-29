# MXM V1 — Phase 2 Tail Plan
## Market Data Expansion, Reporting, and Operationalisation

**Phase:** Phase 2 — Market Data Completion (Tail)  
**Position in roadmap:** After Session 13 (product-level meta-orchestrator)  
**Status at start:**  
- Product-level orchestrator (`product_marketdata`) complete and operational  
- Dataset-level ingestion, mapping, coverage, and attempt ledgers in place  
- Phase 2 core objective (single-product end-to-end ingestion) achieved  

This tail phase focuses on **scaling, observability, and operations**, not new data primitives.

## 1. Purpose of the Phase 2 Tail

Phase 2 proper established *correctness* for a single product.

The **Phase 2 tail** establishes:

- **Scale**: multiple products, consistent execution
- **Visibility**: coverage, gaps, and data state
- **Operability**: scheduled runs on a stable machine
- **Readiness**: a clean hand-off into Phase 3 (synthetic assets, strategies)

No new ingestion semantics are introduced here.

## 2. Workstreams Overview

This tail phase is split into **five focused workstreams**, each suitable for one or more short sessions.

1. Multi-product orchestration (product universe)
2. Product universe expansion (refdata)
3. Market data reporting & query layer
4. Deployment & operational setup
5. Phase 3 readiness checkpoint

## 3. Workstream A — Multi-Product Orchestration

### Objective
Introduce a **thin wrapper** that runs the existing product-level orchestrator across a defined universe of products.

### Deliverables

#### 3.1 Product universe definition
- Define a canonical product universe (initially small and explicit)
- Likely location:
  ```
  mxm-refdata/products/*.yaml
  ```
- Each product entry minimally includes:
  - product_id
  - vendor feed metadata
  - inclusion flags (enabled / disabled)

#### 3.2 Multi-product orchestrator
Create a wrapper orchestrator, for example:

```
mxm/v1/marketdata/orchestrators/product_universe.py
```

Responsibilities:
- Iterate over products
- Invoke `ingest_product_marketdata` per product
- Aggregate results into a universe-level report
- Stop deterministically on fatal errors (optional policy)

#### 3.3 Ops script
Create:

```
scripts/marketdata/ops/product_universe.py
```

CLI arguments:
- `--mode`
- `--cost-cap-usd` (global or per-product)
- `--products` (subset filter)
- `--dry-run`
- `--reset`
- `--reset-local`

This script must remain **mechanical** — no new orchestration intelligence.

## 4. Workstream B — Product Universe Expansion

### Objective
Expand beyond the initial CME E-mini product by enriching MXM refdata.

### Scope
- Manual, explicit expansion
- No scraping automation yet

### Deliverables

#### 4.1 CME product survey session
- Review CME website and documentation
- Identify:
  - Equity index futures
  - Rates futures
  - Core liquid commodities
- Capture:
  - Root symbols
  - Contract cycles
  - Vendor dataset compatibility

#### 4.2 Refdata updates
- Extend `mxm-refdata` with additional product definitions
- Ensure:
  - Naming consistency
  - Explicit exclusions where applicable
  - Version-controlled provenance

This is a **knowledge curation task**, not a coding-heavy one.

## 5. Workstream C — Market Data Reporting & Query Layer

### Objective
Make the collected market data **inspectable**, **auditable**, and **human-legible**.

This is explicitly *not* a dashboarding project.

### Deliverables

#### 5.1 Coverage inspection API
Introduce read-only helpers such as:
- product coverage summary
- per-contract OHLCV coverage
- missing / incomplete ranges

Likely locations:
```
mxm/v1/marketdata/reports/
mxm/v1/marketdata/query/
```

#### 5.2 Coverage reports
Produce scripts that output:
- Table summaries (terminal-friendly)
- Optional JSON / CSV exports

Example:
- “Which contracts for product X are complete?”
- “What date ranges are missing for product Y?”

#### 5.3 Refdata & definitions reports
Add simple reports for:
- instrument definitions (current snapshot)
- definition → mapping completeness
- vendor vs internal universe diffs

## 6. Workstream D — Deployment & Operations

### Objective
Make market data ingestion **boring, repeatable, and scheduled**.

### Deliverables

#### 6.1 Monolith deployment
- Clone MXM repos to monolith
- Set up:
  - Python environment
  - Secrets
  - Database paths
- Ensure parity with development layout

#### 6.2 Scheduled execution
- Create a daily job that runs:
  ```
  product_universe.py --mode update
  ```
- Enforce:
  - conservative cost caps
  - logging
  - failure visibility

#### 6.3 Data synchronisation
Define a **clear policy** for syncing:
- Market data
- SQLite metadata
- Parquet artifacts

Between:
- monolith (authoritative)
- bridge (development / inspection)

This may be one-way at first.

## 7. Workstream E — Phase 3 Readiness Checkpoint

### Objective
Formally close Phase 2 before entering synthetic assets and strategy work.

### Exit Criteria

Phase 2 is considered complete when:

- Multiple products can be ingested end-to-end
- Daily update runs are operational on monolith
- Coverage can be queried and explained
- Data quality issues are visible, not implicit
- No ad-hoc ingestion scripts remain in use

Only then does it make sense to proceed to:

**Phase 3 — Synthetic Assets & Portfolio Construction**

## 8. Explicit Non-Goals (Deferred)

- Automated vendor product discovery
- GUI dashboards
- Parallel ingestion
- Strategy logic
- Signal generation
- Portfolio backtesting

These belong to later phases.

## 9. Closing Note

The Phase 2 tail is about **turning a working system into an operational one**.

Nothing here is intellectually novel — that is the point.

Phase 3 will only be productive if Phase 2 ends cleanly, visibly, and boringly.
