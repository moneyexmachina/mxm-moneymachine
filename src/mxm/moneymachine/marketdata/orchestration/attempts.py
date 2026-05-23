"""
Generic attempt ledger for dataset orchestration.

This module defines the **orchestration-level abstraction** for recording,
querying, and reasoning about ingestion attempts for datasets.

An “attempt” represents a single, auditable decision point where MXM
considered ingesting data for a specific (dataset scope, unit/window)
and either:
- executed an ingest,
- skipped execution (policy, budget, completeness),
- was blocked by a precondition,
- or failed with an error.

──────────────────────────────────────────────────────────────────────────────

Responsibilities
----------------

This module defines:
- the *concept* of an attempt and its canonical lifecycle,
- the minimal, dataset-agnostic fields required for orchestration decisions,
- a stable API (port) used by the orchestration core to:
    - record attempt start and completion,
    - retrieve the latest attempt outcome for a unit,
    - reason about recent failures for retry policy enforcement.

The attempt ledger is an **authoritative audit surface** for orchestration:
once an attempt outcome is recorded here, orchestration decisions must be
derivable from it without consulting dataset-specific logic.

──────────────────────────────────────────────────────────────────────────────

What this module does NOT do
---------------------------

This module does not:
- define dataset-specific schemas or extra attempt metadata,
- define how attempts are physically stored (SQLite, etc.),
- define how completeness is evaluated,
- perform vendor calls or data ingestion,
- implement retry or decision logic itself.

Those concerns live respectively in:
- dataset adapters,
- store backends,
- completeness/coverage semantics,
- the orchestration state and decision modules.

──────────────────────────────────────────────────────────────────────────────

Relationship to datasets and stores
-----------------------------------

This module defines the *port* used by orchestration.

Concrete persistence is provided by backends (e.g. SQLite) that implement
this port. Dataset adapters may:
- provide dataset-specific scope/unit keys,
- attach additional dataset-specific metadata,
- choose which backend/table namespace to use.

However, datasets must not redefine the meaning of attempt status or
attempt lifecycle. All datasets share the same attempt semantics.

──────────────────────────────────────────────────────────────────────────────

Design intent
-------------

The purpose of this module is to:
- eliminate copy-pasted attempt tracking across datasets,
- ensure uniform retry, blocking, and audit semantics,
- make orchestration behaviour explainable and inspectable.

By centralising the attempt vocabulary and API, MXM ensures that adding a
new windowed dataset does not silently introduce divergent ingestion logic.

This module intentionally precedes implementation: its API defines
architectural ownership before any storage backend is written.
"""
