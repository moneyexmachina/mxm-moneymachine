# Container Contract

## Purpose

This document defines the MXM container contract for Prefect Docker worker execution.

The contract specifies how runtime containers receive code, configuration, secrets,
data access, and output channels when executing `mxm-moneymachine` flows.

The policy applies to Docker-worker based Prefect flow runs.

# Core Principle

A flow container is disposable compute.

Each container receives all required runtime inputs explicitly and persists durable
outputs only through declared MXM storage interfaces.

The container boundary is therefore an explicit runtime contract.

# Runtime Inputs and Outputs

A Prefect Docker flow container interacts with the MXM system through five channels:

```text
code in
configuration in
secrets in
data access in/out
metadata and logs out
```

Each channel has a defined ownership model.

# Code Access

MXM distinguishes between development code access and production code access.

## Development Code Access

Development Docker deployments use a mounted local repository.

The local repository is mounted into the runtime container, and the container executes
the current checked-out source tree.

This supports:

- rapid iteration,
- local debugging,
- testing uncommitted or branch-local code,
- validating deployment semantics before publishing artifacts.

Development deployments may mount the repository directly from the host machine.

Example pattern:

```text
host repo path -> same path inside container
```

The current development work pool is:

```text
mxm-dev-docker
```

## Production Code Access

Production Docker deployments use baked runtime images.

A production runtime image contains:

- the MXM package,
- pinned package dependencies,
- the required Python runtime,
- the required Prefect runtime,
- any required system dependencies.

Production flow containers execute code installed in the image.

Production deployments should not rely on host-mounted source repositories.

The future production work pool is:

```text
mxm-prod-docker
```

## Future Sovereign Artifact Access

The long-term MXM direction is to support a sovereign artifact supply chain.

This may include:

- a private Python package index,
- a private OCI/container registry,
- mirrored base images,
- cached third-party wheels,
- controlled promotion of tested artifacts.

The staged code-access model is:

```text
development:
  mounted repository

local production-shaped:
  locally built MXM image

published production:
  baked image using pinned released packages

sovereign production:
  baked image from self-hosted package and container registries
```

# Configuration Access

Runtime configuration is divided into:

```text
non-secret configuration
secret configuration
```

Non-secret configuration includes:

- work pool names,
- deployment names,
- API URLs,
- mounted paths,
- image tags,
- dataset locations,
- runtime mode,
- machine/environment labels.

Non-secret deployment configuration may be stored in version-controlled YAML files
when the values are suitable for the public repository.

Environment-specific configuration may later be rendered from `mxm-config`.

# Secret Access

Secrets are retrieved dynamically at runtime.

The MXM secret invariant is:

```text
No persisted cleartext secrets outside gopass.
```

Secrets may be injected into containers through:

- transient environment variables,
- Docker secrets,
- Prefect secret blocks,
- MXM runtime secret loaders.

The source of truth for MXM secrets is `gopass`.

Committed deployment YAML must not contain secret values.

Generated files containing cleartext secrets are outside the accepted runtime policy.

# Data Access

Flow containers access durable data through explicit storage interfaces.

Development deployments may use mounted local data paths.

Production deployments may use:

- mounted server storage,
- network-attached storage,
- object stores,
- database connections,
- future table/catalogue layers.

Filesystem-backed stores are valid MXM storage surfaces.

Any filesystem path used by a flow must be resolved through MXM configuration.

A Docker deployment that uses filesystem-backed stores must explicitly mount the
required host paths into the container.

Production containers should use configured runtime roots rather than implicit
Path.home()-derived locations.

Containers must not depend on undeclared host filesystem access.

Data paths required by a deployment must be explicit in the deployment configuration
or resolved through MXM runtime configuration.

# Analytical Data Output

Analytical datasets are written through MXM dataset stores.

The current analytical data format is partitioned Parquet.

Dataset writes follow the publication discipline:

```text
write temporary output
validate output
publish atomically
record semantic metadata
```

Parallel writes must respect partition ownership.

The intended rule is:

```text
parallelism unit == ownership unit == writable partition
```

# Semantic Metadata Output

Semantic metadata includes:

- dataset attempts,
- idempotency keys,
- coverage records,
- failure classification,
- source lineage,
- dataset availability.

Semantic metadata is owned by MXM.

The current implementation may use SQLite for local development.

The production target is PostgreSQL-backed semantic metadata.

# Operational Metadata Output

Prefect receives operational metadata from flow runs.

This includes:

- flow run state,
- task run state,
- logs,
- artifacts,
- assets,
- timings,
- retry state.

Prefect operational metadata complements MXM semantic metadata.

# Network Access

Runtime containers may require network access to:

- Prefect API,
- vendor APIs,
- databases,
- object stores,
- artifact registries,
- internal services.

Network access must be explicit in deployment configuration or infrastructure policy.

Local Docker development may use:

```text
host.docker.internal
```

to reach services exposed on the host machine.

# Container Lifecycle

Docker-worker flow containers are ephemeral.

A container is created for a flow run, executes the flow, emits operational metadata,
persists durable outputs through declared stores, and exits.

Development deployments may remove containers automatically after completion.

Production deployments may retain failed containers or logs according to operational
debugging policy.

# Work Pool Semantics

MXM uses separate work pools for development and production-oriented execution.

Current development pools:

```text
mxm-dev-process
mxm-dev-docker
```

Future production pool:

```text
mxm-prod-docker
```

The development Docker pool uses mounted source repositories.

The production Docker pool uses baked runtime images.

The production pool should only be introduced once the baked-image runtime contract
is implemented and tested.

# Current Session 44 Status

Session 44 validated the development Docker container contract.

The tested path was:

```text
Prefect deployment
→ mxm-dev-docker work pool
→ Docker worker
→ ephemeral container
→ mounted local repository
→ flow execution
→ Prefect state/log output
→ container auto-removal
```

This proves the development execution substrate.

The production image contract remains a future implementation step.

# Open Questions

The following questions remain open:

- What is the first MXM baked runtime image structure?
- Which base image should production MXM runtime images use?
- How should MXM image versions relate to package versions and git commits?
- Which artifact registry should MXM use first?
- When should MXM introduce a self-hosted Python package index?
- When should MXM introduce a self-hosted OCI/container registry?
- How should production containers receive secrets beyond local development?
- How should production containers access durable data stores on `monolith`?
