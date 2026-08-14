# MXM Semantic State Protocol

## Purpose

This document defines the semantic-state protocol for Money Ex Machina.

The protocol establishes how MXM applications identify, consume, produce, validate, relate, and record durable semantic state.

Its purpose is to provide a common correctness model across:

- reference data;
- market data;
- synthetic assets;
- models and signals;
- risk and portfolio construction;
- orders and execution state;
- future MXM domain applications.

The protocol deliberately does **not** define a central semantic-state engine, service, database schema, framework, or class hierarchy.

Instead:

> Every MXM domain owns its semantic state while conforming to a common protocol for identity, lineage, acceptance, discovery, and safe re-entry.

Supporting provenance should be recorded where useful for audit, diagnosis, and historical understanding.

Reproducibility is a stronger property that should be pursued deliberately where its value justifies the required controls. It is not implied merely by storing provenance.

Common implementation infrastructure should be extracted only when repeated domain requirements demonstrate that it is useful.

# 1. Two State Authorities

Money Ex Machina distinguishes between:

```text
operational execution state
semantic application state
```

These are different kinds of truth and have different owners.

## Operational execution state

The orchestration system owns:

- schedules;
- deployments;
- work pools;
- workers;
- flow runs;
- task runs;
- retries;
- cancellation;
- execution timing;
- execution failures;
- operational logs;
- orchestration artifacts.

For the current MXM architecture, Prefect is the operational execution authority.

## Semantic application state

MXM applications own:

- what semantic state exists;
- which semantic state was consumed;
- which semantic state was produced;
- relationships between semantic states;
- whether a state is valid or accepted;
- whether a state supersedes another;
- which state satisfies a downstream semantic requirement;
- idempotency and safe re-entry;
- domain-specific consistency guarantees.

Operational execution state does not determine semantic truth.

In particular:

```text
Prefect COMPLETED
≠
semantic state accepted
```

and:

```text
Prefect FAILED
≠
no semantic effect occurred
```

The application semantic state remains authoritative.

# 2. Semantic State Is Domain State

Semantic state describes the durable world as understood by Money Ex Machina.

Examples may include:

```text
RefDataState
InstrumentDefinitionsState
InstrumentMappingsState
MarketDataState
SyntheticAssetState
SignalState
TargetHoldingsState
OrderIntentState
RealisedHoldingsState
```

The exact state model remains domain specific.

The protocol does not require every domain to use the same tables, storage technology, lifecycle states, or object model.

A semantic state may be represented through:

- PostgreSQL records;
- filesystem datasets plus metadata;
- versioned source repositories;
- domain-specific stores;
- combinations of these.

What matters is that the domain can establish the required semantic properties explicitly and durably.

# 3. Core Semantic Contract

The core protocol consists of five concepts:

```text
identity
lineage
acceptance
discovery
safe re-entry
```

These form the everyday semantic fabric of the Money Machine.

Provenance and reproducibility support this core but have different purposes and stronger requirements.

# 4. Identity

A semantic state must be identifiable independently of its execution history.

Conceptually:

```text
RefDataState R42
InstrumentDefinitionsState I77
MarketDataState M103
SignalState S81
TargetHoldingsState H17
```

The identity answers:

> Which exact semantic state is this?

Semantic identity must not depend on:

- Prefect flow-run ID;
- Prefect task-run ID;
- worker identity;
- retry number;
- process ID;
- orchestration timestamps.

Repeated operational executions may therefore resolve to the same semantic state.

Stable identity allows downstream systems to refer to an exact state rather than to vague notions such as:

```text
latest signals
current refdata
today's holdings
```

# 5. Lineage

Lineage records relationships between semantic states.

It is the primary mechanism by which Money Ex Machina explains its trading decision chain.

Conceptually:

```text
MarketDataState M17
        ↓
SignalState S42
        ↓
TargetHoldingsState H11
        ↓
OrderIntentState O19
        ↓
RealisedHoldingsState H12
```

A downstream semantic state should identify the concrete upstream semantic states it consumed.

For example:

```text
TargetHoldingsState H11

inputs:
    signals = S42
    current_holdings = H10
    risk_state = R7
    portfolio_config = C3
```

This relationship is semantic lineage.

The durable statement is:

```text
H11 was constructed from S42, H10, R7, and C3
```

not:

```text
the portfolio task happened to run after the signal task
```

Lineage must survive independently of the orchestration history that happened to produce it.

## Why lineage is central

Lineage supports normal successful operation.

It allows MXM to answer questions such as:

```text
Which signals produced these target holdings?

Which market-data state produced these signals?

Which instrument state was used by this market-data state?

Which target holdings produced these order intents?

Which order intents produced these realised holdings?
```

It also allows analytics associated with different semantic states to be connected without requiring a reconstruction of the entire computation.

For trading-relevant states, explicit lineage is a core requirement.

# 6. Acceptance

Where a domain distinguishes usable from unusable results, semantic acceptance belongs to the domain.

Possible domain states may include:

```text
candidate
accepted
rejected
superseded
```

The exact lifecycle is domain specific.

The important rule is:

> Operational execution success must not substitute for semantic acceptance.

If a result requires validation before downstream use, that validation belongs inside the semantic contract of the producing application.

For example:

```text
build state
→ validate state
→ accept state
→ expose semantic reference
```

A downstream application should depend on an accepted semantic state, not merely on the successful completion of an upstream process.

# 7. Discovery

Applications must be able to discover semantic state according to domain requirements.

Conceptually:

```text
find an accepted RefDataState
suitable for:
    environment = prod
    universe = V1
    as_of = 2026-08-13
```

Discovery answers:

> Which already-existing semantic state satisfies this operation's requirements?

Discovery policy is domain owned.

It must not be inferred merely from which Prefect task happened to run most recently.

A semantic operation may therefore:

```text
receive an explicit state reference
```

or:

```text
discover an acceptable state from a semantic requirement
```

Both paths must ultimately resolve to a concrete semantic state.

# 8. Safe Re-Entry

Every mutating semantic operation exposed to an orchestration retry boundary must define safe re-entry behaviour.

Repeated equivalent invocation must not corrupt or accidentally duplicate authoritative semantic state.

On re-entry, an operation may:

```text
discover equivalent accepted state
→ return it
```

or:

```text
discover recoverable partial semantic state
→ reconcile or resume safely
```

or:

```text
discover no suitable state
→ construct and commit new state
```

The exact mechanism is domain specific.

The correctness guarantee comes from MXM semantic state and lifecycle logic rather than Prefect retry metadata.

This means that on operational retry, the application asks:

```text
What semantic state exists?
```

not:

```text
Which Prefect retry is this?
```

# 9. Semantic Operations

A semantic operation is an application operation that may observe or transition durable MXM semantic state.

Examples include:

```text
build reference data
update instrument definitions
update instrument mappings
materialise market data
construct signals
construct target holdings
create order intents
reconcile realised holdings
```

Each semantic operation should make explicit:

```text
what operation is being requested
what semantic inputs it consumes
what constitutes successful semantic completion
what durable state it produces
how equivalent re-entry behaves
```

A semantic operation must remain meaningful outside Prefect.

The same operation may be invoked through:

- CLI;
- Prefect;
- tests;
- future orchestration systems;
- future agent or operator surfaces.

Its semantic meaning must remain unchanged.

# 10. Semantic References

Semantic states may be referred to explicitly through stable semantic references.

Conceptually:

```text
SemanticRef(
    kind="refdata",
    id="R42",
)
```

or through domain-specific equivalents such as:

```text
RefDataStateRef("R42")
```

A semantic reference is:

```text
a durable reference to semantic truth
```

It is not the semantic state itself.

When an application receives a semantic reference, it remains responsible for resolving and validating it against the authoritative domain state.

A passed reference must not be trusted merely because another Prefect task returned it.

# 11. Explicit Reference Versus Discovery

MXM supports two legitimate ways of selecting semantic inputs.

## Explicit reference

An operation may receive the exact semantic state it should consume:

```text
update_instrument_definitions(
    refdata = R42
)
```

This makes the intended lineage explicit and deterministic.

## Semantic discovery

An operation may instead receive a semantic requirement:

```text
update_instrument_definitions(
    as_of = 2026-08-13
)
```

and resolve:

```text
accepted RefDataState satisfying policy
→ R42
```

