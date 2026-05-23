"""
MXM V1 — daily_stats Dataset
============================

The `daily_stats` dataset is a deterministic, materialized daily surface
derived from the `statistics_1d` event stream.

It is **not** a vendor-ingestion dataset. It performs no external data
collection, cost management, retry logic, or backfill orchestration.
Instead, it transforms upstream event data into a canonical daily
settlement surface suitable for downstream trading logic.

Conceptual Role
---------------

`daily_stats` forms the semantic bridge between:

    statistics_1d  (event stream, multiple rows per trading date)

and

    daily trading surfaces (exactly one row per trading date)

It converts an event-level dataset into a daily-level surface using a
versioned, deterministic selection rule.

Core Properties
---------------

- Deterministic: identical upstream input produces identical output.
- Idempotent: repeated materialization without upstream change yields
  byte-identical parquet output.
- Versioned: selection logic is explicitly versioned.
- Auditable: build metadata records upstream fingerprint, output fingerprint,
  and diagnostic summaries.
- Purely derived: no vendor calls, no retry semantics, no cost awareness.

Data Model
----------

Input:
    statistics_1d rows where stat_type == settlement

Output:
    One row per trading_date per instrument, selected via a
    deterministic ordering rule.

Each output row includes:
    - identity fields (publisher_id, instrument_id, trading_date)
    - selected settlement value
    - provenance fields (sequence, ts_event, is_final)
    - selection diagnostics (counts, tie-break flags)
    - selection_rule_version

Architecture
------------

The dataset module is structured as a materialized view layer:

    selection.py        Deterministic event selection logic
    builder.py          Surface construction
    store.py            Parquet IO and fingerprinting
    coverage.py         Daily surface window semantics
    builds_store.py     Materialization metadata (lineage + diagnostics)

Inspection and CLI dispatch integrate with the unified
`marketdata_inspect` interface, but operate purely on stored
metadata and surface files.

Strategic Significance
----------------------

`daily_stats` is the canonical settlement layer for:

    - InstrumentSeries
    - Synthetic assets
    - Portfolio construction
    - Backtesting

It represents the first derived dataset in MXM V1 and marks the
transition from vendor ingestion plumbing to semantic surface
construction.
"""
