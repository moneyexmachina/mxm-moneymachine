"""
Market Data Orchestration Core.

This module contains the **generic orchestration logic** for collecting,
updating, and auditing *instrument-scoped market data datasets* in MXM.

Its responsibility is to coordinate *what* data should be collected,
*when* it should be attempted, and *how* ingestion state is tracked —
without knowing anything about the *content* of the data itself.

The orchestration layer is intentionally agnostic to:
- vendor APIs and transport mechanics (handled in `vendors/`)
- storage backends and physical layout (handled in `stores/`)
- dataset-specific schemas, parsing, and completeness rules
  (handled in `datasets/<dataset_name>/`)

──────────────────────────────────────────────────────────────────────────────

Scope of responsibility
-----------------------

This module provides shared machinery for datasets that are:

- scoped to a set of instruments,
- collected over time (event streams or time-indexed windows),
- subject to retry, idempotency, and cost-aware ingestion,
- evaluated for coverage and completeness.

Concretely, it implements:

- generic window / range iteration and update policies
  (e.g. bootstrap vs incremental update, rechecking recent periods),
- attempt lifecycle management and status semantics
  (attempted, cached, ingested, partial, failed, etc.),
- coordination of vendor pulls, cache hits, and error handling,
- persistence-agnostic coverage snapshots and derived state,
- uniform decision logic for “should we attempt this now?”.

All dataset-specific behaviour is injected via *adapters* supplied by
individual datasets.

──────────────────────────────────────────────────────────────────────────────

What this module deliberately does NOT do
-----------------------------------------

This module does not:

- issue raw vendor API calls or define vendor request parameters
  (those live in `vendors/` and dataset adapters),
- define dataset schemas, row formats, or parsing logic,
- decide how or where data is physically stored,
- impose a single storage schema across datasets,
- perform any market modelling or data transformation.

These concerns are intentionally separated to preserve clear ownership
boundaries and to avoid premature generalisation.

──────────────────────────────────────────────────────────────────────────────

Relationship to other layers
----------------------------

- `vendors/`:
    Source-specific APIs, normalisation, cost estimation, and raw data access.

- `datasets/<name>/`:
    Dataset-specific adapters defining:
      - request construction,
      - payload parsing,
      - deduplication keys,
      - completeness predicates,
      - persistence layout,
      - dataset-specific inspection views.

- `stores/`:
    Concrete persistence backends (Parquet, SQLite, etc.).

- `orchestrators/`:
    Runtime entrypoints and product-level pipelines that invoke this
    orchestration core to run specific datasets or end-to-end workflows.

──────────────────────────────────────────────────────────────────────────────

Design intent
-------------

The orchestration layer exists to ensure that *all instrument-scoped datasets
share the same ingestion semantics*, auditability, and update behaviour.

By centralising this logic, MXM avoids silent divergence between datasets
and ensures that adding a new dataset is primarily a matter of implementing
a small, explicit adapter — not copy-pasting orchestration code.

This module is expected to grow conservatively and only when duplication
across datasets would otherwise threaten semantic consistency.
"""
