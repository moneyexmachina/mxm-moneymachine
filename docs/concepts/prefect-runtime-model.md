# Prefect Runtime Model

## Purpose

This document defines the Prefect runtime model used by Money Ex Machina.

It describes:

- the role of Prefect within MXM;
- the structure of the orchestration control plane;
- deployments, work pools, workers, flows, and tasks;
- the accepted V1 execution substrate;
- the boundary between Prefect execution state and MXM semantic state;
- how semantic operations and semantic references interact with orchestration.

The semantic meaning and correctness of MXM operations are defined separately by:

```text
docs/concepts/semantic-state-protocol.md
```

This document defines execution and orchestration only.

# 1. Core Principle

Money Ex Machina uses:

```text
one logical Prefect control plane
```

to orchestrate:

```text
many independently composed MXM applications
```

Conceptually:

```text
Money Ex Machina
        │
        └── Prefect control plane
                 │
                 ├── mxm-refdata operations
                 ├── marketdata operations
                 ├── synthetic-asset operations
                 ├── model and signal operations
                 ├── risk and portfolio operations
                 └── future MXM applications
```

Prefect is therefore infrastructure for Money Ex Machina as a whole.

It is not:

```text
one Prefect server per application
```

and the existence of the Prefect Python package inside a particular application
environment does not imply ownership of the Prefect control plane by that
application.

The control-plane infrastructure is currently defined from the
`mxm-moneymachine` repository because that repository contains the operational
integration layer for the Money Machine.

# 2. Responsibilities

The core responsibility split is:

```text
Prefect owns execution.

MXM applications own semantic correctness.
```

Prefect owns:

- schedules;
- deployments;
- execution ordering;
- flow runs;
- task runs;
- work pools;
- workers;
- retries;
- cancellation;
- concurrency controls;
- operational logging;
- execution timing;
- execution state;
- orchestration artifacts and observability.

MXM applications own:

- semantic identity;
- semantic inputs;
- semantic lineage;
- domain validation;
- semantic acceptance;
- discovery of suitable semantic state;
- safe re-entry;
- idempotency;
- durable domain state;
- domain-specific consistency guarantees.

The distinction is fundamental.

```text
Prefect execution success
≠
semantic acceptance
```

and:

```text
Prefect execution failure
≠
proof that no semantic effect occurred
```

Semantic truth is determined by MXM application state.

# 3. Runtime Topology

The accepted V1 topology on `monolith` is:

```text
monolith
│
├── Docker Compose
│   │
│   └── Prefect control plane
│       ├── PostgreSQL
│       ├── Redis
│       ├── Prefect API / UI
│       └── Prefect background services
│
├── Prefect process worker
│   └── polls an MXM process work pool
│
└── MXM application environments
    ├── mxm-refdata
    ├── mxm-moneymachine
    ├── supporting MXM packages
    └── configured filesystem / PostgreSQL / secret infrastructure
```

The long-running orchestration services are containerised.

MXM application execution is not required to be containerised.

For V1, `monolith` itself is the controlled application runtime environment.

# 4. Prefect Control Plane

The Prefect control plane is a long-running infrastructure capability.

It currently consists of:

- Prefect server/API;
- Prefect UI;
- Prefect background services;
- PostgreSQL;
- Redis.

The control plane is defined under:

```text
infra/prefect/
```

in `mxm-moneymachine`.

The infrastructure stack is managed through Docker Compose.

Its responsibilities include:

- deployment registration;
- scheduling;
- flow-run coordination;
- task-run coordination;
- worker coordination;
- orchestration state;
- operational logs;
- retry state;
- concurrency state;
- execution history;
- operational artifacts.

The Prefect PostgreSQL database is an operational ledger.

It is not the authoritative store of MXM semantic state.

# 5. Infrastructure Lifecycle

Docker Compose owns the lifecycle of long-running Prefect infrastructure.

It defines:

- service topology;
- networking;
- startup configuration;
- service dependencies;
- persistent volumes;
- restart behaviour;
- control-plane configuration.

The current infrastructure entry point is:

```text
infra/prefect/stack.sh
```

The wrapper exists to provide a repeatable, secret-safe operational interface
around the Compose stack.

Prefect infrastructure secrets remain outside committed configuration and are
resolved through the accepted MXM secret infrastructure.

# 6. Work Pools

A Prefect work pool defines an execution contract.

It answers:

> On what kind of runtime infrastructure should this flow execute?

Work pools separate logical deployments from concrete execution backends.

Possible execution backends include:

```text
process
Docker
remote hosts
cloud compute
Kubernetes
future distributed execution substrates
```

The accepted V1 backend is:

```text
process execution on monolith
```

Different environments may use distinct work pools where operational isolation
requires it.

Work-pool configuration is operational policy.

