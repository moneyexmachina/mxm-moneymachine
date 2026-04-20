# session_36_plan.md

## Session 36 — MXM Runtime & Execution Model (V1 Implementation)

## Summary

Session 36 establishes the **first deployed runtime for MXM V1**, while simultaneously formalizing and implementing the **execution and reporting model** of the system.

This session incorporates a key architectural refinement:

> **Tasks are the canonical executable unit. There is no separate jobs layer.**

The execution model is now aligned with standard orchestration frameworks, while remaining **fully controlled and owned by MXM via `mxm-pipeline`**.

The goal is to build a **minimal but complete vertical slice**:

- execution model
- runtime reporting
- orchestration DAG
- deployment on `monolith`

## Core Objective

> Build and deploy the first MXM V1 runtime using a 5-product × 2-task DAG, while implementing the canonical execution model based on `FlowRun`, `TaskRun`, and `TaskAttempt`, with domain-level `SemanticEvent`s.

## Final Execution Model (V1)

```text
FlowRun
  TaskRun
    TaskAttempt(s)
    SemanticEvent(s)
```

### Interpretation

- **FlowRun** → orchestration of a full runtime execution
- **TaskRun** → orchestration-level scheduling and dependency resolution
- **TaskAttempt** → actual execution attempt of a task
- **SemanticEvent** → domain-level meaning emitted by tasks

## Architectural Ownership

### `mxm-pipeline` — Execution & Orchestration Substrate

Owns:

- `FlowSpec`, `TaskSpec`
- `FlowRun`, `TaskRun`, `TaskAttempt`
- execution runners (local, parallel, CLI)
- DAG compilation and scheduling
- runtime reporting and persistence
- logging integration and correlation

Defines:

> the **grammar and runtime of execution**

### `mxm-v1` — Domain Task Definitions

Owns:

- concrete `TaskSpec` instances
- concrete `FlowSpec` definitions
- config loading
- dependency construction
- domain logic
- emission of `SemanticEvent`s

Defines:

> the **actual work performed by the system**

### Dataset / Domain Layer — Semantic Meaning

Owns:

- `SemanticEvent` instances
- dataset-local stores
- domain-specific payloads and interpretations

Defines:

> what execution *means*

## Key Architectural Decision

### Tasks are the canonical executable unit

- tasks replace the previous "job" abstraction
- tasks must be executable:
  - standalone (CLI / local)
  - within flows
- no duplication of execution semantics across surfaces

### Design Rule

```text
Task = canonical executable
Flow = composition of tasks
```

Standalone execution is equivalent to:

```text
FlowRun with a single TaskRun
```

## Runtime Scope (V1)

### Products

5 products (current universe)

### Tasks per product

1. `instrument-definitions update`
2. `instrument-definition-mappings rebuild`

### Execution topology

```text
update
  ↓
rebuild
```

Across products:

```text
lane(P1) ∥ lane(P2) ∥ lane(P3) ∥ lane(P4) ∥ lane(P5)
```

### Result

- 10 TaskRuns
- 5 parallel lanes
- 2 sequential steps per lane

## Execution Model Responsibilities

### FlowRun

- unique run identifier
- start/end timestamps
- overall status
- grouping of TaskRuns

### TaskRun

- task identity
- product / parameters
- orchestration state:
  - pending / running / succeeded / failed / skipped / blocked
- dependency context
- start/end timestamps

### TaskAttempt

- execution attempt for a task
- retry tracking
- start/end timestamps
- status
- error summary
- log references

### SemanticEvent

- domain-level event emitted during execution

Minimal envelope:

```text
event_id
task_attempt_id
event_type
event_ts
dataset_key
payload
```

## Logging vs Structured Reporting

### Structured records (FlowRun / TaskRun / TaskAttempt)

- factual
- queryable
- persistent
- minimal

### SemanticEvents

- domain meaning
- structured but domain-specific

### Logs (stdout / file)

- narrative execution trace
- debugging context
- stack traces
- intermediate state

### Principle

> records say **what happened**  
> semantic events say **what it meant**  
> logs say **how it unfolded**

## Work Plan

### 1. Define Minimal Data Models

Implement:

- `FlowRun`
- `TaskRun`
- `TaskAttempt`
- base `SemanticEvent` envelope

Keep schemas minimal and sufficient for:

- status tracking
- linkage
- inspection

### 2. Implement Persistence

Implement simple persistence (likely SQLite or file-based):

- flow_runs table
- task_runs table
- task_attempts table

Optional:

- semantic_events store (may remain dataset-local initially)

### 3. Upgrade Execution Engine

Extend `mxm-pipeline`:

- support true DAG execution
- enable parallel execution across independent tasks
- preserve sequential dependencies within lanes

### 4. Define TaskSpec Properly

Ensure `TaskSpec` supports:

- config resolution
- dependency construction
- execution function
- context injection
- semantic event emission hooks

### 5. Implement Runners

Provide:

- local sequential runner
- local parallel runner
- CLI entrypoint

All operating on the same `TaskSpec` / `FlowSpec`

### 6. Build Runtime Graph

Define 5×2 DAG using TaskSpecs:

```text
update(P)
  ↓
rebuild(P)
```

### 7. Implement Runtime Reporting

Minimal reporting:

- FlowRun summary
- TaskRun statuses
- failure visibility
- log linkage

### 8. Deploy on `monolith`

- create runtime entrypoint
- run via cron/systemd
- verify environment and secrets
- execute full DAG

## Concurrency Policy (Initial)

- sequential within product
- limited parallelism across products
- start conservatively (e.g. 2–3 concurrent lanes)
- increase after observation

Consider:

- Databento limits
- SQLite contention
- file system write conflicts

## Key Principles

### 1. Standard Model Alignment

MXM uses standard execution concepts:

- flows
- tasks
- runs
- attempts

No exotic execution ontology.

### 2. Separation of Concerns

```text
mxm-pipeline → execution & orchestration
mxm-v1       → task definitions & domain logic
datasets     → semantic meaning
```

### 3. Canonical Execution Boundary

> Task is the single executable abstraction across all surfaces.

### 4. Link, Don’t Merge

- structured records linked via IDs
- logs remain separate
- semantic events remain domain-local

## Non-Goals (V1)

- full semantic event platform
- advanced reporting UI
- multi-backend persistence abstraction
- full dataset refactor of AttemptStores
- distributed execution
- containerization

## Success Criteria

Session 36 is successful if:

1. execution model is implemented (`FlowRun`, `TaskRun`, `TaskAttempt`)
2. 5×2 DAG runs via `mxm-pipeline`
3. parallelism works across products
4. runtime executes successfully on `monolith`
5. failures are visible and inspectable
6. logs and structured records are linked
7. extension to full marketdata stack is straightforward

## Extension Path

After Session 36:

```text
instrument-definitions update
    ↓
instrument-definition-mappings rebuild
    ↓
ohlcv_1d update
statistics_1d update
    ↓        ↓
daily_stats build
    ↓
daily_mark build
```

## One-Sentence Definition

> Session 36 establishes the MXM V1 execution substrate by implementing a standard flow/task/attempt model in `mxm-pipeline`, defining domain tasks in `mxm-v1`, and deploying the first 5-product × 2-task runtime on `monolith`.
