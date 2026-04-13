# session_35_plan.md

## Session 35 — Establishing the MXM Marketdata Runtime System

## Summary

Session 35 transitions the marketdata subsystem from a collection of runnable scripts into a **living runtime system**.

The goal is not to extend data logic, but to:

- define a **clean execution model**
- establish **stable job boundaries**
- introduce a **canonical invocation layer**
- and deploy a **scheduled runtime on monolith**

This session formalizes the separation between:

- **domain orchestration (Python)**
- **invocation (CLI / run functions)**
- **deployment/runtime (scheduler)**

## Core Objective

> Establish a clean execution model (`run` functions + CLI adapters + scheduler) and use it to run the full marketdata pipeline as a continuously operating system.

## Architectural Model

### Layer 1 — Domain (Canonical)

- Dataset orchestrators
- Product/meta orchestrators
- Dataset semantics and policies
- Attempt ledgers
- Structured reports and health logic

This layer is the **single source of truth**.

### Layer 2 — Invocation (Adapters)

- `ops.<dataset>.run(...)` functions
- CLI scripts (thin wrappers)
- Future `mxm` CLI surface

This layer provides **stable entrypoints** into the domain logic.

### Layer 3 — Deployment / Runtime

- Scheduler (native; Dagster optional later)
- Job sequencing
- Scheduling and retries
- Operational logging

This layer keeps the system **alive over time**.

## Key Design Rule

> Domain orchestration lives in Python.  
> The scheduler composes only coarse job entrypoints.

## Execution Unit

The canonical executable unit is:

```
ops.<dataset>.run(...)
```

Each such function:

- encapsulates dataset orchestration
- owns its attempt ledger
- returns a structured report
- is callable from:
  - CLI
  - scheduler
  - Python

## Scope of Session 35

### In Scope

- Introduce `run(...)` functions for dataset ops
- Refactor scripts into CLI adapters
- Add `daily_mark` ops entrypoint
- Define marketdata runtime job chain
- Implement initial scheduling on `monolith`
- Execute first full end-to-end runtime

### Out of Scope

- Containerisation
- Advanced parallelisation across products
- Distributed execution
- Full DAG tooling integration (Dagster optional, not required)
- Major refactors of dataset internals

## Work Plan

### 1. Introduce `run(...)` Functions

#### Objective

Establish canonical callable entrypoints for each dataset.

#### Tasks

For each dataset:

- `statistics_1d`
- `daily_stats`
- `daily_mark` (new)
- (optionally) `ohlcv_1d`
- `instrument_definitions`
- `instrument_definition_mappings`

Implement:

```
mxm.v1.marketdata.ops.<dataset>.run(...)
```

#### Requirements

- Calls existing orchestrator logic
- Produces structured report
- Owns attempt ledger
- Idempotent behavior

### 2. Add `daily_mark` Ops Entry Point

#### Objective

Promote `daily_mark` to a first-class runtime dataset.

#### Tasks

- Create `ops.daily_mark.run(...)`
- Replace current smoke script with proper ops entrypoint
- Ensure:
  - full-history build support
  - incremental update support
  - correct mark policy application

#### Output

- `daily_mark` becomes part of runtime job chain

### 3. Refactor Scripts into CLI Adapters

#### Objective

Turn scripts into thin invocation layers.

#### Tasks

For each script in:

```
scripts/marketdata/ops/
```

Refactor to:

- parse arguments
- call corresponding `run(...)`
- print/log report

#### Rule

No domain logic remains in scripts.

### 4. Define Marketdata Job Chain

#### Objective

Make runtime sequencing explicit.

#### Logical per-product chain

1. instrument_definitions (idempotent update)
2. instrument_definition_mappings (idempotent update)
3. ohlcv_1d (optional)
4. statistics_1d (vendor ingestion)
5. daily_stats (derived)
6. daily_mark (authoritative marks)
7. inspect / validate

#### Note

Cadence distinction:

- Core daily:
  - statistics_1d
  - daily_stats
  - daily_mark

- Maintenance:
  - instrument_definitions
  - mappings

Initial implementation may run all sequentially.

### 5. Establish Runtime Scheduling

#### Objective

Run the system continuously on `monolith`.

#### Initial approach

- Native scheduling (e.g. simple loop, cron, or systemd)
- Sequential execution of job chain

#### Requirements

- Clear job ordering
- Logging of each job invocation
- Failure visibility
- Manual rerun capability

#### Optional (not required)

- Introduce Dagster as thin orchestration layer

### 6. First End-to-End Execution

#### Objective

Validate the runtime system.

#### Tasks

- Run full job chain for one product
- Verify:
  - datasets updated
  - no missing coverage
  - daily_mark produced correctly
  - reports generated

#### Then

- Expand to multiple products (sequentially)

### 7. Inspection and Health Surface

#### Objective

Ensure observability.

#### Tasks

- Use `marketdata_inspect.py` as base
- Confirm:
  - dataset completeness checks
  - missing data detection
  - reporting surface usable

## Parallelisation (Deferred)

- Future work: parallel execution across products
- Constraint: filesystem + SQLite contention
- Not required for Session 35 completion

## Containerisation Policy

- Not part of Session 35
- System must be container-ready
- Deployment remains native on `monolith`

## Deliverables

### Code

- `ops.<dataset>.run(...)` functions
- Refactored CLI scripts
- `daily_mark` ops entrypoint

### Runtime

- Defined job chain
- Working scheduler (native)

### Execution

- Successful end-to-end run
- Updated datasets
- Generated reports

## Acceptance Criteria

Session 35 is complete when:

1. Each dataset has a working `run(...)` entrypoint
2. CLI scripts call only `run(...)`
3. `daily_mark` is integrated into runtime
4. A scheduled or repeatable job chain exists
5. Full pipeline runs end-to-end without manual stitching
6. Outputs are inspectable and consistent

## One-Sentence Definition

> Session 35 establishes a clean execution model and uses it to make the marketdata subsystem continuously operational.