It must not change the semantic meaning of the MXM operation being executed.

# 7. Process Workers

Process workers are the accepted V1 execution substrate.

A process worker:

```text
polls a Prefect work pool
        ↓
receives a scheduled flow run
        ↓
creates a local Python process
        ↓
executes the MXM flow on monolith
```

This model deliberately uses the controlled `monolith` runtime directly.

Applications therefore execute with normal access to:

- MXM Python environments;
- `mxm-runtime`;
- `mxm-config`;
- accepted secret infrastructure;
- local PostgreSQL;
- configured MXM filesystem roots;
- source repositories required by operational applications;
- other explicitly installed MXM dependencies.

The process-worker model avoids creating a second representation of the
`monolith` runtime inside an execution container.

This is a deliberate V1 architectural choice rather than a temporary debugging
mechanism.

# 8. Alternative Execution Backends

Prefect supports other worker and infrastructure models.

MXM may later use:

- Docker workers;
- immutable runtime images;
- remote workers;
- cloud batch infrastructure;
- Kubernetes;
- other execution substrates.

These are portability, isolation, and scaling options.

They are not prerequisites for the accepted V1 architecture.

The semantic contract of an operation must remain unchanged when its execution
backend changes.

Therefore:

```text
process worker
Docker worker
cloud worker
future orchestrator
```

may alter:

```text
where and how the operation executes
```

but must not alter:

```text
what semantic operation the application performs
```

Container-specific policy is documented separately in:

```text
docs/policy/container-contract.md
```

# 9. Deployments

A Prefect deployment binds a flow to operational execution policy.

A deployment may define:

- flow entry point;
- deployment name;
- work pool;
- runtime parameters;
- schedule;
- environment-specific execution configuration;
- infrastructure job variables.

Deployments are treated as:

```text
version-controlled operational policy
```

rather than ephemeral CLI configuration.

Deployment definitions currently live under:

```text
infra/prefect/deployments/
```

They should be:

- explicit;
- inspectable;
- reproducible;
- scriptable;
- environment aware;
- free of committed secret values.

A deployment determines when and where an operation executes.

It does not define the semantic meaning of that operation.

# 10. Flows

Prefect flows define execution structure.

A flow may:

- invoke one MXM semantic operation;
- coordinate several semantic operations;
- express execution ordering;
- transport semantic references between operations;
- introduce task-level parallelism;
- emit operational logs and artifacts;
- provide an operator-facing execution unit.

The preferred architecture is:

```text
thin Prefect orchestration
        ↓
existing MXM application operations
```

Flows must not duplicate application logic.

In particular, flows should not contain domain-specific:

- SQL;
- source-generation logic;
- lifecycle semantics;
- semantic acceptance rules;
- persistence implementations;
- alternate configuration paths;
- alternate secret-access mechanisms.

Flows invoke accepted MXM application boundaries.

# 11. Tasks

A Prefect task is an operational execution and retry boundary.

Task decomposition must therefore respect semantic commit boundaries.

The governing policy is defined in:

```text
docs/policy/prefect-task-boundaries.md
```

The core rule is:

> A mutating MXM operation may be exposed to Prefect automatic retry only when
> the semantic operation has established safe re-entry behaviour.

The preferred initial alignment is:

```text
one semantic commit unit
        ≈
one Prefect retry unit
```

Pure or read-only operations may be decomposed more freely.

Semantic correctness takes precedence over orchestration granularity.

# 12. Semantic State and Execution State

Money Ex Machina maintains two distinct ledgers.

## Prefect operational ledger

Prefect records:

```text
deployment
flow run
task run
worker
work pool
retry
cancellation
timing
execution state
operational logs
```

This ledger answers:

> What happened computationally while MXM attempted to execute work?

## MXM semantic ledger

MXM domain state records:

```text
semantic identity
semantic lineage
acceptance
discovery
safe re-entry state
domain-specific durable state
supporting provenance
```

This ledger answers:

> What does Money Ex Machina believe to be true?

The two ledgers remain independently authoritative.

Neither is a duplicate of the other.

# 13. The Command / Result Boundary

The interaction between Prefect and an MXM application follows a command/result
model.

Conceptually:

```text
Prefect
    ↓
invoke semantic operation
    ↓
MXM application
    ↓
resolve semantic inputs
    ↓
perform domain work
    ↓
validate
    ↓
commit durable semantic state
    ↓
return semantic reference/result
    ↓
Prefect records operational outcome
```

Prefect does not inject its execution history into the semantic state engine so
that MXM can reason about retries.

Instead:

```text
MXM operation is safe under re-entry
```

and on repeated invocation the application examines its own durable semantic
state to determine correct behaviour.

# 14. Semantic References Through Flows

Prefect may transport semantic references between tasks and flows.

For example:

```text
R = build_refdata()

I = update_instrument_definitions(
    refdata=R
)

M = update_instrument_mappings(
    instrument_definitions=I
)
```

Here:

```text
R
I
M
```

represent semantic references produced by MXM applications.

Prefect transports these values as execution data.

It does not make them authoritative.

A downstream application remains responsible for:

```text
resolve reference
→ validate semantic state
→ verify compatibility
→ perform operation
```

The durable semantic lineage remains in MXM state.

# 15. Semantic Graph Versus Execution Graph

The semantic-state protocol distinguishes:

```text
semantic dependency graph
execution graph
```

The distinction is reflected directly in the orchestration architecture.

## Semantic dependency graph

Example:

```text
RefData R42
    ↓
InstrumentDefinitions I77
    ↓
InstrumentMappings M18
    ↓
MarketData D103
    ↓
SignalState S81
    ↓
TargetHoldings H17
```

This graph describes durable domain relationships.

MXM owns it.

## Execution graph

Example:

```text
run refdata
    ↓
run instrument definitions
    ↓
run instrument mappings
    ↓
run market data
```

This graph describes an execution plan.

Prefect owns it.

An execution plan is one way of materialising the required semantic state.

It is not semantic truth itself.

# 16. Execution Ordering

Prefect may order tasks based on expected semantic dependencies.

For example:

```text
refdata update
    ↓
instrument-definition update
    ↓
market-data update
```

Task completion is nevertheless only an operational signal.

The downstream operation must still establish from MXM semantic state that its
actual semantic prerequisites are satisfied.

Therefore:

> Prefect ordering determines when work is attempted.

> MXM semantic state determines whether the work is valid.

This allows execution plans to change without changing semantic meaning.

For example, if accepted upstream state already exists, an execution plan may
skip its reconstruction and continue from the existing semantic reference.

# 17. Retry Semantics

Retries are owned by Prefect.

Semantic recovery is owned by MXM.

On operational retry, MXM does not need to know:

```text
retry number
previous worker
previous Prefect state
previous process ID
```

Instead it asks:

```text
What semantic state currently exists?
```

Possible outcomes include:

```text
equivalent state already accepted
→ return it

recoverable partial domain state exists
→ reconcile or resume safely

required state absent
→ construct it
```

Prefect execution history does not determine these semantic decisions.

# 18. Correlation Between the Ledgers

Operational and semantic state should be easy to correlate without sharing
authority.

The preferred direction is:

```text
MXM semantic operation
    ↓
semantic reference / semantic result identity
    ↓
return to Prefect
    ↓
Prefect logs / artifacts / operational observability
```

This allows an operator to inspect a Prefect run and identify:

```text
which semantic state was consumed
which semantic state was produced
```

without making Prefect execution IDs part of semantic identity.

Prefect IDs may be retained as observational correlation metadata where useful.

Such correlation metadata must not determine:

- semantic identity;
- lineage;
- acceptance;
- equivalence;
- supersession;
- downstream validity.

# 19. RuntimeContext Boundary

Prefect flow execution must use the normal MXM runtime and composition path.

The accepted application construction model is:

```text
RuntimeIdentity
        ↓
runtime discovery
configuration
secrets/resources
        ↓
RuntimeContext
        ↓
application composition root
        ↓
application
```

Prefect is simply another application entry point alongside:

```text
CLI
tests
future operator surfaces
```

It must not create:

- a Prefect-specific `RuntimeContext`;
- an alternate configuration hierarchy;
- an alternate composition root;
- an alternate secret-access path.

Prefect execution bookkeeping such as:

```text
flow-run ID
task-run ID
retry number
worker identity
deployment ID
```

does not belong in `RuntimeContext`.

# 20. Runtime Configuration

Runtime configuration describes the environment in which MXM executes.

Examples include:

- environment;
- machine identity;
- filesystem roots;
- database endpoints;
- configured application resources;
- secret references;
- runtime role;
- execution substrate.

Runtime configuration is resolved through the accepted MXM runtime/configuration
architecture.

Prefect deployment parameters should pass only values that are legitimately part
of:

```text
operation parameters
```

or:

```text
runtime selection
```

rather than reproducing configuration already owned by MXM runtime discovery.

Detailed policy is defined in:

```text
docs/policy/runtime-configuration.md
```

# 21. Secrets

Prefect does not establish a new secret-access architecture for MXM applications.

Application secrets remain resolved through the accepted MXM runtime and secret
infrastructure.

The current invariant remains:

```text
No persisted cleartext secrets outside the accepted secret stores.
```

Prefect infrastructure itself may require infrastructure secrets, such as the
Prefect PostgreSQL credential.

Those are orchestration-infrastructure secrets and are injected into the
control-plane runtime by the infrastructure wrapper.

Application flows must not introduce ad-hoc Prefect-specific secret access where
the application already has an accepted MXM secret path.

