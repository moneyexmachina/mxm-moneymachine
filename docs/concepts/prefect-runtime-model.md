# Prefect Runtime Model

## Purpose

This note defines the runtime model used by `mxm-moneymachine` when orchestrating
flows with Prefect.

The purpose of the document is to describe:

- the structure of the runtime system,
- the responsibilities of each layer,
- the ownership boundaries between Prefect and MXM,
- the execution and deployment model used for local and production-shaped runtimes.

This document describes the current intended architecture and runtime semantics for
Session 44 and beyond.

# Core Runtime Model

MXM uses Prefect as an orchestration substrate for runtime execution.

The runtime system consists of four major layers:

```text
domain logic
→ Prefect flows and deployments
→ worker execution infrastructure
→ orchestration control plane
```

The overall execution chain is:

```text
deployment
→ work pool
→ worker
→ flow run
→ domain execution
→ durable MXM stores
```

Each layer has a distinct responsibility.

# Domain Logic

MXM domain logic contains the actual business and analytical behaviour of the system.

Examples include:

- marketdata collection,
- valuation logic,
- portfolio construction,
- dataset construction,
- risk calculations,
- data normalization,
- attempt metadata management.

Domain logic is intended to remain:

- testable,
- deterministic where appropriate,
- executable outside Prefect,
- separable from orchestration concerns.

The preferred structure is:

```text
domain function
→ thin Prefect wrapper
→ deployment
→ runtime execution
```

# Prefect Flows

Prefect flows define orchestration structure and runtime coordination.

Flows are responsible for:

- execution ordering,
- task dependency structure,
- runtime coordination,
- retries,
- scheduling,
- operational logging,
- infrastructure execution boundaries.

Flows coordinate domain operations but do not replace the domain model itself.

Flow implementations are located under:

```text
src/mxm/moneymachine/flows/
```

# Deployments

A deployment binds a flow to a concrete execution environment.

Deployments define:

- which flow should execute,
- deployment naming,
- work pool selection,
- execution image,
- mounted volumes,
- environment variables,
- runtime parameters,
- schedules,
- infrastructure-specific job variables.

MXM expresses deployments as deployment-as-code.

Deployment definitions are stored under:

```text
infra/prefect/deployments/
```

This separates:

```text
domain logic
deployment configuration
infrastructure stack configuration
```

into independently understandable layers.

Deployments are intended to be:

- version controlled,
- reproducible,
- non-interactive,
- scriptable,
- environment-aware.

# Work Pools

A work pool defines an execution contract.

The work pool specifies the type of infrastructure used to execute flow runs.

Initial MXM work pools include:

```text
mxm-dev-process
mxm-dev-docker
```

Future work pools may include:

```text
mxm-prod-docker
mxm-k8s
mxm-cloud
mxm-wildling
```

Different work pools may target different infrastructure while executing the same
logical deployment.

# Workers

Workers poll work pools and execute matching flow runs.

Workers translate Prefect orchestration state into actual runtime execution.

MXM currently uses two worker models:

## Process Workers

Process workers execute flow runs as local subprocesses.

This execution model is well suited to:

- local development,
- debugging,
- rapid iteration,
- smoke testing,
- direct interaction with the local Poetry environment.

## Docker Workers

Docker workers execute each flow run inside a dedicated Docker container.

This execution model provides explicit runtime structure for:

- runtime images,
- environment variables,
- mounted volumes,
- network topology,
- container lifecycle,
- dependency isolation,
- reproducible execution environments.

Docker workers form the primary production-oriented runtime model for MXM.

# Control Plane

The Prefect control plane consists of long-running orchestration services.

The control plane stores and coordinates operational runtime state.

The current local stack includes:

- Prefect API,
- Prefect UI,
- Prefect background services,
- PostgreSQL,
- Redis.

The control plane runs as a Docker Compose stack.

The control plane is responsible for:

- deployment registration,
- flow run coordination,
- task run coordination,
- schedules,
- worker coordination,
- orchestration metadata,
- operational logs,
- artifacts and assets.

# Infrastructure Stack

MXM defines long-running infrastructure services through Docker Compose.

The infrastructure stack currently lives under:

```text
infra/prefect/
```

Docker Compose defines:

- service topology,
- startup configuration,
- service dependencies,
- persistent volumes,
- networking,
- restart behaviour,
- container configuration.

The Compose stack provides the operational substrate on top of which Prefect
coordinates flow execution.

# Flow Runs

A flow run represents one execution of a deployment.