Once resolved, the concrete state actually consumed must be recorded in the resulting semantic lineage.

Therefore:

```text
selector
→ discovery
→ concrete semantic reference
→ operation
```

The selector expresses policy.

The concrete reference records what was actually used.

# 12. Provenance

Provenance records information about how a semantic state came to exist.

Depending on the domain and importance of the state, this may include:

- source-data identity;
- source repository revision;
- configuration identity;
- model identity;
- code or package revision;
- as-of parameters;
- universe identity;
- external observation identity;
- other domain-specific construction facts.

Provenance answers questions such as:

```text
Which code produced this state?

Which configuration was active?

Which source revision was used?

Which vendor observation was consumed?

Which model version produced this signal state?
```

Provenance is primarily useful for:

- post-mortem investigation;
- audit;
- debugging;
- historical understanding;
- explaining unexpected semantic results.

It is therefore important, particularly for trading-relevant state, but it is not identical to lineage.

## Lineage versus provenance

Lineage says:

```text
H11 depends on S42
```

Provenance may say:

```text
S42 was produced by:
    model version M7
    code revision abc123
    configuration C12
    market-data state D103
```

Lineage describes relationships in the semantic-state graph.

Provenance describes the construction history of a semantic state.

# 13. Reproducibility

Reproducibility is a stronger property than provenance.

A state is reproducible when the retained semantic inputs, provenance, environment requirements, and computation rules are sufficient to reconstruct or independently verify the state to the claimed degree.

Possible guarantees range from:

```text
conceptually reproducible
```

through:

```text
numerically equivalent
```

to:

```text
bitwise identical
```

These are different guarantees and must not be conflated.

Exact reproducibility may require preserving or controlling:

- immutable input data;
- code;
- configuration;
- dependency versions;
- model parameters;
- random seeds;
- external observations;
- numerical libraries;
- platform-dependent behaviour;
- other nondeterministic inputs.

Therefore:

> The presence of provenance does not imply reproducibility.

MXM should pursue reproducibility where it materially improves trading robustness, auditability, or research integrity.

It should not claim exact reproducibility merely because some provenance has been recorded.

For important historical trading decisions, reproducibility-grade provenance is highly desirable.

It is not a blanket prerequisite for every intermediate semantic state.

# 14. Relative Importance

The protocol deliberately gives different weight to lineage, provenance, and reproducibility.

## Everyday semantic requirements

For trading-relevant accepted state, the most important properties are:

```text
identity
lineage
acceptance
discovery
safe re-entry
```

These are used during normal operation.

## Investigative requirements

Provenance supports:

```text
audit
diagnosis
post-mortem analysis
unexpected-result investigation
```

It should be retained proportionately to the importance and failure risk of the semantic state.

## Robustness requirements

Reproducibility is a higher-order robustness property.

It should be strengthened deliberately where valuable rather than assumed universally.

This hierarchy keeps the semantic protocol both useful and lightweight.

# 15. Relationship to Prefect

Prefect owns execution orchestration.

MXM owns semantic correctness.

The interaction between them follows a command/result protocol.

Conceptually:

```text
Prefect task
    ↓
invoke semantic operation
    ↓
MXM discovers/resolves semantic state
    ↓
MXM performs domain work
    ↓
MXM validates and commits durable semantic result
    ↓
return semantic reference/result
    ↓
Prefect records operational success and correlation
```

Prefect may transport semantic references between tasks.

For example:

```text
R = build_refdata()

I = update_instrument_definitions(
    refdata = R
)

M = update_instrument_mappings(
    instrument_definitions = I
)
```

The returned values represent semantic references.

Prefect is transporting them as execution data.

It is not making them authoritative.

# 16. Semantic Graph Versus Execution Graph

MXM distinguishes between:

```text
semantic dependency graph
execution graph
```

## Semantic dependency graph

The semantic graph records enduring domain relationships.

For example:

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

This graph belongs to MXM semantic state.

It must remain meaningful if Prefect history is unavailable.

## Execution graph

The execution graph describes how MXM chooses to produce or refresh semantic state.

For example:

```text
run refdata
    ↓
run instrument definitions
    ↓
run instrument mappings
    ↓
run market data
```

This graph belongs to Prefect.

It represents an execution plan, not semantic truth.

