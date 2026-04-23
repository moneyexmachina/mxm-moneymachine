# session_36e_plan.md

## Session 36e — Prefect Operationalisation and First Real-World Deployment

### Objective

Move from **library-level integration** (Session 36d) to **operational execution**:

> **Stand up a working Prefect-backed runtime on bridge + monolith, and execute a real MXM flow as a deployed job with parallelism across products.**

This session establishes Prefect as the **actual execution substrate** for MXM v1.

## Context

After Session 36d:

- Prefect is integrated as execution engine
- MXM owns only:
  - `SemanticEvent`
  - `ExecutionContext`
- All redundant execution reporting has been removed

However:

> Prefect is still being used as a **local function wrapper**, not as an **orchestration system**

## Core Shift in This Session

We now transition from:

> Prefect as a library dependency

to:

> Prefect as an operational system (server + worker + deployments)

## Target Architecture (v1)

### Machines

#### bridge (MacBook)
- Development environment
- Local Prefect server (optional, lightweight)
- CLI usage
- Flow compilation and testing

#### monolith (Linux server)
- Primary execution environment
- Prefect self-hosted server
- Prefect worker(s)
- Execution of MXM deployments

### Responsibility Split

#### Prefect owns:
- flow execution
- task execution
- retries
- scheduling (later)
- run state persistence
- logs
- orchestration lifecycle

#### MXM owns:
- semantic events
- domain-level meaning
- deterministic data processing logic

## Real-World Test Flow

We introduce the first **non-demo flow**:

### Structure

Per product:

```
instrument_definition_update
    → instrument_definition_mappings_update
```

Across products:

```
parallel execution over product universe
```

### Properties

- Sequential within product
- Parallel across products
- Minimal logic, but real data access
- Emits `SemanticEvent` at key steps

## Implementation Plan

### Step 1 — Prefect Installation and Configuration

#### On both bridge and monolith:

- ensure Prefect is installed in the `mxm-pipeline` environment
- verify CLI:

```bash
prefect version
```

#### Define profiles (optional but recommended):

- local/dev profile (bridge)
- server profile (monolith)

### Step 2 — Start Prefect Server

#### On monolith:

Run:

```bash
prefect server start
```

This starts:

- REST API
- orchestration backend
- SQLite DB (default)

Verify:

- UI accessible (default: http://localhost:4200)
- API responding

### Step 3 — Create Work Pool

On monolith:

```bash
prefect work-pool create mxm-pool
```

This defines:

- execution target for deployments

### Step 4 — Start Worker

On monolith:

```bash
prefect worker start -p mxm-pool
```

This process:

- polls for scheduled/deployed runs
- executes flows

### Step 5 — Adapt mxm-pipeline for Deployment

Extend Prefect adapter usage:

- allow flows to be:
  - executed locally (current)
  - deployed via Prefect

Key requirement:

> expose a callable flow function compatible with Prefect deployments

### Step 6 — Define First Deployment

For test flow:

- create deployment:
  - name: `instrument-update`
  - work pool: `mxm-pool`
  - parameters:
    - product universe
    - optional date/as_of

Deployment can be created via:

- CLI
- or programmatically (preferred long-term)

### Step 7 — Execute Deployment

Trigger run:

```bash
prefect deployment run instrument-update
```

Verify:

- worker picks up run
- tasks execute
- retries (if any) behave correctly
- Prefect UI shows:
  - flow run
  - task runs
  - logs

### Step 8 — Integrate Semantic Events

Inside task functions:

- emit events such as:

```python
execution_context.emit_semantic_event(
    event_type="materialized",
    domain_key=f"instrument_definition.{product}",
    payload={...},
)
```

Verify:

- events persisted in SQLite via `SemanticEventsStore`
- IDs (`flow_run_id`, `task_run_id`) populated

### Step 9 — Validate End-to-End Behaviour

Confirm:

#### Prefect side:
- flow runs visible in UI
- task runs visible
- retries/logs correct

#### MXM side:
- semantic events written
- correct domain keys
- timestamps valid
- payloads correct

## Non-Goals

Do **not**:

- build full deployment abstraction layer
- implement scheduling (cron, intervals)
- introduce cloud execution
- redesign CLI
- implement query/analysis layer for Prefect data

## Risks and Watchpoints

### 1. Environment mismatch
- bridge vs monolith differences
- Python environment inconsistencies

### 2. Prefect API disabled
- must ensure `PREFECT_API_ENABLE != false` in operational mode

### 3. Worker connectivity
- worker must connect to correct server/profile

### 4. Over-complication
- keep deployment minimal
- avoid premature abstraction

## Success Criteria

At the end of Session 36e:

- Prefect server running on monolith
- Worker running and connected to pool
- Deployment created and runnable
- Real-world flow executes across products
- Parallelism achieved at product level
- Semantic events emitted and persisted
- Prefect UI shows operational state

## Outcome

This session establishes:

> **MXM-pipeline as a deployable, orchestrated system, not just a library.**

It bridges the gap between:

- architecture (Sessions 30–36d)
- and real execution of a living system

## Next Steps (Beyond 36e)

- Add scheduling (daily runs)
- Expand semantic event taxonomy
- Extend flows to full market data pipeline
- Introduce monitoring/alerting
- Build query interfaces for:
  - semantic events
  - Prefect operational data

## Closing Note

Session 36e is the first step where:

> **The Money Machine becomes a running system, not just a designed one.**
