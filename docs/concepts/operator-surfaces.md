# Operator Surfaces

## Purpose

Money Ex Machina exposes multiple operator interaction surfaces.

These surfaces allow humans and future programmable agents to:

- inspect operational execution;
- inspect semantic application state;
- invoke accepted operations;
- observe failures and diagnostics;
- receive scheduled reports and alerts.

Operator surfaces do not own state.

They expose and act through the authoritative systems beneath them:

```text
Prefect
    → operational execution state

MXM applications
    → semantic application state
```

A surface may present information from both systems, but it must preserve the distinction between them.

# 1. Core Principle

Operator interfaces are views and control surfaces over existing application and orchestration boundaries.

They must not create alternative execution paths, semantic state, or hidden administration mechanisms.

Conceptually:

```text
operator surface
        ↓
accepted orchestration or application boundary
        ↓
authoritative state
```

Not:

```text
operator surface
        ↓
direct database mutation
hidden script
special configuration path
alternate business logic
```

The same underlying operation should retain the same meaning regardless of whether it is invoked through:

- CLI;
- Prefect;
- TUI;
- private web operations surface;
- future agent interface.

# 2. Operational Execution Surfaces

Prefect provides the primary operational-execution surfaces.

These include:

```text
Prefect UI
Prefect CLI
```

They expose execution concerns such as:

- deployments;
- schedules;
- upcoming runs;
- flow runs;
- task runs;
- work pools;
- workers;
- retries;
- failures;
- cancellations;
- execution timing;
- operational logs;
- orchestration artifacts.

These surfaces answer questions such as:

```text
Is the daily reference-data deployment armed?

When is its next run?

Which worker executed it?

Did the task retry?

Why did this execution fail?

What semantic result did this flow report?
```

Prefect is authoritative for these operational facts.

Operational execution state must not be treated as semantic application truth merely because it is visible through an operator UI.

# 3. Application and Semantic Surfaces

MXM applications provide operator surfaces for domain and semantic state.

The primary current form is:

```text
application CLI
```

Examples include application-level commands for:

- preflight;
- smokechecks;
- diagnostics;
- coverage inspection;
- domain-state reads;
- explicit application operations.

Future surfaces may include:

```text
TUI
private web operations views
semantic-state explorer
lineage views
domain-specific dashboards
```

These surfaces answer questions such as:

```text
What reference-data state exists?

Is it accepted and healthy?

Which semantic state produced these target holdings?

Which signals fed this portfolio state?

What market-data state did those signals consume?

Which state supersedes this one?
```

MXM application and semantic state remains authoritative for these questions.

# 4. Combined Operations Surfaces

A future private operations interface may combine operational and semantic information.

For example:

```text
Daily Refdata Update

Prefect:
    flow run          completed
    retries           0
    worker            monolith
    duration          ...

MXM:
    semantic state    R42
    acceptance        accepted
    lineage           ...
    smokecheck        PASS
```

This is desirable because operators often need to move between:

```text
What happened computationally?
```

and:

```text
What semantic state resulted?
```

The interface may correlate the two ledgers through semantic references returned to Prefect.

It must not collapse them into one state.

In particular:

```text
Prefect COMPLETED
```

must not be presented as equivalent to:

```text
MXM semantic state ACCEPTED
```

unless the application itself has established that semantic result.

# 5. Semantic Lineage as an Operator Surface

Semantic lineage is a particularly important operator-facing capability for Money Ex Machina.

The trading system should eventually allow an operator to traverse relationships such as:

```text
MarketDataState
        ↓
SignalState
        ↓
TargetHoldingsState
        ↓
OrderIntentState
        ↓
RealisedHoldingsState
```

This supports ordinary analytical questions such as:

```text
Which signals produced this target portfolio?

Which market-data state produced those signals?

Which target holdings generated these orders?
```

Lineage inspection is therefore not only a post-mortem facility.

It is part of the normal semantic operating surface of the Money Machine.

Detailed semantic-state policy is defined in:

```text
docs/concepts/semantic-state-protocol.md
```

# 6. CLI Surfaces

CLI commands remain a first-class operator interface.

They are particularly appropriate for:

- direct inspection;
- diagnostics;
- smoke tests;
- explicit one-off operations;
- scripting;
- acceptance demonstrations;
- development and debugging.

CLI commands should invoke the same application composition and semantic operation boundaries used by Prefect.

A CLI must not become a privileged alternate implementation of the application.

Conceptually:

```text
CLI ───────┐
           ├── RuntimeIdentity
Prefect ───┘       ↓
              RuntimeContext
                   ↓
               composition
                   ↓
               application
```

# 7. TUI Surfaces

A future TUI may provide a richer local operator experience while preserving terminal-first operation.

Useful TUI capabilities may include:

- execution status;
- semantic-state browsing;
- lineage navigation;
- application diagnostics;
- deployment inspection;
- recent failures;
- scheduled-operation overview.

A TUI should remain a presentation and control layer over accepted APIs and application boundaries.

It must not introduce separate state ownership.

# 8. Private Web Operations Surface

A private web operations surface may eventually provide secure remote observability and operational control over the running Money Machine.

It may combine:

- Prefect operational state;
- MXM semantic state;
- lineage;
- application diagnostics;
- reports;
- alerts;
- explicit operator actions.

