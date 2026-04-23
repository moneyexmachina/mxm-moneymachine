# session_36d_plan.md

## Session 36d — Runtime Integration with Prefect

### Objective

Define and implement a clean integration between the MXM execution semantics + reporting substrate and the Prefect execution engine.

This session focuses on:

> **Mapping MXM-owned execution semantics onto Prefect runtime mechanics in a controlled and explicit way.**

This is not a generic implementation step, but a **design + integration session**.

## Starting Point

We now have:

### Fully implemented (MXM-owned)

- Execution model:
  - `FlowRun`
  - `TaskRun`
  - `TaskAttempt`
  - `SemanticEvent`

- Reporting infrastructure:
  - SQLite backend
  - stores (state + event ledgers)
  - `ReportingRecorder`
  - `ExecutionContext`
  - `ReportingSemanticEventSink`

- Supporting utilities:
  - canonical timestamps (`mxm-types`)
  - ID generation
  - serde layer

### Existing runtime

- Prefect-based execution via `prefect_adapter.py`
- Topological execution logic already implemented
- Task wrapping via `@task`
- Flow wrapping via `@flow`

But:

> **No integration exists yet between runtime execution and reporting.**

## Architectural Target

Adopt the following stance:

> **MXM owns execution semantics and reporting.  
> Prefect is used as the execution engine.**

Implications:

- MXM defines:
  - run/attempt lifecycle
  - reporting
  - semantic events
- Prefect provides:
  - task execution
  - scheduling
  - retries (if usable)
  - deployment (later)

## Implementation Plan

### Step 1 — Define Reporting Runtime Bootstrap

Inside execution:

- construct:
  - `ReportingLayout`
  - `SQLiteBackend`
  - `ReportingStore`
  - `ReportingRecorder`

Decision needed:

- reporting root path (temporary default acceptable)

### Step 2 — FlowRun Lifecycle Integration

In `_mxm_run`:

- generate `flow_run_id`
- call:
  - `record_flow_run_created`
  - `record_flow_run_started`
- wrap execution in try/except:
  - on success → `SUCCEEDED`
  - on failure → `FAILED`

### Step 3 — TaskRun Lifecycle Integration

For each task:

- create `task_run_id`
- call:
  - `record_task_run_created`
- update status:
  - RUNNING when first attempt starts
  - SUCCEEDED / FAILED at end

### Step 4 — TaskAttempt Lifecycle Integration

For each attempt:

- generate `task_attempt_id`
- increment attempt counter
- call:
  - `record_task_attempt_started`

On success:
- `record_task_attempt_succeeded`

On failure:
- `record_task_attempt_failed`

### Step 5 — ExecutionContext Wiring

For each attempt:

- construct `ExecutionContext`:
  - flow_run_id
  - task_run_id
  - task_attempt_id
  - attempt_number
  - logger
  - `ReportingSemanticEventSink`
  - metadata

- inject into task function if accepted

### Step 6 — SemanticEvent Integration

- ensure all emitted events via context are:
  - routed through sink
  - persisted via recorder

### Step 7 — Retry Handling Decision

Evaluate:

- whether Prefect retry behavior is sufficient

If not:

- introduce explicit retry loop around task invocation

Goal:

> ensure `TaskAttempt` semantics are **deterministic and observable**

### Step 8 — Minimal End-to-End Test

Add test:

- run a simple flow
- assert:
  - correct results
  - FlowRun persisted
  - TaskRuns persisted
  - TaskAttempts persisted
  - SemanticEvents persisted

## Non-Goals for This Session

Do **not**:

- implement multi-engine abstraction
- introduce Dagster/Airflow support
- build query/analysis layer for reporting
- implement parallel execution
- redesign CLI/API

## Risks and Watchpoints

### 1. Prefect Retry Opacity
Prefect retries may not expose enough detail → may require MXM retry loop

### 2. Context Injection Fragility
Function signature inspection must remain simple and predictable

### 3. Over-coupling to Prefect
Avoid leaking Prefect concepts into MXM core models

### 4. Reporting Performance
Initial implementation is correctness-first; optimisation later

## Success Criteria

At the end of Session 36d:

- A flow executed via Prefect produces:
  - full MXM reporting trace
- ExecutionContext is available inside tasks
- Semantic events persist correctly
- TaskAttempt semantics are clearly defined and observable
- Tests cover the full execution → reporting path

## Outcome

This session will produce:

> A fully integrated execution + reporting system, with Prefect as the runtime engine and MXM as the semantic authority.

This completes the **execution layer of mxm-pipeline v1**.
