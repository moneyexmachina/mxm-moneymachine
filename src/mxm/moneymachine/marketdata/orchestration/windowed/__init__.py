"""
Windowed dataset orchestration.

This subpackage contains the **generic orchestration logic** for
instrument-scoped datasets whose expected data is defined over
*time windows* (e.g. daily bars, daily statistics).

A “windowed” dataset is characterised by:
- a known or derivable expected time interval per instrument,
- the ability to evaluate local coverage relative to that expectation,
- a notion of completeness that may be proven, disproven, or accepted as final,
- idempotent ingestion over bounded time windows.

──────────────────────────────────────────────────────────────────────────────

Responsibilities
----------------

The windowed orchestration layer provides:

- a shared state and decision model for windowed datasets
  (blockers, completeness, retryability, budget gating),
- a generic execution loop that iterates expected windows and coordinates
  ingestion attempts,
- dataset-agnostic policies for bootstrap vs incremental updates,
- a uniform vocabulary for derived states and decisions.

Dataset-specific behaviour is supplied via adapters, including:
- how expected windows are derived,
- how completeness is evaluated for a window,
- how ingestion is performed and persisted.

──────────────────────────────────────────────────────────────────────────────

What this subpackage does NOT do
-------------------------------

This subpackage does not:
- define vendor request parameters or execute raw vendor pulls,
- define dataset schemas or parsing logic,
- define storage layouts or persistence backends,
- implement dataset-specific completeness heuristics.

Those concerns remain owned by dataset adapters, vendor integrations,
and store backends respectively.

──────────────────────────────────────────────────────────────────────────────

Design intent
-------------

The purpose of this subpackage is to ensure that all windowed, instrument-scoped
datasets in MXM share the same orchestration semantics, retry behaviour,
and decision logic.

By centralising this logic, MXM avoids copy-paste orchestration code and
prevents silent divergence in ingestion semantics as new datasets are added.

This subpackage is expected to grow conservatively and only in response to
clear duplication or semantic drift across windowed datasets.
"""
