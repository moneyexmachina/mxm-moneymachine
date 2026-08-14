# Prefect Task Boundaries

## Purpose

This document defines how Money Ex Machina chooses Prefect task boundaries.

The purpose is to ensure that Prefect execution semantics remain compatible with:

- MXM semantic correctness;
- safe retries;
- durable state transitions;
- semantic lineage;
- parallel execution;
- future execution backends.

The governing semantic model is defined in:

```text
docs/concepts/semantic-state-protocol.md
```

The governing Prefect execution model is defined in:

```text
docs/concepts/prefect-runtime-model.md
```

# 1. Core Principle

A Prefect task boundary is an operational retry boundary.

Therefore:

> A mutating MXM operation may be exposed to Prefect automatic retry only when that operation has established safe re-entry semantics.

MXM semantic correctness takes precedence over orchestration granularity.

Prefect must not be used to create task decomposition that weakens an application's semantic transaction boundaries.

# 2. Semantic Commit Units

A semantic commit unit is an MXM operation that owns a coherent semantic transition.

It may:

```text
resolve semantic inputs
→ inspect existing durable state
→ determine required work
→ perform side effects
→ validate resulting state
→ commit durable semantic state
→ record lineage
→ return a semantic reference or result
```

The semantic commit unit owns the correctness of that transition.

It is therefore the natural initial Prefect retry boundary.

Conceptually:

```text
one semantic commit unit
≈
one Prefect retry unit
```

This is a default, not a requirement that every semantic operation must remain permanently monolithic.

# 3. Safe Re-Entry

Prefect may retry a task after:

- process failure;
- worker loss;
- transient network failure;
- timeout;
- infrastructure interruption;
- other operational failure.

A retry may occur after some application side effects have already happened.

The application must therefore determine correct behaviour from its own durable semantic state.

On re-entry, it may:

```text
discover equivalent accepted state
→ return it
```

or:

```text
discover recoverable partial state
→ reconcile or resume
```

or:

```text
discover no relevant state
→ execute normally
```

The application must not depend on:

```text
Prefect retry number
previous task-run state
previous worker
previous process identity
```

to determine semantic correctness.

Where safe re-entry has not been established:

```text
automatic retry should not be enabled
```

until the semantic operation provides the required guarantee.

# 4. Valid Task Boundaries

Task boundaries are appropriate where the enclosed operation is independently safe under Prefect execution semantics.

## Pure operations

Examples:

- validation;
- normalization;
- deterministic calculation;
- parameter expansion.

These operations have no durable side effects and may be retried freely.

## Read-only operations

Examples:

- semantic-state discovery;
- configuration inspection;
- metadata lookup;
- cost estimation;
- coverage inspection.

These operations do not mutate authoritative state.

## Independently retry-safe semantic operations

Examples may include:

- building one idempotent reference-data state;
- ingesting one independently owned market-data unit;
- publishing one atomic dataset partition;
- constructing one independently identifiable signal state.

These operations own their semantic commit and can safely tolerate repeated invocation.

## Reporting and observability

Examples:

- producing Prefect artifacts;
- rendering reports;
- recording metrics;
- logging returned semantic references.

These may normally be separate tasks where doing so provides operational value.

# 5. Invalid Task Boundaries

The following decompositions are unsafe unless each resulting operation has its own independent semantic guarantees.

## Splitting fetch from semantic commit

Unsafe pattern:

```text
task A
    fetch external data

task B
    write dataset

task C
    advance semantic metadata
```

A retry between these steps may create inconsistency between:

- retrieved observations;
- persisted data;
- semantic state.

If these actions form one semantic transaction, they should remain inside one retry-safe semantic operation.

## Splitting state determination from mutation

Unsafe pattern:

```text
task A
    determine missing work

task B
    perform mutation based on stale determination
```

unless task B independently revalidates the semantic state it depends upon.

Semantic decisions must remain correct even if state changes between tasks.

## Splitting validation from acceptance

If validation determines whether a produced state is semantically usable, it must be part of the producing operation's acceptance contract.

A downstream Prefect task must not turn an otherwise unaccepted state into accepted state merely because the preceding task completed.

