# Container Contract

## Purpose

This document defines the Money Ex Machina policy for containerised runtime components.

The current V1 architecture uses containers for the long-running Prefect control plane.

MXM application operations currently execute through a Prefect process worker directly on the controlled `monolith` runtime.

Therefore:

```text
current V1
    Prefect control plane     → containers
    MXM flow execution        → native process on monolith
```

This document also preserves the execution contract that must apply if MXM later introduces Docker-worker or other containerised application execution.

Containerised flow execution is an optional execution backend, not a prerequisite of the Money Ex Machina architecture.

# 1. Current V1 Position

The accepted V1 runtime topology is:

```text
monolith
│
├── Docker Compose
│   └── Prefect control plane
│       ├── PostgreSQL
│       ├── Redis
│       ├── Prefect API / UI
│       └── Prefect background services
│
└── Prefect process worker
    ↓
    native MXM application execution
    ↓
    RuntimeIdentity
    ↓
    RuntimeContext
    ↓
    application composition
```

`monolith` is an owned and controlled MXM runtime environment.

It already provides:

- MXM Python environments;
- configured PostgreSQL;
- MXM filesystem roots;
- runtime configuration;
- accepted secret infrastructure;
- required source repositories;
- operational application dependencies.

The V1 architecture therefore does not reproduce this environment inside ephemeral flow containers.

# 2. Why the Prefect Control Plane Is Containerised

The Prefect control plane consists of long-running infrastructure services.

Containers are well suited to this boundary because the services have explicit:

- images;
- ports;
- network relationships;
- persistent volumes;
- service dependencies;
- restart policies;
- infrastructure credentials.

The Prefect stack is defined under:

```text
infra/prefect/
```

and managed through Docker Compose.

Containerisation here provides a clean lifecycle boundary around shared orchestration infrastructure.

It does not imply that every operation orchestrated by Prefect should also execute inside a container.

# 3. Why MXM Operations Currently Use Process Execution

Session 44 validated both process-worker and Docker-worker execution.

Process execution successfully ran real MXM application operations against the local runtime environment.

Docker execution also reached MXM application code, but required the execution container to reproduce or import substantial parts of the host runtime contract, including:

- source code;
- filesystem state;
- configuration;
- secrets;
- database connectivity;
- host-network relationships;
- runtime dependencies.

For V1, this duplication provides insufficient benefit relative to the additional operational complexity.

The accepted model is therefore:

> Use the controlled `monolith` runtime directly until isolation, portability, distribution, or deployment requirements justify a separate container execution boundary.

Process execution is not considered a lesser or temporary production mode.

It is the accepted V1 execution substrate.

# 4. Containers Are an Execution Backend

Money Ex Machina separates:

```text
semantic application contract
```

from:

```text
execution substrate
```

An MXM semantic operation must retain the same meaning whether executed through:

```text
process worker
Docker worker
remote worker
cloud worker
future execution backend
```

Changing the execution substrate may change:

- dependency packaging;
- filesystem access;
- networking;
- secret delivery;
- startup lifecycle;
- resource isolation.

It must not change:

- semantic identity;
- semantic inputs;
- lineage;
- acceptance;
- safe re-entry behaviour;
- domain correctness.

Containerisation is therefore an infrastructure concern rather than an application-semantic concern.

# 5. When Containerised Execution Becomes Useful

Containerised application execution may be introduced when concrete requirements justify it.

Examples include:

- stronger dependency isolation;
- immutable deployable runtime artifacts;
- multiple incompatible application environments;
- execution on remote worker hosts;
- cloud or batch execution;
- Kubernetes execution;
- horizontal scaling across machines;
- stronger deployment reproducibility;
- restricted or specialised runtime environments.

The existence of one of these requirements should drive container adoption.

Containers should not be introduced merely to make a local controlled runtime appear more production-shaped.

# 6. Core Container Principle

Where MXM application execution is containerised:

> A flow container is disposable compute.

The container receives all required runtime inputs through an explicit contract.

Durable truth remains outside the container.

Conceptually:

```text
code in
configuration in
secrets in
data access in/out
        ↓
disposable compute
        ↓
durable MXM state out
operational logs out
```