The execution plan may legitimately differ from the semantic dependency graph.

For example, if an acceptable `RefDataState R42` already exists:

```text
discover R42
    ↓
skip refdata construction
    ↓
run instrument definitions against R42
```

No semantic dependency has changed.

Only the execution plan has changed.

# 17. Task Completion Is Not Semantic Proof

A downstream operation must not rely on:

```text
the preceding Prefect task completed
```

as proof that a semantic prerequisite exists.

Instead it relies on:

```text
accepted semantic state R42 exists
and satisfies this operation's requirements
```

A Prefect task may conveniently return `R42` to the downstream task.

The downstream application still resolves and validates `R42` through the semantic authority.

Therefore:

> Prefect ordering determines when an operation is attempted. Semantic state determines whether that operation is valid.

# 18. Retry Boundaries

A Prefect task boundary is an operational retry boundary.

Therefore:

> Prefect automatic retry is permitted around a mutating MXM operation only when that semantic operation has established safe re-entry behaviour.

A semantic commit unit must not be split across multiple independently retryable Prefect tasks unless each resulting unit is independently safe under retry.

Preferred alignment:

```text
semantic commit unit
=
retry unit
=
independent ownership unit
```

Where safe re-entry has not been established, retries should remain disabled or explicitly bounded until the domain operation provides the required semantics.

Retry count and Prefect execution history are not semantic inputs.

On retry, the application discovers its own durable semantic state and decides how to proceed.

# 19. Correlation Between Operational and Semantic State

Operational and semantic ledgers remain independently authoritative while remaining easy to correlate.

The preferred correlation direction is:

```text
MXM semantic operation
    ↓
semantic operation/result reference
    ↓
returned to Prefect
    ↓
Prefect log / artifact / observability record
```

This allows an operator to move from:

```text
Prefect flow/task execution
```

to:

```text
the semantic state produced or consumed
```

without making Prefect identifiers part of semantic identity.

Prefect identifiers may be retained as observational correlation metadata if a future operational need demonstrates value.

Such metadata must obey the rule:

> Removing or changing orchestration correlation metadata must not change semantic identity, lineage, validity, or acceptance.

# 20. Execution Information Is Not Semantic Information

The following are operational execution facts:

```text
flow-run ID
task-run ID
deployment ID
worker
work pool
retry number
process ID
orchestrator state
```

They do not by themselves provide meaningful information about MXM semantic state.

Semantic decisions must therefore not depend on statements such as:

```text
this is retry 2
the previous flow run failed
this worker previously crashed
```

Where adaptive behaviour is required, the application should discover the relevant semantic or external state directly.

Examples:

```text
Is the requested state already accepted?

What materialisation already exists?

Which partitions are committed?

Is the required vendor data currently available?

What broker order state exists?
```

Correct behaviour is derived from domain truth rather than execution history.

# 21. RuntimeContext Boundary

`RuntimeContext` exists to compose an MXM application in a concrete runtime.

The accepted construction model is:

```text
RuntimeIdentity
    ↓
runtime discovery
configuration
secrets/resources
    ↓
RuntimeContext
    ↓
composition root
    ↓
application
```

`RuntimeContext` may contain information necessary to determine the application's operational environment.

It must not become a carrier for Prefect execution bookkeeping.

In particular, MXM does not require a parallel application-facing:

```text
ExecutionContext
```

containing Prefect flow-run, task-run, retry, or worker information.

Semantic operation parameters and semantic references are explicit operation inputs rather than hidden execution context.

# 22. Implementation Policy

This protocol does not require a central semantic-state service.

Initial implementations should prefer the simplest domain-owned mechanism that satisfies the protocol.

For example:

```text
mxm-refdata
    PostgreSQL reference-data state
    source identity
    idempotent build semantics

marketdata
    dataset state
    coverage/watermarks
    semantic metadata
    idempotent ingest semantics

signals
    signal-state identity
    input lineage
    acceptance

portfolio
    target-holdings identity
    signal/risk/current-holdings lineage
    acceptance
```

Common abstractions should be introduced only when multiple domains demonstrate the same requirement.

The preferred evolution is:

```text
domain-specific implementations
        ↓
observe genuine repetition
        ↓
extract common semantic types/services
```

