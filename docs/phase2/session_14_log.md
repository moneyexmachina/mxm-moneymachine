# Session 14 — Marketdata Semantic Hardening (Normative Closure)

**Project:** MXM V1  
**Phase:** Phase 2 — Market Data Completion  
**Session:** 14  
**Status:** Closed (normative semantics completed and proven)

## 1. Session framing

Session 14 began as a planned “final clarity pass” over the marketdata system prior to scaling and deployment. During execution, it became clear that the system had accumulated **semantic drift across layers**, particularly around:

- attempt status vocabularies,
- completeness semantics,
- vendor-final handling,
- and inspection rollups.

Rather than pushing forward with additional functionality, Session 14 deliberately expanded into a **semantic hardening session**. The goal was not to add features, but to ensure that the existing system has a *single, authoritative interpretation of truth* across ingestion, persistence, and inspection.

This session therefore serves as a **closure point for Phase 2 semantics**.

## 2. The semantic problem (pre-state)

Before Session 14, the system exhibited the following risks:

- Attempt status labels were **overloaded** and inconsistently interpreted across layers.
- “Completeness” was sometimes inferred implicitly rather than derived from a single canonical source.
- Vendor-final behaviour blurred the distinction between *partial availability* and *logical completeness*.
- Inspection layers risked re-deriving policy or semantics rather than projecting stored facts.
- Product- and system-level rollups had no formally enforced precedence rules.

These issues did not necessarily cause incorrect ingestion, but they **undermined trust** in the system’s reporting surfaces and created a latent risk of silent inconsistency as the system scaled.

## 3. Normative semantics (authoritative post-state)

Session 14 establishes the following **normative semantics**, now enforced in code and verified by proof.

### 3.1 Attempt ledger (persisted facts)

The attempt ledger (`ohlcv_1d_attempts`) is the **only source of persisted factual history**.

It records:
- what was attempted,
- under what constraints,
- with what outcome.

The **closed, authoritative attempt status vocabulary** is:

- `unmapped`
- `skipped_empty_expected_window`
- `complete`
- `dry_run`
- `skipped_cost_cap`
- `ingested`
- `incomplete`
- `error`

No other status values are permitted. This is enforced and verified.

`status_detail` is explanatory only and **never drives semantics**.

### 3.2 Derived state (non-persisted, internal)

A separate `DerivedState` vocabulary exists for **decision-making only** inside the orchestrator.

Derived state:
- is not persisted,
- is not surfaced directly,
- and must never leak into inspection logic.

This cleanly separates **facts** (what happened) from **policy** (what to do next).

### 3.3 Completeness semantics

**Completeness is not a status.**

Completeness is derived *only* from:

```
CoverageWindows.complete
```

which is computed from:
- the `ExpectedWindow`,
- and observed stored coverage.

No attempt status may override this truth.

Vendor-final is treated as:
- an explanatory flag,
- never as a substitute for completeness.

### 3.4 Vendor-final semantics

Vendor-final indicates that the vendor cannot supply additional data beyond the expected window.

This allows:
- partial-but-final ingestion to be *explained*,
- without asserting completeness where coverage does not support it.

Vendor-final **does not imply complete**.

### 3.5 Inspection layer contract

All inspection layers are **strict projections**:

- They may *read* the attempt ledger.
- They may *delegate* coverage computation to canonical builders.
- They must **never re-derive semantics or policy**.

This applies at:
- contract level,
- product level,
- and system level.

## 4. What was implemented

### 4.1 Orchestrators (writer surfaces)

- OHLCV-1D orchestrator rewritten to:
  - emit only authoritative attempt statuses,
  - isolate decision logic (`DerivedState → Decision`),
  - enforce exactly one attempt row per contract per run,
  - handle cost-cap, dry-run, and vendor-final paths explicitly.
- Sticky budget bugs resolved.
- Status and stage aggregation semantics aligned with the normative model.

Instrument definitions and instrument-definition mappings were verified to comply with the same discipline.

### 4.2 Coverage semantics

- `ExpectedWindow` is the sole authority for expected availability.
- Coverage builders compute:
  - observed windows,
  - completeness,
  - and vendor-final derivations.
- No layer re-implements coverage logic.

### 4.3 Inspection layer

- Contract inspection projects ledger rows into coverage models without inference.
- Product inspection applies explicit precedence rules:
  - `error` > `blocked` > `partial` > `done`.
- System inspection mirrors product logic exactly.
- All timestamps follow the `*_ts_utc` (string) → `*_ts` (parsed) convention.

## 5. Proofs (executed)

The following proofs were executed during Session 14:

### 5.1 Ledger integrity

- SQL verification confirms **no illegal status values** in `ohlcv_1d_attempts`.
- Exactly one attempt row per contract per run is recorded.

### 5.2 Dry-run behaviour

- Dry-run executions:
  - record `status = dry_run`,
  - perform no vendor calls,
  - mutate no stored data.

### 5.3 Cost-cap behaviour

- Cost caps correctly produce:
  - `skipped_cost_cap`,
  - without falsely marking completion,
  - and block product status as expected.

### 5.4 Vendor-final partial ingestion

- Vendor-final partial ingestion produces:
  - `status = ingested`,
  - `windows_complete = False`,
  - `vendor_final = True`.
- Product and system inspection correctly classify the product as `blocked` or `partial`, not `done`.

### 5.5 Inspection consistency

- Contract, product, and system inspection reports agree numerically.
- No contradictions exist between:
  - attempt status,
  - coverage windows,
  - and roll-up status.

All proofs were executed via CLI scripts and verified against persisted state.

## 6. Explicitly deferred work

The following items are intentionally deferred to later sessions (Phase 3):

- Universe-level (all-products) orchestrator.
- Expansion of the product universe (from ~5 to ~30–40 products).
- Deployment of a scheduled daily update job.
- Rich / styled CLI output for inspection reports.

These depend on upcoming work on **synthetic assets and price construction** and would dilute semantic focus if addressed earlier.

## 7. Session close

Session 14 closes the semantic hardening phase of marketdata ingestion.

At this point:
- attempt statuses are closed and enforced,
- completeness semantics are authoritative and provable,
- inspection layers are trustworthy projections,
- and the system is safe to use as an input to research, simulation, and P&L construction.

Phase 3 can now proceed without retrofitting risk.

**Session 14 is complete.**

