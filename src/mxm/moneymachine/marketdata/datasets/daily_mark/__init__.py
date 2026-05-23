"""
MXM V1 — daily_mark Dataset
===========================

The `daily_mark` dataset is a deterministic, policy-curated daily valuation
surface defined on the MXM business calendar.

It is **not** a source-near vendor dataset, and it is **not** a direct
projection of any single upstream daily surface. Instead, it expresses MXM's
authoritative judgement of the best available daily valuation mark for each
(contract_id, session) pair under an explicit and deterministic policy.

Conceptual Role
---------------

`daily_mark` forms the semantic bridge between:

    trading-session-aligned source surfaces
    (e.g. daily_stats and other upstream daily datasets)

and

    MXM business-session-aligned economic processes
    (valuation, daily PnL, backtesting, attribution)

It converts source-near daily observations into a canonical valuation surface
on MXM business-session support.

Core Properties
---------------

- Deterministic: identical upstream inputs and calendar inputs produce
  identical output.
- Idempotent: repeated materialization without input change yields identical
  dataset content.
- Policy-driven: mark assignment follows an explicit source hierarchy and
  carry-forward rule.
- Auditable: source class, quality class, carry state, and provenance are
  recorded explicitly.
- Business-session-based: rows are keyed by MXM business sessions rather than
  exchange trading sessions.

Data Model
----------

Input:
    Upstream daily source surfaces and MXM business-session support.

Output:
    One row per (contract_id, session), where `session` is an MXM business
    session label.

Each output row includes:
    - identity fields (contract_id, session)
    - authoritative valuation mark (`mark_px`)
    - mark provenance and quality fields
    - carry state and carry streak information
    - optional upstream lineage fields for audit and debugging

Construction Principle
----------------------

`daily_mark` is built independently per contract over ascending MXM business
sessions.

For each session, MXM applies a deterministic mark-selection policy:

    1. use an acceptable same-session settlement-derived mark if available
    2. else use an acceptable same-session close-derived mark if available
    3. else carry forward the prior authoritative daily_mark if one exists
    4. else mark the session as unavailable

This makes missingness and degraded source coverage an explicit modeled state
rather than an implicit runtime failure.

Architecture
------------

The dataset module is structured as a curated valuation layer:

    builder.py          Business-session mark construction logic
    store.py            Parquet IO and surface persistence
    orchestrator.py     Build coordination over contracts / ranges
    inspect.py          Inspection and diagnostics for stored surfaces

Additional helper modules may separate source classification, projection, and
policy logic as needed.

Inspection and CLI dispatch integrate with the unified
`marketdata_inspect` interface, but operate on stored surfaces and explicit
dataset metadata rather than raw source datasets.

Strategic Significance
----------------------

`daily_mark` is the canonical daily valuation layer for:

    - mark-to-market valuation
    - daily PnL construction
    - synthetic asset backtesting
    - attribution and downstream reporting

It represents the transition from source-aligned market data surfaces to
business-session-aligned valuation policy in MXM V1.
"""
