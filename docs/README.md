# Money Ex Machina Documentation

## Purpose

This directory contains the current architecture and operating policy for the integrated Money Ex Machina system.

The documentation is intended to answer:

```text
How does the Money Machine fit together?

Which component owns each responsibility?

What architectural rules should new work preserve?

Where is the authoritative documentation for a given concept?
```

These documents describe the **current intended system**.

Historical session plans and logs remain useful development records, but they are not architectural specifications.

# Documentation Principles

## Current state, not design history

Architecture and policy documents describe the system as it is currently intended to work.

They should not narrate every previous design or superseded implementation.

Important historical decisions may be recorded where they explain a current constraint, but obsolete architectures should not remain presented as alternatives.

## One authority per concept

A concept should have one authoritative documentation owner.

The general rule is:

> The package that implements a concept owns the authoritative documentation for that concept.

For example:

```text
mxm-runtime
    owns RuntimeIdentity, RuntimeContext, runtime discovery,
    and runtime construction

mxm-config
    owns configuration semantics

mxm-secrets
    owns secret-access semantics

mxm-refdata
    owns the reference-data application architecture
```

The `mxm-moneymachine/docs/` directory documents how these independently owned capabilities fit together into the Money Ex Machina system.

It should reference package-specific architecture rather than duplicate it.

## Architecture versus policy

Documents under:

```text
docs/concepts/
```

describe the architecture and mental models of the system.

Documents under:

```text
docs/policy/
```

define rules that implementations and operational work should obey.

# Recommended Reading Order

For reconstructing the current Money Ex Machina operational architecture, read these documents in order.

## 1. Semantic State Protocol

```text
concepts/semantic-state-protocol.md
```

Defines the common semantic contract across MXM applications.

Core concepts include:

```text
semantic identity
lineage
acceptance
discovery
safe re-entry
supporting provenance
selective reproducibility
```

The protocol deliberately does not require a central semantic-state service or universal framework.

Domains may initially implement the protocol through their existing application and storage boundaries.

This is the authoritative starting point for questions such as:

```text
What semantic state does MXM believe to be true?

How are trading states related?

What makes an operation safe to retry?

How should semantic state be passed between applications?
```

## 2. Prefect Runtime Model

```text
concepts/prefect-runtime-model.md
```

Defines the Money Ex Machina execution and orchestration architecture.

The core split is:

```text
Prefect
    owns execution state

MXM applications
    own semantic state
```

The current V1 topology uses:

```text
one logical MXM Prefect control plane
        ↓
Dockerised Prefect infrastructure on monolith
        ↓
Prefect process workers
        ↓
normal MXM application runtime and composition
```

This is the authoritative starting point for questions about:

```text
scheduling
deployments
work pools
workers
flows
tasks
retries
execution observability
operational versus semantic state
```

## 3. Operator Surfaces

```text
concepts/operator-surfaces.md
```

Defines how operators interact with the running Money Machine.

Current and future surfaces include:

```text
Prefect UI / CLI
MXM application CLIs
TUI
private web operations surfaces
scheduled reports and alerts
future programmable agents
```

Operator surfaces do not own state.

They expose and act through the authoritative Prefect and MXM application boundaries.

# Policies

## Runtime

```text
policy/runtime.md
```

Defines how `mxm-moneymachine` uses the shared runtime architecture implemented by `mxm-runtime`.

The authoritative runtime model itself lives in:

```text
mxm-runtime
```

This policy establishes the integration rules:

```text
normal RuntimeIdentity → RuntimeContext construction
no Prefect-specific runtime path
operation inputs are not runtime configuration
semantic references are operation inputs
Prefect execution bookkeeping does not belong in RuntimeContext
```

## Prefect Task Boundaries

```text
policy/prefect-task-boundaries.md
```

Defines how semantic correctness constrains Prefect task decomposition.

The central rule is:

> A mutating MXM operation may be exposed to automatic Prefect retry only when that semantic operation has established safe re-entry behaviour.

Task boundaries are chosen from semantic correctness outward rather than orchestration convenience inward.

## Container Contract

```text
policy/container-contract.md
```

Defines the MXM container boundary.

The current V1 architecture uses containers for:

```text
Prefect control-plane infrastructure
```

but uses:

```text
native process execution on controlled monolith
```

for MXM applications.

Containerised flow execution remains an optional future execution backend when isolation, portability, distribution, or deployment requirements justify it.

## Additional Policies

The directory also contains specialised policies:

```text
policy/daily_mark.md
policy/vendor-dependencies.md
```

These should be consulted when work enters the domains they govern.

# Architecture at a Glance

The current operational model can be summarised as:

```text
                       MONEY EX MACHINA

                       Prefect
                execution / orchestration
                         │
                         │ invokes
                         │ transports semantic refs
                         ▼
                 MXM applications
                         │
                         │ semantic operations
                         ▼
               domain-owned semantic state
```

Prefect answers:

```text
When should work run?
Where did it run?
Did execution fail or retry?
```

MXM answers:

```text
What semantic state exists?
What states produced it?
Is it accepted?
What should happen if the operation is invoked again?
```

The central architectural invariant is:

```text
semantic state determines what is true

orchestration state determines what work is attempted
```

# Semantic and Execution Graphs

Money Ex Machina deliberately distinguishes between:

```text
semantic dependency graph
```

and:

```text
execution graph
```

For example:

```text
RefDataState
    ↓
InstrumentDefinitionsState
    ↓
MarketDataState
    ↓
SignalState
    ↓
TargetHoldingsState
```

is durable semantic lineage.

A Prefect flow such as:

```text
update refdata
    ↓
update instruments
    ↓
update market data
    ↓
construct signals
```

is an execution plan for producing or refreshing that semantic state.

The execution graph may change without changing the semantic dependency graph.

# Repository and Package Boundaries

The `mxm-moneymachine` repository currently also contains shared Money Ex Machina integration infrastructure such as:

```text
infra/prefect/
```

This infrastructure serves Money Ex Machina as a whole.

Its location inside the repository does not imply that the Prefect control plane is owned by the `mxm-moneymachine` Python application.

Shared infrastructure may later move into a dedicated repository such as:

```text
mxm-orchestration
```

without changing the architecture described here.

# Using These Documents During Engineering Work

Before changing an architectural boundary:

1. identify the package or document that owns the concept;
2. read the current authoritative documentation;
3. preserve the existing boundary unless a concrete requirement demonstrates that it must change;
4. update the authoritative document when the architecture itself changes;
5. avoid creating a second description of the same concept elsewhere.

For orchestration or semantic-state work, begin with:

```text
concepts/semantic-state-protocol.md
concepts/prefect-runtime-model.md
policy/runtime.md
policy/prefect-task-boundaries.md
```

before relying on historical session logs.

# Documentation Map

```text
docs/
├── README.md
│
├── concepts/
│   ├── semantic-state-protocol.md
│   ├── prefect-runtime-model.md
│   └── operator-surfaces.md
│
└── policy/
    ├── runtime.md
    ├── prefect-task-boundaries.md
    ├── container-contract.md
    ├── daily_mark.md
    └── vendor-dependencies.md
```

This directory is the integration-level architectural reference for the running Money Ex Machina system.