## Shared mutable ownership

Independent tasks must not concurrently mutate the same semantic ownership unit unless the underlying MXM application provides an explicit concurrency and consistency mechanism.

Prefect concurrency configuration may reduce contention operationally.

It must not be the sole correctness mechanism.

# 6. Semantic Dependencies Versus Execution Dependencies

MXM distinguishes between:

```text
semantic dependency
```

and:

```text
Prefect execution dependency
```

A semantic dependency is a durable domain relationship.

For example:

```text
SignalState S42
    depends on
MarketDataState M17
```

A Prefect dependency means only:

```text
run task B after task A
```

The execution dependency is an execution plan.

It is not semantic proof.

Therefore:

> Task ordering determines when a downstream operation is attempted.

> Semantic state determines whether its prerequisites are actually satisfied.

# 7. Passing Semantic References Between Tasks

Prefect may transport semantic references between tasks.

Example:

```text
R = build_refdata()

I = update_instrument_definitions(
    refdata=R
)
```

Here:

```text
R
```

is a reference to durable MXM semantic state.

Passing the reference provides:

- explicit intended dependency;
- clear operational data flow;
- convenient alignment between execution and semantic lineage.

However, the downstream application remains responsible for:

```text
resolve reference
→ verify existence
→ verify acceptance
→ verify compatibility
→ perform semantic operation
```

A reference does not become authoritative merely because Prefect supplied it.

# 8. Task Completion Is Not Semantic Acceptance

A successful Prefect task means:

```text
the Python operation completed according to Prefect execution semantics
```

It does not by itself mean:

```text
the resulting semantic state is accepted for downstream use
```

Semantic acceptance belongs to the MXM application.

Where an operation produces an accepted semantic result, the preferred pattern is:

```text
perform work
→ validate
→ commit / accept semantic state
→ return semantic reference
→ task completes
```

The returned reference then identifies the state that downstream operations may resolve and consume.

# 9. Retry Semantics and Semantic References

If a task is retried, the same semantic request should normally remain in effect.

For example:

```text
Task B(refdata=R42)
```

fails operationally and is retried as:

```text
Task B(refdata=R42)
```

The retry does not create new semantic meaning merely because Prefect has started another task attempt.

The application inspects its own semantic state and determines whether:

- the requested result already exists;
- partial state must be reconciled;
- work must be repeated;
- a semantic failure should be returned.

Prefect retry state is therefore operational information only.

# 10. Parallelism

Parallelism should align with semantic ownership boundaries.

The preferred alignment is:

```text
parallelism unit
=
retry unit
=
independent semantic ownership unit
```

Examples may include:

```text
one product
one independent dataset partition
one independently committed time range
one independent model calculation
```

This alignment reduces:

- lock contention;
- ambiguous partial state;
- cross-task rollback requirements;
- duplicate ownership;
- retry complexity.

Task-level parallelism should be introduced only where the semantic ownership model makes concurrent execution safe.

# 11. Concurrency Controls

Prefect may provide operational concurrency controls.

These may be useful for:

- vendor rate limits;
- host resource limits;
- reducing duplicate work;
- preventing excessive simultaneous database activity.

Such controls are operational protections.

They must not be the sole enforcement of semantic invariants.

If concurrent execution could corrupt semantic state, the MXM application itself must provide the required:

- idempotency;
- uniqueness;
- locking;
- transaction isolation;
- ownership discipline;
- conflict detection.

# 12. External Side Effects

Operations involving external side effects require particular care.

Examples include:

- vendor requests with financial cost;
- externally published files;
- notifications;
- broker orders;
- other non-transactional external systems.

A Prefect retry may occur after the external side effect happened but before the application received confirmation.

The semantic operation must therefore provide an explicit safe re-entry or reconciliation mechanism before automatic retries are enabled.

For trading execution, stable semantic identities such as an order-intent identity should determine whether an external action has already occurred.

Prefect retry identity must not be used as the semantic idempotency key.

# 13. Flow Boundaries

A Prefect flow may coordinate multiple semantic operations.

For example:

```text
build refdata
    ↓
update instrument definitions
    ↓
update instrument mappings
    ↓
update market data
```

