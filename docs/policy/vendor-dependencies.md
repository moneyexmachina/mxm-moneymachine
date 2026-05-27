# Vendor Dependency Policy

## Purpose

This document defines the policy governing external vendor dependencies inside
`mxm-moneymachine`.

The goal is to distinguish clearly between:

- vendor-owned APIs and schemas,
- MXM-owned semantic abstractions,
- stable normalization boundaries,
- operational runtime dependencies.

# Core Principle

MXM should not construct artificial abstraction layers over vendor APIs unless a
real semantic or operational boundary exists.

Vendor-specific modules may depend directly on vendor libraries and types.

# Current V1 Position

MXM V1 marketdata ingestion is intentionally built around:

```text
Databento
```

Databento is therefore treated as:

- a selected infrastructure dependency,
- a stable vendor integration surface,
- a first-class runtime dependency of `mxm-moneymachine`.

Direct dependency on the Databento Python client is therefore acceptable.

# Avoiding False Abstractions

The project should avoid creating partial structural replicas of vendor APIs solely
to appear vendor-neutral.

Examples of discouraged patterns include:

- recreating vendor client interfaces as local protocols,
- wrapping entire vendor APIs without semantic transformation,
- rebuilding vendor data models locally,
- introducing indirection without an independent semantic boundary.

These patterns create:

- duplicated maintenance burden,
- fragile typing layers,
- conceptual ambiguity,
- false portability,
- degraded readability.

# Correct Abstraction Boundary

The preferred MXM boundary is:

```text
vendor API
→ MXM normalization
→ MXM semantic datasets
→ MXM stores
→ MXM economic systems
```

Abstractions should be introduced only after normalization into MXM-owned semantics.

# Vendor-Specific Modules

Vendor-specific modules may depend directly on vendor libraries.

Examples include:

```text
marketdata/vendors/databento/*
marketdata/ops/instrument_definitions.py
vendor-specific ingestion logic
vendor-specific cost estimation
vendor-specific metadata discovery
```

These modules are expected to import vendor types directly.

Example:

```python
import databento as db

client: db.Historical
```

This is considered correct and intentional.

# MXM-Owned Semantic Layer

MXM abstractions begin after data has crossed the vendor boundary.

Examples of valid MXM-owned abstractions include:

- normalized event schemas,
- canonical timestamps,
- dataset contracts,
- semantic attempt records,
- watermark semantics,
- business calendars,
- curated valuation surfaces,
- economic datasets,
- partition ownership semantics.

These abstractions are stable even if vendor integrations change.

# Multi-Vendor Future

Future multi-vendor support is expected to emerge through:

```text
multiple vendor adapters
→ normalization into MXM semantic forms
```

rather than through a universal abstract marketdata client API.

The intended future architecture is:

```text
vendor-specific ingestion
→ MXM normalization layer
→ shared semantic datasets
```

rather than:

```text
one generic client API for all vendors
```

# Typing Policy

Type annotations should accurately reflect real ownership and dependency structure.

If a module is Databento-specific, it should use Databento types directly.

Example:

```python
client: db.Historical
```

rather than:

```python
client: InstrumentDefinitionsClient
```

when the protocol merely reconstructs a subset of the Databento API.

# Operational Dependency Policy

Operational runtime systems are permitted to depend directly on:

- Prefect,
- Databento,
- SQLite,
- Postgres,
- Docker,
- Redis,
- other explicitly selected infrastructure dependencies.

MXM should maintain semantic ownership over:

- lifecycle logic,
- correctness guarantees,
- dataset semantics,
- idempotency,
- normalization policy,
- execution semantics,
- operational provenance.

# Stability Principle

MXM should minimize unnecessary abstraction layers while aggressively protecting:

- semantic ownership,
- reproducibility,
- operational correctness,
- deterministic rebuildability,
- durable economic meaning.

Abstractions are introduced when they encode durable semantic structure, not merely
to hide third-party APIs.

# Session 44 Position

Session 44 establishes the following operational simplification policy:

```text
Databento-specific modules use Databento types directly.
```

The earlier protocol-based abstraction layer around Databento client surfaces is being
removed because it duplicated vendor API structure without introducing meaningful MXM
semantic separation.