# 22. Parallelism

MXM distinguishes between:

```text
flow-level parallelism
task-level parallelism
```

## Flow-level parallelism

Multiple flow runs may execute concurrently across workers.

Examples may include:

```text
one market-data operation per product
independent dataset updates
independent model calculations
```

## Task-level parallelism

Independent tasks may execute concurrently inside a flow.

Parallelism is permitted only where domain ownership and semantic consistency
remain explicit.

Operational parallelism must not become the sole mechanism protecting semantic
correctness.

Where multiple operations may contend for the same semantic ownership unit,
the underlying MXM application must provide appropriate consistency,
idempotency, or locking semantics.

# 23. Observability

Prefect is the primary operational observability surface for scheduled execution.

It provides visibility into:

- upcoming schedules;
- deployments;
- worker availability;
- flow history;
- task history;
- retries;
- failures;
- timings;
- operational logs;
- orchestration artifacts.

MXM applications provide semantic/operator diagnostics describing domain state.

Examples include:

```text
mxm-refdata smokecheck
market-data coverage
semantic-state inspection
future lineage / acceptance views
```

These surfaces complement one another.

Prefect answers:

> Did and how did the operation execute?

MXM diagnostics answer:

> What semantic state exists and is it acceptable?

# 24. Operator Surfaces

Prefect UI and CLI form part of the operational execution surface.

They do not replace MXM application-level operator interfaces.

MXM may expose:

- CLI;
- TUI;
- Prefect UI;
- private web operations surfaces;
- scheduled reports and alerts;
- future agent interfaces.

The broader operator-surface model is described in:

```text
docs/concepts/operator-surfaces.md
```

# 25. Deployment Portability

The V1 architecture deliberately optimises for a controlled `monolith` runtime.

This does not prevent future portability.

Because semantic meaning remains inside MXM applications and Prefect execution
policy remains outside them, the same semantic operation can later move from:

```text
monolith process worker
```

to:

```text
Docker worker
cloud worker
Kubernetes worker
other execution substrate
```

without changing its application contract.

Portability is therefore achieved through:

```text
separation of semantic meaning
from execution infrastructure
```

rather than by requiring containerisation from the beginning.

# 26. Current V1 Architecture

The accepted V1 orchestration model is:

```text
Dockerised Prefect control plane on monolith
        ↓
Prefect deployments and schedules
        ↓
process work pool
        ↓
persistent process worker on monolith
        ↓
thin Prefect flow/task wrappers
        ↓
RuntimeIdentity
        ↓
RuntimeContext
        ↓
normal MXM composition root
        ↓
retry-safe MXM semantic operations
        ↓
domain-owned durable semantic state
        ↓
semantic references returned to Prefect
        ↓
operational logs / artifacts / run state
```

This is the production-shaped V1 execution architecture.

Docker-worker execution and other deployment substrates remain optional future
extensions.

# 27. Explicit Non-Goals

The Prefect runtime model does not require:

- one Prefect control plane per MXM application;
- containerised execution of every MXM flow;
- application logic inside Prefect flows;
- Prefect-specific composition paths;
- Prefect-specific application configuration;
- Prefect execution IDs inside semantic identity;
- duplication of Prefect retry state in MXM;
- duplication of MXM semantic state in Prefect;
- Prefect assets as the authoritative semantic ledger;
- one universal semantic-state service;
- cloud or Kubernetes execution for V1.

These may be reconsidered only where concrete operational requirements justify
them.

# Core Invariants

```text
One logical MXM Prefect control plane orchestrates many MXM applications.

Prefect owns execution state.

MXM owns semantic state.

Prefect controls when and where work executes.

MXM applications define what the work means.

Prefect task completion is not semantic proof.

MXM semantic operations exposed to retry are safely re-enterable.

Prefect may transport semantic references between operations.

MXM remains authoritative for resolving and validating those references.

Semantic result identities may flow outward to Prefect for correlation.

Prefect execution identity does not determine semantic identity or acceptance.

RuntimeContext remains the single accepted MXM application composition context.

The accepted V1 execution substrate is a process worker on controlled monolith.

Alternative execution backends remain future portability options.
```

# Summary

The Prefect runtime architecture is intentionally simple.

Prefect provides:

```text
schedule
→ coordinate
→ execute
→ retry
→ observe
```

MXM applications provide:

```text
resolve semantic inputs
→ perform domain work
→ validate
→ commit semantic state
→ record lineage
→ return semantic references
```

The orchestration graph and semantic graph are related but distinct.

Prefect determines:

```text
what work should be attempted next
```

MXM semantic state determines:

```text
what is actually true
```

This separation allows Money Ex Machina to use Prefect as a powerful operational
execution system without making its trading semantics dependent on the
orchestrator.
