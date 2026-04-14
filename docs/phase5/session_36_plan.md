# session_36_plan.md

## Session 36 — First Deployed Runtime: 5 Products × 2 Jobs DAG

### Summary

Session 35 resolved the execution semantics of MXM V1:

- dataset logic now lives in dataset-local modules
- named jobs exist above the dataset logic
- a unified `mxm` CLI exists as the canonical invocation surface
- the distinction between jobs, CLI, and orchestration is now clear

Session 36 moves to the next layer:

> **define and implement the first real deployed runtime for MXM V1**

The scope is intentionally minimal but operationally meaningful:

- 5 products
- 2 atomic jobs per product
- sequencing within each product
- parallelism across products
- deployed on `monolith`
- producing logs, outputs, and run status

This is the first runtime graph that turns MXM V1 from a manually invoked toolset into a **living system**.

## Core Objective

> Build and validate the first deployed runtime for MXM V1 using a 5-product × 2-job DAG, and use it to settle the deployment mechanism for V1.

## Runtime Scope

### Products

A current universe of 5 products.

### Jobs per product

1. `instrument-definitions update`
2. `instrument-definition-mappings rebuild`

### Execution topology

For each product:

```text
instrument-definitions update
    ↓
instrument-definition-mappings rebuild
```

Across products:

- products are independent
- product lanes may be run in parallel
- sequencing must hold within each lane

This yields:

- 10 total job executions
- 5 parallel lanes
- 2 sequential jobs per lane

## Why This Scope Is Correct

This runtime slice is rich enough to answer the important questions without dragging in the full marketdata stack.

It already includes:

- a real vendor-facing job (`instrument_definitions`)
- a downstream derived job (`instrument_definition_mappings`)
- an explicit dependency edge
- shared storage
- meaningful opportunities for parallelism
- vendor limits and operational concerns

It is therefore sufficient to decide:

- whether MXM V1 should use `mxm-pipeline`
- how deployment should actually work
- how concurrency and retries should be handled
- how runtime reporting should be captured

## Main Questions for Session 36

### 1. Deployment Mechanism

We must decide whether the first deployed runtime should be implemented via:

#### Option A — direct Python runtime runner
A custom deployment runner inside MXM V1.

#### Option B — `mxm-pipeline`
Reuse the existing task/pipeline framework, likely already close to what is needed.

#### Option C — thin host-level scheduling only
Use shell/systemd/cron chains without an explicit runtime graph framework.

The working assumption is:

> `mxm-pipeline` is likely the most promising candidate, but must be assessed explicitly against current Session 36 needs.

### 2. Parallelism

We want parallelism across products.

However, we must consider:

- SQLite concurrency
- file write contention
- Databento request limits
- max concurrent streaming requests
- whether back-pressure / worker-count control is needed

We therefore need a clear initial policy for:

- concurrency width
- failure isolation
- retry handling
- resource limits

### 3. Runtime Reporting

The runtime must produce operationally useful outputs.

At minimum:

- per-task success/failure
- logs
- timing
- overall run summary

This is operational reporting, not semantic provenance.

## Architectural Assumptions

### Settled from Session 35

- jobs are the primary executable unit
- CLI is the canonical invocation surface
- orchestration is external to jobs
- semantic provenance is future work
- attempts/logs are operational provenance

### Applied in Session 36

The runtime must invoke the settled jobs/CLI surface, not bypass it.

This means deployment should be built on top of:

```text
mxm marketdata instrument-definitions update ...
mxm marketdata instrument-definition-mappings rebuild ...
```

or the equivalent direct job call surface, if we explicitly decide to use Python invocation instead of CLI invocation.

This choice must be made consciously.

## Work Plan

### 1. Decide the Deployment Mechanism

#### Goal

Determine how the runtime graph should actually be executed.

#### Tasks

- inspect current `mxm-pipeline` capabilities
- compare it against the exact needs of:
  - 5 product lanes
  - 2-job sequence
  - controlled parallelism
  - run reporting
