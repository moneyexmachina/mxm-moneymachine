# session_35_notes.md

## Session 35 — Runtime Model Clarification & Design Decisions

## Purpose

This document captures the conceptual clarifications and architectural decisions reached during Session 35 discussions.

The goal of the session was to resolve ambiguity around:

- the meaning of "runtime"
- the role of orchestrators, jobs, and schedulers
- the relationship between code, artefacts, and system state
- how to structure MXM V1 as a **living system**

## 1. Core Realisation

The central insight is:

> MXM V1 is a **single logical machine**, whose state is encoded in persisted artefacts and advanced through discrete, idempotent jobs.

This implies:

- there is no single in-memory "system state"
- system state is **constructed by consumers reading artefacts**
- different subsystems may interpret state differently
- state is inherently **partial and contextual**

This ambiguity is **real and unavoidable**, and must be managed, not eliminated.

## 2. Control Plane vs Data Plane

A critical conceptual separation:

### Control Plane (Operational)

- job execution
- scheduling
- retries
- logging
- attempts

### Data Plane (Semantic)

- datasets
- transformations
- outputs
- state transitions

Key principle:

> Execution events (attempts) are NOT equivalent to state changes.

## 3. Operational vs Semantic Provenance

We identified two distinct second-order layers:

### Operational Provenance

- every job execution attempt
- includes retries, failures, partial runs
- stored in **attempt ledgers**

### Semantic Provenance (future)

- meaningful dataset updates
- represents **state transitions**
- independent of how many attempts were required

Example:

- 3 retries → 1 successful dataset update  
→ **3 operational events, 1 semantic event**

Current state:

- MXM V1 implements **operational provenance**
- semantic provenance is **deferred to a later phase**

## 4. The Naming Problem (Resolved)

The original confusion stemmed from misuse of terms:

- "orchestrator"
- "job"
- "runtime"

### Final Definitions

#### Job

A **named unit of work** that:

- runs in a single runtime
- instantiates its dependencies
- performs a state transformation
- records an attempt

Jobs can be:

- **atomic** (single transformation)
- **compound** (sequence of transformations)

Examples:

- `update_instrument_definitions` (atomic)
- `update_product_marketdata` (compound)

#### Orchestration

Reserved for:

> coordination of multiple jobs across runtimes

Includes:

- scheduling
- DAG execution
- retries between jobs
- dependency enforcement

Examples:

- Dagster pipelines
- Airflow DAGs
- systemd chains

#### Scheduler

Responsible for:

- when to run jobs
- triggering execution
- not responsible for domain correctness

## 5. Key Structural Insight

We identified two fundamentally different types of orchestration:

### 1. In-process orchestration

- single Python runtime
- direct function calls
- shared services and state
- current `product_marketdata` implementation

### 2. Cross-process orchestration

- multiple runtimes
- jobs executed independently
- coordination via scheduler/DAG
- future Dagster-like system

### Critical Conclusion

> These two forms of orchestration should NOT coexist for the same logic without a unifying abstraction.

Therefore:

> In MXM V1, we treat in-process orchestration as **compound jobs**, not "orchestration".

## 6. Reframing Existing Code

### Current State

- `marketdata/orchestrators/` contains:
  - both atomic transformations
  - and compound workflows
- CLI scripts combine:
  - job definition
  - dependency wiring
  - execution interface

### Target Model

#### Layer 1 — Domain Logic

- dataset builders
- pure transformation functions

#### Layer 2 — Jobs

- instantiate services/stores
- call domain logic
- define a single unit of work

Located in:

```
datasets/*/jobs.py
marketdata/jobs.py
```

#### Layer 3 — CLI

- user-facing interface
- invokes jobs
- parses arguments

Future:

```
mxm/v1/cli/...
```

#### Layer 4 — Orchestration / Scheduler

- invokes jobs
- manages ordering and dependencies
- may use Dagster or equivalent

## 7. Design Decision: Jobs as Primary Abstraction

We adopt:

> All executable units in MXM V1 are **jobs**.

This includes:

- previously "orchestrators"
- dataset-level operations
- compound workflows

### Implications

- `product_marketdata` becomes a **compound job**
- no need to split it into separate scheduled stages (yet)
- domain dependency logic remains internal

## 8. Why This Works

This approach:

- avoids duplicating dependency logic
- avoids mismatch between in-process and cross-process execution
- preserves correctness
- allows gradual evolution toward full orchestration frameworks

## 9. Relationship to Future mxm-pipeline

The discussion confirms:

> A formal task/pipeline framework is needed — but not for V1.

Future system will include:

- explicit task specifications
- dependency graphs
- execution backends (in-process vs distributed)

Current V1 approach is a **pragmatic stepping stone**.

## 10. Remaining Tensions (Accepted)

We explicitly accept:

### 1. Artefact vs State ambiguity

- artefacts do not define state alone
- interpretation is required

### 2. Version drift

- different code versions may interpret artefacts differently
- not fully solved in V1

### 3. Time dimension (as-of vs event-time)

- no full revision tracking yet
- only current "best view" is maintained

## 11. Immediate Refactor Plan

### 1. Introduce `jobs` modules

For each dataset:

```
datasets/<dataset>/jobs.py
```

And for compound jobs:

```
marketdata/jobs.py
```

### 2. Refactor CLI layer

Move from:

```
scripts/marketdata/ops/*.py
```

to:

```
mxm/v1/cli/marketdata.py
```

CLI becomes:

- thin wrapper
- invokes jobs

### 3. Deprecate "orchestrators" naming

- rename to reflect domain role
- or migrate logic into jobs layer

## 12. Guiding Principles

### 1

> Jobs are the fundamental executable unit.

### 2

> Orchestration is cross-runtime coordination.

### 3

> Execution (attempts) is not state.

### 4

> State is constructed from artefacts.

### 5

> Keep V1 simple; defer general frameworks.

## 13. Final Mental Model

> MXM V1 is a stateful machine driven by jobs, where:
>
> - jobs transform persisted artefacts
> - attempts record execution
> - state is reconstructed from artefacts
> - orchestration is external and optional

## 14. Outcome

This session resolves:

- confusion around runtime meaning
- ambiguity in job vs orchestrator naming
- tension between in-process and cross-process execution
- structure of CLI and execution layers

And establishes a clear path forward for implementation.