A flow run may:

- call vendor APIs,
- retrieve runtime configuration,
- retrieve runtime secrets,
- read and write datasets,
- update semantic metadata,
- emit operational logs,
- produce Prefect artifacts and assets.

Flow runs execute as infrastructure-connected runtime processes.

Flow runs may execute:

- locally,
- inside Docker containers,
- on remote workers,
- on future distributed infrastructure.

# Runtime Containers

Docker flow runs execute inside ephemeral runtime containers.

Runtime containers provide isolated execution environments for flow runs.

Containers receive:

- runtime images,
- mounted code access,
- mounted storage access,
- environment variables,
- runtime configuration,
- runtime secrets,
- network access.

Current local development deployments use mounted source repositories inside the
runtime container.

Future production deployments may use:

- baked runtime images,
- pinned package versions,
- git retrieval,
- object-store-based runtime packaging.

# Runtime Configuration

MXM distinguishes between:

```text
non-secret configuration
runtime secrets
```

Non-secret runtime configuration includes:

- repository paths,
- work pool names,
- deployment configuration,
- runtime topology,
- storage locations,
- image tags,
- runtime environment selection.

Secrets are retrieved dynamically at runtime.

The intended secret flow is:

```text
gopass
→ runtime extraction
→ transient environment injection
→ worker/container runtime
```

Secrets are never to be persisted in committed files.

# Runtime State Ownership

The runtime system distinguishes between:

```text
operational orchestration state
semantic MXM state
```

## Prefect Operational State

Prefect operational state includes:

- deployments,
- flow runs,
- task runs,
- schedules,
- worker state,
- orchestration logs,
- artifacts,
- assets.

## MXM Semantic State

MXM semantic state includes:

- dataset attempts,
- coverage metadata,
- idempotency metadata,
- data availability,
- valuation semantics,
- dataset lineage,
- marketdata semantics,
- analytical datasets.

Both state surfaces may eventually share infrastructure services such as PostgreSQL
while remaining conceptually distinct.

# Storage Model

The current intended storage model is:

```text
orchestration metadata  -> Prefect PostgreSQL database
semantic metadata       -> SQLite initially, PostgreSQL target
analytical datasets     -> partitioned Parquet datasets
```

Dataset ownership follows a single-writer discipline aligned with the runtime
parallelism model.

The current data layer emphasizes:

- deterministic dataset construction,
- explicit ownership,
- partition-oriented writes,
- reproducible rebuild behaviour.

# Parallelism Model

MXM distinguishes between:

```text
flow-level parallelism
task-level parallelism
```

## Flow-Level Parallelism

Flow-level parallelism consists of multiple flow runs executing concurrently across
workers.

Examples include:

```text
one marketdata flow per product
multiple concurrent backtests
parallel dataset builds
```

## Task-Level Parallelism

Task-level parallelism consists of concurrent execution inside a single flow run.

Examples include:

```text
parallel contract collection
parallel processing steps inside one product flow
```

The storage model and partition ownership strategy are intended to align with these
parallel execution surfaces.

# Local Session 44 Milestone

Session 44 established the first fully operational local orchestration substrate for
MXM.

The following execution chains were successfully validated.

## Process Worker Runtime

```text
CLI
→ Prefect API
→ deployment
→ process worker
→ local flow execution
```

## Docker Worker Runtime

```text
CLI
→ Prefect API
→ deployment
→ Docker work pool
→ Docker worker
→ ephemeral runtime container
→ mounted repository
→ successful flow execution
→ automatic container removal
```

This established a working foundation for future marketdata orchestration flows.

# Open Questions

The following architectural questions remain open.

## Code Distribution

Future production runtime execution may use:

- mounted repositories,
- baked runtime images,
- package installation,
- git retrieval,
- object-store-based packaging.

The long-term production model remains under evaluation.

## Deployment Templating

Deployment configuration currently uses concrete deployment YAML definitions.

Future deployment generation may integrate with:

- `mxm-config`,
- machine-aware runtime configuration,
- environment-aware deployment rendering.

## Semantic Metadata Integration

The relationship between:

- Prefect assets and artifacts,
- MXM semantic attempt metadata,

remains under evaluation.

## Metadata Storage Evolution

The long-term migration path from SQLite-based semantic metadata stores toward
PostgreSQL-backed metadata infrastructure remains under evaluation.

## Table Metadata Layer

Future evaluation may introduce a metadata layer such as Iceberg above partitioned
Parquet datasets.