The container itself is not authoritative state.

# 7. Code Contract

A containerised MXM operation must receive application code explicitly.

Possible models include:

## Development-mounted source

```text
host repository
    ↓ bind mount
runtime container
```

This is useful for:

- development;
- rapid iteration;
- execution-backend testing.

It is not an immutable deployment artifact.

## Immutable runtime image

```text
tested application packages
+ pinned dependencies
+ required system libraries
        ↓
versioned runtime image
```

This is the preferred model if container execution becomes an operational deployment mechanism.

The exact future image and artifact supply chain is deliberately deferred.

# 8. Runtime Construction Inside Containers

Containerised execution must still use the normal MXM runtime architecture:

```text
RuntimeIdentity
    ↓
mxm-runtime
    ↓
RuntimeContext
    ↓
composition root
    ↓
application
```

A container must not introduce:

- a second application composition path;
- container-specific application semantics;
- a separate configuration hierarchy;
- direct secret access that bypasses MXM runtime policy.

The container changes the execution substrate.

It does not change how the application is constructed conceptually.

# 9. Configuration Contract

Container-specific infrastructure configuration may include:

- image identity;
- mount definitions;
- network configuration;
- resource limits;
- working directory;
- execution user;
- container lifecycle policy.

Application runtime configuration remains owned by the normal MXM configuration/runtime architecture.

Container deployment definitions must not become a duplicate store for:

- database semantics;
- MXM filesystem semantics;
- application configuration;
- semantic operation parameters.

Where configuration varies by substrate, that variation should be represented through the accepted MXM runtime/configuration model.

# 10. Secret Contract

The MXM secret invariant remains:

```text
No persisted cleartext secrets outside accepted secret stores.
```

Containerised application execution may require a different delivery mechanism from native process execution.

Possible future mechanisms include:

- mounted secret files;
- Docker secrets;
- transient runtime injection;
- runtime-specific secret backends.

However:

> Application code continues to consume secrets through the accepted MXM runtime and secret interfaces.

Application code must not become aware that a secret originated from Docker, Prefect, gopass, or another infrastructure mechanism unless that distinction is itself part of the accepted secret abstraction.

No cleartext secrets may be committed into:

- container images;
- deployment YAML;
- Compose files;
- repository configuration;
- generated persistent `.env` files.

# 11. Filesystem and Data Contract

A container has no implicit right to access the host filesystem.

Any required durable filesystem access must be explicit.

A containerised flow may access:

- configured MXM data roots;
- databases;
- object stores;
- network storage;
- source repositories;
- other declared runtime resources.

Filesystem-backed storage may be exposed through explicit mounts where appropriate.

Paths must be resolved through MXM runtime configuration rather than relying on accidental host properties such as:

```text
Path.home()
```

or undeclared host directory layouts.

Durable application state must be written through accepted MXM storage boundaries.

# 12. Database Access

Containerised execution may require network access to MXM databases.

The deployment must make that connectivity explicit.

A container must not change application database semantics merely because:

```text
localhost
```

inside the container no longer identifies the host database.

Differences in network location belong to runtime/substrate configuration.

Application code continues to consume the configured database boundary supplied through normal composition.

# 13. Semantic State

Containers do not own semantic state.

MXM semantic state remains governed by:

```text
docs/concepts/semantic-state-protocol.md
```

A containerised operation must preserve the same guarantees as native execution:

- semantic identity;
- explicit lineage;
- domain acceptance;
- discovery;
- safe re-entry;
- durable commit.

A container may disappear at any point.

Semantic correctness must therefore not depend on container persistence.

# 14. Prefect Execution State

Container lifecycle is operational execution state.

Prefect may record:

- worker identity;
- flow run;
- task run;
- infrastructure state;
- container startup;
- container failure;
- retry;
- timing;
- logs.

These remain Prefect concerns.

Container identity does not become semantic identity.

A retry in a new container is semantically equivalent to a retry in another local process: the MXM operation determines correct behaviour from durable semantic state.

# 15. Durable Outputs

A flow container may emit two broad categories of output.

## Semantic outputs

Examples:

- database state;
- datasets;
- semantic metadata;
- semantic references;
- accepted domain results.