- decide whether to:
  - use `mxm-pipeline`
  - build a thin custom runtime runner
  - use an even thinner host-level chain

#### Success criterion

A clear decision:

> what execution framework is being used for the first deployed runtime

### 2. Define the Runtime Graph Explicitly

#### Goal

Formalize the first runtime DAG.

#### Graph

For each product `P`:

```text
update_instrument_definitions_for_product(P)
    ↓
rebuild_instrument_definition_mappings_for_product(P)
```

Across products:

```text
lane(P1) ∥ lane(P2) ∥ lane(P3) ∥ lane(P4) ∥ lane(P5)
```

#### Deliverable

An explicit graph specification in code or runtime config.

### 3. Define Concurrency Policy

#### Goal

Set a safe and sensible first parallelism policy.

#### Topics

- maximum concurrent products
- Databento stream concurrency
- SQLite/file contention risk
- whether product lanes are fully isolated enough
- whether concurrency should initially be capped below 5

#### Likely initial policy

- preserve sequential execution within each product
- begin with limited cross-product concurrency
- increase only after observing runtime behavior

#### Deliverable

A written and implemented concurrency rule.

### 4. Implement the First Runtime

#### Goal

Create the actual executable runtime.

#### Requirements

- invokes the 5×2 graph
- captures logs/status
- records task outcomes
- returns clear overall success/failure

#### Possible surfaces

- Python module
- MXM runtime CLI command
- `mxm-pipeline` graph
- scheduler entrypoint

#### Deliverable

A first executable runtime command.

### 5. Deploy on `monolith`

#### Goal

Run the runtime in the actual target environment.

#### Tasks

- install/configure entrypoint on `monolith`
- verify `.venv` / CLI execution path
- ensure secrets access works
- ensure logs are written/readable
- run end-to-end against real data

#### Deliverable

A real run on `monolith`.

### 6. Define Logging and Run Output

#### Goal

Make the runtime inspectable.

#### Minimum outputs

- start/end time
- per-task status
- per-product lane status
- overall status
- stdout/stderr or structured logs

#### Optional later

- email notification
- daily summary
- richer run artifact

#### Deliverable

A clear run-reporting scheme for the deployed runtime.

## Key Decision Criteria

The chosen deployment mechanism should satisfy:

### Correctness
- job order preserved
- dependencies respected

### Operational clarity
- failures visible
- retries understandable
- logs accessible

### Simplicity
- minimal moving parts
- no unnecessary infrastructure burden

### Extensibility
- easy to extend from 2 jobs to full marketdata stack
- easy to increase product universe later

## Non-Goals

Session 36 does **not** aim to:

- fully formalize semantic event ledgers
- solve general JSON representation policy
- fully migrate all remaining dataset jobs
- solve all concurrency for all future layers
- deploy the complete marketdata stack
- implement full email/alerting system
- containerize MXM V1

## Risks / Open Concerns

### 1. `mxm-pipeline` fit
It may already be suitable, but needs explicit validation.

### 2. Shared storage contention
Even simple cross-product parallelism may expose SQLite or filesystem issues.

### 3. Vendor request limits
Databento stream concurrency must be respected.

### 4. False complexity
There is a danger of overbuilding deployment infrastructure before the first runtime is proven.

## Success Criteria

Session 36 is successful if:

1. the deployment mechanism for MXM V1 is explicitly chosen
2. the 5-product × 2-job runtime graph is implemented
3. parallelism policy is explicitly defined
4. the runtime runs successfully on `monolith`
5. logs / run status are inspectable
6. the path to extending the graph to the remaining marketdata jobs is clear

## Extension Path After Session 36

Once the 5×2 runtime works, extension should be mechanical:

Per product:

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

with:

- additional parallelism opportunities by product
- possible later parallelism by contract where sensible
- explicit runtime control at the scheduler layer

## One-Sentence Definition

> Session 36 establishes the first deployed MXM V1 runtime by implementing and running a 5-product × 2-job DAG on `monolith`, and uses that slice to settle the deployment mechanism for the system.
