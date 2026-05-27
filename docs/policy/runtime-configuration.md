# Runtime Configuration Policy

## Purpose

This document defines how `mxm-moneymachine` handles runtime configuration.

The policy applies to operational code, flows, scripts, infrastructure wrappers, and
containerized execution.

# Core Principle

Runtime configuration must be explicit, injectable, and inspectable.

Operational code should receive runtime values through configuration or request
objects rather than hidden module-level constants.

# Configuration Surfaces

MXM distinguishes between:

```text
domain parameters
runtime configuration
secrets
derived runtime state
```

## Domain Parameters

Domain parameters describe the work being requested.

Examples:

- product id
- dataset name
- ingestion mode
- cost cap
- window size
- requested end timestamp

These belong on explicit request objects.

## Runtime Configuration

Runtime configuration describes the environment in which the work executes.

Examples:

- data root
- cache root
- store backend
- API endpoint
- work pool name
- deployment mode
- secret paths
- mounted container paths

These should be supplied through `mxm-config` or explicit runtime config objects.

## Secrets

Secrets are values required for runtime access.

Examples:

- API keys
- database passwords
- registry credentials

Secret values are retrieved through `mxm-secrets` from `gopass`.

Secret values must not be committed or persisted as cleartext configuration files.

## Derived Runtime State

Derived runtime state is discovered at execution time.

Examples:

- Prefect flow run id
- task run id
- worker name
- deployment id
- runtime timestamp

This belongs in `ExecutionContext`.

# Module-Level Constants

Module-level constants may be used for true static facts.

Examples:

```python
DEFAULT_WINDOW_DAYS = 31
DEFAULT_OVERLAP = "1d"
```

Module-level constants should not be used for machine-, user-, environment-, or
secret-specific configuration.

Discouraged:

```python
DATABENTO_SECRET_PATH = "mxm/dev/databento/api-key"
```

Preferred:

```python
request.databento_api_key_secret_path
```

or:

```python
runtime_cfg.vendors.databento.api_key_secret_path
```

# Request Objects

Operational functions should receive explicit request objects.

Example:

```python
@dataclass(frozen=True, slots=True)
class InstrumentDefinitionsRunRequest:
    product_id: str
    mode: Mode
    cost_cap_usd: float
    databento_api_key_secret_path: str
```

Request objects make runtime dependencies visible and testable.

# Future Direction

The long-term source of runtime configuration is:

```text
mxm-config
```

The long-term source of secrets is:

```text
mxm-secrets / gopass
```

The intended runtime path is:

```text
mxm-config resolves non-secret runtime config
mxm-secrets resolves secret values at runtime
ExecutionContext records execution provenance
domain code receives explicit request/config/context objects
```

# Container Implication

Containerized flows must receive all required runtime configuration explicitly.

A container may receive configuration through:

- deployment job variables,
- mounted configuration files,
- environment variables,
- rendered non-secret runtime config,
- `mxm-config` loaders.

Secrets are injected separately through the accepted secret runtime path.

# Policy Summary

```text
No hidden runtime configuration.
No persisted cleartext secrets.
No environment-specific module globals.
Runtime values flow through explicit config, request, secret, and execution-context surfaces.
```