The web surface should be treated as:

```text
a remote operator client
```

rather than:

```text
a second execution or semantic engine
```

Actions initiated through it should delegate to the same underlying application and orchestration boundaries used elsewhere.

# 9. Scheduled Reports and Alerts

Scheduled reports and alerts are read-oriented operator surfaces.

Examples may include:

- daily system health;
- failed scheduled operations;
- stale semantic state;
- unexpected data coverage;
- portfolio changes;
- risk changes;
- order/execution anomalies.

Reports may combine operational and semantic information where useful.

They should preserve the source of each fact.

For example:

```text
execution failure
    → Prefect operational state

stale accepted market-data state
    → MXM semantic state
```

Alerts should not create a third independent definition of system health.

# 10. Programmable and Agent Interfaces

Future programmable agents may act as operator clients.

They may:

- inspect system state;
- query lineage;
- review execution failures;
- invoke permitted application operations;
- trigger Prefect deployments;
- prepare reports;
- propose operator actions.

Agents must use the same accepted interfaces and authority boundaries as human-operated surfaces.

They must not gain privileged access to:

- direct database mutation;
- hidden execution paths;
- unvalidated semantic state transitions;
- alternate secret mechanisms.

Agent access changes who or what operates the system.

It does not change the system architecture.

# 11. Action Boundaries

Operator actions fall into two broad categories.

## Orchestration actions

Examples:

```text
run deployment
pause schedule
retry execution
cancel flow run
inspect worker
```

These belong to Prefect.

They should be performed through Prefect's accepted control surfaces or APIs.

## Semantic/application actions

Examples:

```text
build reference data
inspect accepted signal state
rebuild a dataset
construct target holdings
inspect lineage
```

These belong to MXM applications.

They should be performed through accepted application boundaries.

An operator surface may initiate both types of action.

It must route them to the correct authority.

# 12. No Direct State Mutation

Operator convenience must not bypass application correctness.

Discouraged patterns include:

```text
web UI
    → direct SQL UPDATE

TUI
    → mutate dataset files directly

admin script
    → alter semantic acceptance outside application logic
```

The preferred model is:

```text
operator action
    ↓
application operation
    ↓
semantic validation
    ↓
durable state transition
```

or:

```text
operator action
    ↓
Prefect control action
    ↓
orchestrated execution
```

This keeps operator interfaces replaceable and application invariants centralised.

# 13. Security Boundaries

Money Ex Machina distinguishes between several information and interaction surfaces with different security requirements.

## Private operations plane

Contains:

- operational execution state;
- semantic trading state;
- system diagnostics;
- controls;
- potentially sensitive portfolio and trading information.

Access must be restricted.

## Public publishing surface

Contains intentionally published material.

It must remain separate from private operational controls and state.

## Documentation system

Contains architecture, policy, and operating documentation.

Documentation may describe the private system without itself becoming an operational access path.

These surfaces may share underlying authored content or generated information where appropriate, but their security and trust boundaries remain distinct.

# 14. Authority and Correlation

Operator surfaces frequently need to display correlated information from different authorities.

The rule is:

```text
Prefect
    authoritative for execution facts

MXM
    authoritative for semantic facts
```

Correlation may be established through semantic references returned by MXM operations and recorded in Prefect logs or artifacts.

A combined operator surface may then navigate:

```text
Prefect flow run
    ↓
semantic result R42
    ↓
semantic lineage
    ↓
downstream trading state
```

without making either ledger dependent on the other.

# 15. Current V1 Operator Model

The current V1 operator surfaces are intentionally simple.

```text
Prefect UI / CLI
    → execution and schedule inspection

MXM application CLIs
    → semantic/application inspection and direct operations

scheduled diagnostics / reports
    → targeted observability where required
```

Future TUI, web, and agent interfaces may be added when they provide concrete operational value.

They are not prerequisites for the running V1 Money Machine.

# Explicit Non-Goals

The operator-surface architecture does not require:

- one universal MXM UI;
- a custom web operations platform for V1;
- replacement of Prefect UI;
- replacement of application CLIs;
- duplicated operational state;
- duplicated semantic state;
- direct database administration as an application interface;
- privileged agent execution paths;
- a public interface to private operational controls.

New surfaces should be introduced only when they improve operator capability without creating new state authorities.

# Core Invariants

```text
Operator surfaces do not own state.

Prefect surfaces expose operational execution state.

MXM application surfaces expose semantic/domain state.

A combined surface may correlate both ledgers but must not collapse them.

Prefect execution success is not semantic acceptance.

Operator actions use accepted orchestration or application boundaries.

CLI, TUI, web, and agent interfaces must not create alternative business logic.

Direct mutation of authoritative semantic state outside application boundaries is not an operator interface.

Private operations, public publishing, and documentation remain distinct security surfaces.
```

# Summary

Money Ex Machina supports multiple operator surfaces because different operational questions require different interfaces.

The architecture remains simple:

```text
operator
    ↓
appropriate surface
    ↓
authoritative Prefect or MXM boundary
    ↓
authoritative state
```

Prefect provides the operational view of execution.

MXM applications provide the semantic view of the trading system.

Future interfaces may combine these views for convenience, but they remain presentation and control layers over the same underlying authorities.
