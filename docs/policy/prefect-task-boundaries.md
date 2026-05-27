# Prefect Task Boundaries

## Purpose

This document defines the principles used to determine Prefect flow and task
boundaries inside `mxm-moneymachine`.

The purpose of the policy is to ensure that Prefect orchestration semantics remain
compatible with MXM semantic correctness, idempotency guarantees, and durable dataset
construction behaviour.

# Core Principle

A Prefect task boundary is also a runtime retry boundary.

Task decomposition must therefore preserve the semantic integrity of MXM operations.

MXM semantic correctness takes precedence over orchestration granularity.

# Semantic Commit Units

MXM ingestion and dataset construction logic frequently operates through semantic
commit units.

A semantic commit unit is a unit of work that:

- observes current durable state,
- determines required work,
- performs side effects,
- updates durable state,
- records semantic metadata,
- produces a semantically consistent new system state.

The semantic commit unit is the primary idempotency boundary.

# Idempotent Re-Invocation

MXM ingestion functions are expected to be safe under repeated invocation.

Repeated execution should converge toward the same durable state.

This allows runtime systems such as Prefect to retry executions safely after:

- crashes,
- worker loss,
- container interruption,
- transient network failures,
- partial progress.

The source of durable idempotency is:

```text
MXM stores
MXM semantic metadata
MXM lifecycle logic
```

rather than Prefect runtime state.

# Prefect Retry Semantics

Prefect retries may re-enter a task after partial side effects have already occurred.

For example:

```text
fetch data
write partial results
advance watermark
worker crashes
Prefect retries task
```

MXM semantic logic must therefore safely reconcile partially completed work.

# Task Boundary Rule

A semantic commit unit must not be split across independent Prefect retry boundaries
unless each sub-unit is independently safe and idempotent.

This is the central Prefect task-boundary invariant for MXM.

# Valid Task Boundaries

The following are typically valid task boundaries:

## Pure Validation

Examples:

- argument validation,
- request normalization,
- parameter expansion.

These operations are deterministic and side-effect free.

## Read-Only State Resolution

Examples:

- reading watermarks,
- reading configuration,
- reading dataset metadata,
- estimating request ranges,
- estimating cost.

These operations do not mutate durable state.

## Independently Idempotent Commit Units

Examples:

- ingesting one independently owned partition,
- ingesting one safely replayable window,
- building one atomic dataset partition.

These operations own their durable state transition and can safely tolerate retries.

## Final Reporting

Examples:

- constructing reports,
- publishing artifacts,
- summarizing metrics,
- emitting observability metadata.

# Invalid Task Boundaries

The following patterns are unsafe unless additional transactional guarantees exist.

## Split Fetch and Commit

Example:

```text
task A -> fetch vendor data
task B -> write dataset
task C -> update watermark
```

Retries between these tasks may produce inconsistent semantic state.

## Split State Transition Ownership

Example:

```text
task A -> determine missing work
task B -> partially execute work
task C -> finalize semantic metadata
```

unless each step is independently replay-safe.

## Shared Mutable Partition Ownership

Parallel tasks must not concurrently mutate the same durable ownership unit without
an explicit concurrency and consistency mechanism.

# Current Marketdata Policy

Current MXM marketdata ingest functions are treated as semantic commit units.

For example:

```text
ingest_instrument_definitions(...)
```

currently owns:

- lifecycle checking,
- watermark resolution,
- vendor requests,
- dataset writes,
- semantic metadata updates,
- report construction.

The entire ingest function is therefore currently the correct Prefect task boundary.

# Initial Prefect Integration Strategy

The initial Prefect integration strategy is:

```text
one semantic ingest unit
→ one Prefect task
```

This preserves existing semantic correctness while validating:

- deployment infrastructure,
- worker execution,
- runtime configuration,
- container execution,
- orchestration semantics.

# Future Refactoring Strategy

Future task decomposition is encouraged where it improves:

- observability,
- retry isolation,
- runtime scalability,
- partition parallelism,
- execution latency,
- operational debugging.

However, future decomposition must preserve semantic idempotency guarantees.

The preferred future decomposition strategy is:

```text
one independently owned semantic unit
→ one independently retry-safe task
```

# Parallelism Policy

Parallel execution should align with ownership boundaries.

The intended alignment is:

```text
parallelism unit
=
retry unit
=
ownership unit
=
writable partition
```

This minimizes coordination complexity and preserves deterministic rebuild semantics.

# Prefect Responsibilities

Prefect provides:

- orchestration,
- scheduling,
- retries,
- worker coordination,
- runtime visibility,
- operational metadata.

MXM semantic systems provide:

- durable correctness,
- idempotency,
- dataset semantics,
- lineage,
- lifecycle policy,
- consistency guarantees.

# Operational Metadata

Prefect runtime identifiers should eventually be propagated into MXM semantic metadata.

Examples include:

- flow_run_id,
- task_run_id,
- deployment_id,
- work pool identity.

This supports correlation between:

```text
operational execution state
semantic dataset state
```

# Current Session 44 Position

Session 44 establishes the initial orchestration integration policy:

```text
existing ingest functions remain intact semantic units
→ Prefect wraps them conservatively
→ task decomposition follows later
```

This preserves correctness while establishing the operational runtime substrate for
future MXM flow orchestration.