Each operation remains responsible for its own semantic correctness.

The flow owns:

- execution ordering;
- scheduling;
- parallelism;
- transport of semantic references;
- operational observability.

The flow does not own:

- semantic identity;
- acceptance;
- lineage authority;
- domain idempotency;
- durable consistency.

A larger flow therefore represents:

```text
an execution plan for producing semantic state
```

rather than one giant semantic transaction.

# 14. Existing Application Boundaries

Existing MXM application operations should be reused as Prefect task boundaries where they already provide appropriate semantic guarantees.

For example:

```text
mxm-refdata
    RefData.build()
```

already provides safe repeated non-destructive materialisation semantics.

It can therefore form a valid orchestration boundary without decomposing reference-data generation or persistence into smaller Prefect tasks.

Likewise, existing market-data ingest operations should initially remain intact where they already own:

- state discovery;
- vendor interaction;
- persistence;
- lifecycle updates;
- semantic metadata;
- report construction.

Task decomposition should follow only when independently retry-safe sub-units have been demonstrated.

# 15. Execution Metadata

Prefect owns:

```text
flow-run ID
task-run ID
deployment ID
worker identity
work pool
retry number
execution state
```

These values do not need to be propagated into MXM semantic state in order to make semantic operations correct.

The preferred correlation model is instead:

```text
MXM semantic operation
    ↓
semantic reference / result identity
    ↓
returned to Prefect
    ↓
Prefect logs or artifacts record the semantic identity
```

This preserves correlation between the operational and semantic ledgers without coupling semantic behaviour to execution history.

# 16. Refactoring Task Boundaries

Future decomposition is encouraged where it improves:

- observability;
- retry isolation;
- scaling;
- parallelism;
- operational debugging;
- latency;
- resource utilisation.

But decomposition must proceed from demonstrated semantic boundaries.

The preferred sequence is:

```text
existing coherent semantic operation
        ↓
identify independently owned sub-operation
        ↓
establish independent safe re-entry
        ↓
prove semantic correctness
        ↓
introduce separate Prefect task
```

Not:

```text
split operation into convenient execution steps
        ↓
attempt to repair semantic consistency afterward
```

# Design Tests

Before creating a mutating Prefect task boundary, ask:

## Retry test

```text
If Prefect invokes this operation twice,
does MXM determine correct behaviour from durable semantic state?
```

If not, the boundary is not ready for automatic retry.

## Crash test

```text
If the process dies after some side effects,
can the operation safely determine what happened on re-entry?
```

## Ownership test

```text
Does this task own an independent semantic state transition?
```

## Concurrency test

```text
Can another execution operate concurrently without corrupting this state?
```

## Orchestrator-independence test

```text
Would the operation retain the same meaning and correctness
if invoked through CLI or another orchestrator?
```

## Semantic-input test

```text
Are required upstream semantic states explicit or independently discoverable?
```

A task must not rely solely on preceding task completion as proof of semantic validity.

# Core Invariants

```text
A Prefect task boundary is a retry boundary.

Semantic correctness is owned by MXM.

Automatic retry requires established safe re-entry.

Retry behaviour is derived from durable semantic state,
not Prefect retry history.

A semantic commit unit must not be split across unsafe retry boundaries.

Prefect execution dependencies are not semantic dependencies.

Prefect may transport semantic references between tasks.

Downstream applications resolve and validate those references independently.

Task completion is not semantic acceptance.

Operational concurrency controls do not replace semantic consistency guarantees.

Parallel execution should align with independent semantic ownership.

Semantic result identities flow outward to Prefect for correlation;
Prefect execution identities do not determine semantic state.
```

# Summary

Prefect tasks are operational execution units.

MXM semantic operations are correctness units.

The preferred relationship is:

```text
retry-safe semantic operation
        ↓
thin Prefect task
        ↓
Prefect execution / retry / observability
```

Flows may combine many such operations into an execution plan and transport semantic references between them.

The underlying rule remains simple:

```text
Prefect may retry the work.

MXM must know what that means.
```

Task boundaries are therefore chosen from semantic correctness outward, rather than from orchestration convenience inward.
