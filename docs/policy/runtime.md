# Runtime Policy

## Purpose

This document defines how `mxm-moneymachine` uses the shared MXM runtime architecture.

The authoritative definition of:

- `RuntimeIdentity`;
- runtime discovery;
- configuration resolution;
- resource materialisation;
- `RuntimeContext`;
- runtime integration with `mxm-config`;
- runtime integration with `mxm-secrets`;

belongs to:

```text
mxm-runtime
```

and is documented in that package.

This policy defines only the integration rules that `mxm-moneymachine`, its Prefect flows, and related operational code must follow.

# Core Rule

MXM applications use the normal runtime construction path:

```text
RuntimeIdentity
    ↓
mxm-runtime
    ↓
RuntimeContext
    ↓
application composition root
    ↓
application
```

Prefect is another application entry point.

It must not introduce an alternative runtime architecture.

# Runtime Construction

Flows and operational entry points must use `mxm-runtime` to construct the application runtime.

They must not independently:

- discover machine identity;
- discover execution substrate;
- load MXM configuration;
- resolve secrets;
- construct database configuration;
- derive filesystem roots;
- reproduce runtime resource construction.

Application composition must use the same runtime path whether invoked through:

```text
CLI
Prefect
tests
future operator surfaces
```

# Operation Inputs Are Not Runtime Configuration

MXM distinguishes between:

```text
runtime context
```

and:

```text
semantic operation inputs
```

Runtime context describes the environment in which an application executes.

Operation inputs describe the semantic work being requested.

Examples of operation inputs include:

- product identifiers;
- as-of dates;
- update modes;
- semantic state references;
- semantic selectors;
- requested universe or scope.

These values should be passed explicitly to the application operation.

They must not be hidden inside `RuntimeContext`.

# Semantic References

Semantic references such as:

```text
RefDataStateRef(...)
SignalStateRef(...)
TargetHoldingsStateRef(...)
```

are semantic operation inputs.

They are not runtime configuration.

Prefect may transport semantic references between tasks and flows, but the receiving application remains responsible for resolving and validating them against authoritative MXM semantic state.

The semantic-state contract is defined in:

```text
docs/concepts/semantic-state-protocol.md
```

# Prefect Execution State

Prefect execution information is orchestration state.

Examples include:

- flow-run ID;
- task-run ID;
- deployment ID;
- work pool;
- worker identity;
- retry number;
- Prefect execution state.

These values do not belong in `RuntimeContext`.

MXM does not maintain a parallel application-facing `ExecutionContext` for Prefect bookkeeping.

Semantic application behaviour must not depend on Prefect retry or execution history.

The orchestration boundary is defined in:

```text
docs/concepts/prefect-runtime-model.md
```

# Deployment Configuration

Prefect deployments may select:

- work pool;
- schedule;
- execution substrate;
- deployment parameters;
- other orchestration-specific execution policy.

Deployment configuration must not duplicate application configuration already owned by:

```text
mxm-config
mxm-runtime
mxm-secrets
```

Where a value describes the application runtime itself, it belongs in the shared MXM runtime/configuration system.

Where a value describes how Prefect schedules or executes the operation, it belongs in Prefect deployment policy.

# Secrets

Application secrets are resolved through the accepted MXM runtime and secret architecture.

Flows must not introduce Prefect-specific secret access paths where the application already has an accepted `mxm-runtime` / `mxm-secrets` path.

Prefect infrastructure may have its own infrastructure credentials, such as the Prefect PostgreSQL password.

Those credentials belong to the orchestration infrastructure boundary and must remain separate from application secret semantics.

# Invariants

```text
mxm-runtime owns runtime construction.

mxm-moneymachine consumes that runtime architecture.

Prefect does not create an alternative RuntimeContext.

Operation parameters are explicit application inputs.

Semantic references are operation inputs, not runtime configuration.

Prefect execution metadata is not application runtime state.

Application secrets use the accepted MXM runtime and secret path.

Deployment configuration controls execution policy,
not application semantics.
```

## Summary

`mxm-moneymachine` does not define its own runtime architecture.

It uses the shared MXM runtime:

```text
RuntimeIdentity
→ RuntimeContext
→ composition
→ application
```

and keeps three concerns distinct:

```text
runtime configuration
semantic operation inputs
orchestration execution state
```

This preserves one authoritative runtime model across Money Ex Machina while allowing Prefect to orchestrate many independently composed MXM applications.