These are owned by MXM.

They must persist through declared durable stores.

## Operational outputs

Examples:

- Prefect logs;
- run state;
- timings;
- operational artifacts.

These are owned by Prefect.

Neither category should depend on retaining the execution container after completion.

# 16. Container Lifecycle

Containerised MXM flow execution should assume ephemeral runtime containers.

Conceptually:

```text
create container
→ construct MXM runtime
→ execute operation
→ persist durable outputs
→ report execution state
→ exit
→ remove container
```

Retention of failed containers may be useful temporarily for debugging but must not become part of application correctness.

# 17. Parallelism and Ownership

Container execution does not alter the semantic ownership rules for parallel work.

The preferred alignment remains:

```text
parallelism unit
=
retry unit
=
independent semantic ownership unit
```

Multiple containers must not concurrently mutate the same semantic ownership unit unless the MXM application provides the required concurrency and consistency guarantees.

Container isolation alone does not provide semantic isolation.

# 18. Future Immutable Runtime Images

If MXM adopts containerised production execution, immutable runtime images are the likely operational target.

Such an image should eventually contain:

- explicitly versioned MXM application packages;
- pinned Python dependencies;
- required system dependencies;
- compatible Prefect runtime support;
- no embedded mutable application state;
- no embedded secrets.

Image identity may then become useful supporting deployment provenance.

Image identity must not replace application semantic provenance or lineage.

The exact image versioning and artifact-promotion system is intentionally deferred until container execution is required.

# 19. Future Artifact Infrastructure

Containerised execution may eventually justify:

- a private Python package index;
- an OCI/container registry;
- mirrored base images;
- controlled artifact promotion;
- signed images;
- reproducible build processes.

These capabilities are not V1 prerequisites.

They should be introduced in response to concrete deployment and supply-chain requirements rather than pre-built speculatively.

# 20. Current Prefect Container Contract

The current implemented container boundary is the Prefect control plane.

Its contract is:

```text
Docker Compose
    ↓
Prefect PostgreSQL
Redis
Prefect server
Prefect services
    ↓
persistent orchestration state
    ↓
Prefect API
```

The control plane interacts with native process workers through the Prefect API.

Application code does not execute inside these infrastructure containers.

# 21. Explicit Non-Goals for V1

V1 does not require:

- Docker-worker flow execution;
- one container per flow run;
- baked MXM runtime images;
- an OCI registry;
- a private package registry;
- Kubernetes;
- cloud execution;
- duplicate container-compatible secret infrastructure;
- replication of the `monolith` filesystem into containers;
- containerisation as a condition of production readiness.

These remain available future options.

# Design Test

Before introducing container execution for an MXM application, ask:

```text
What concrete capability does the container boundary provide
that the controlled process runtime does not?
```

Examples of satisfactory answers might be:

```text
remote execution
immutable deployable artifact
dependency isolation
security boundary
horizontal scaling
cloud portability
```

If the answer is merely:

```text
containers feel more production-like
```

the additional architecture is not justified.

# Core Invariants

```text
The Prefect control plane is containerised.

V1 MXM application execution uses process workers on controlled monolith.

Containerisation is an optional execution backend, not an application requirement.

Changing execution substrate must not change semantic meaning.

Containerised operations still use RuntimeIdentity → RuntimeContext → composition.

Containers are disposable compute.

Durable semantic state lives outside execution containers.

Container identity and lifecycle are operational state, not semantic state.

Configuration, secrets, filesystem access, and networking must be explicit at a
container boundary.

Application code continues to use accepted MXM runtime/configuration/secret interfaces.

Container infrastructure is introduced in response to concrete requirements,
not as speculative production architecture.
```

# Summary

The current Money Ex Machina architecture uses containers where they already provide a clear operational benefit:

```text
long-running Prefect control plane
→ containerised
```

and uses the controlled host environment where reproducing that environment inside a container would currently add unnecessary complexity:

```text
MXM application execution
→ process worker on monolith
```

If future requirements justify containerised flow execution, the container becomes an explicit disposable-compute boundary around the same MXM application contract.

Until then, process execution on `monolith` is the complete and accepted V1 runtime model.