rather than:

```text
design universal semantic engine
        ↓
force all domains into it
```

# 23. Explicit Non-Goals

This protocol does not currently require:

- a standalone `mxm-semantic` service;
- a universal semantic database schema;
- a generic event-sourcing framework;
- a universal `SemanticArtifact` class;
- a universal lifecycle state machine;
- a universal semantic transaction manager;
- exhaustive provenance for every intermediate result;
- universal bitwise reproducibility;
- orchestration-state replication inside MXM;
- replacement of Prefect's operational ledger;
- replacement of domain-specific stores;
- one physical store for all semantic metadata.

Future implementation may introduce shared components where justified.

Those are implementation decisions, not prerequisites of the protocol.

# 24. Design Tests

A semantic operation should satisfy the following tests.

## Semantic identity

Can MXM identify the concrete state produced or consumed independently of Prefect execution identity?

For material trading state, the answer should be yes.

## Lineage

Given an accepted downstream state:

```text
can MXM identify the concrete upstream semantic states it consumed?
```

For material trading dependencies, the answer should be yes.

## Acceptance independence

Can MXM determine whether a result is acceptable without examining Prefect execution state?

The answer should be yes.

## Retry independence

If the operation is invoked twice:

```text
can the application determine correct behaviour
from its own durable semantic state?
```

The answer must be yes before automatic retries are relied upon.

## Orchestrator independence

If Prefect were replaced tomorrow:

```text
would this operation retain the same semantic meaning?
```

The answer should be yes.

## Provenance adequacy

If an important semantic result is questioned:

```text
does MXM retain enough provenance to investigate
how that state came to exist?
```

For trading-relevant state, the answer should normally be yes.

## Reproducibility claim

If a state is described as reproducible:

```text
have we explicitly defined the degree of reproducibility
and retained sufficient inputs to support that claim?
```

The answer must be yes.

# 25. Current V1 Position

MXM does not yet contain one common semantic-state implementation.

This is intentional.

Existing applications already contain parts of the protocol:

- `mxm-refdata` provides reproducible state construction, durable operational state, and safe repeated `build()` semantics;
- marketdata contains existing lifecycle, watermark, idempotency, dataset, and semantic-metadata machinery;
- future domains will introduce additional semantic requirements as they become concrete.

The next semantic-state work should therefore begin by:

```text
inventory existing domain semantic machinery
        ↓
map it onto this protocol
        ↓
identify genuine common concepts
        ↓
remove any accidental duplication of execution state
        ↓
extract only common implementation that is justified
```

The protocol is the common architecture.

The common implementation remains deliberately minimal until the applications demonstrate what it needs to contain.

# Core Invariants

```text
Prefect owns execution state.
MXM owns semantic state.

Operational success is not semantic proof.

Semantic identity is independent of execution identity.

Material trading dependencies are represented through explicit semantic lineage.

Semantic operations exposed to retries are safely re-enterable.

Prefect may transport semantic references but does not make them authoritative.

Downstream operations resolve and validate semantic inputs against MXM semantic state.

Provenance supports audit and diagnosis but does not automatically guarantee reproducibility.

Reproducibility is an explicit robustness guarantee, not an assumed property.

RuntimeContext contains application runtime/composition information,
not orchestrator bookkeeping.

Common semantic infrastructure is extracted from demonstrated repetition,
not designed speculatively.
```

# Summary

The MXM semantic-state architecture is intentionally lightweight.

It does not introduce a second orchestration engine.

It does not require a universal semantic framework.

Its everyday semantic discipline is:

```text
identify semantic state
→ resolve concrete semantic inputs
→ perform domain work
→ validate
→ commit durable semantic state
→ record lineage
→ return semantic reference
```

Where appropriate, the application additionally records provenance sufficient for later investigation.

Where stronger reproducibility matters, that guarantee is designed and stated explicitly.

Prefect provides:

```text
schedule
→ execute
→ retry safely
→ transport semantic references
→ record operational correlation
```

Together these provide a complete separation of concerns:

```text
semantic state determines what is true

semantic lineage records how trading states depend on one another

orchestration state determines what work is attempted
```

This protocol is the architectural contract against which future MXM semantic-state implementations should be built.
