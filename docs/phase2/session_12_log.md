# MXM V1 — Session 12 Log
# Topic: OHLCV-1D Accounting, Completeness Semantics, and Retry Policy
# Status: COMPLETE
# Date: 2026-01-26

## 1. Session intent (recap)

Session 12 was scoped as an *accounting and semantics* session, not an ingestion rewrite.

The objective was to make OHLCV-1D ingestion:
- auditable,
- deterministic,
- retry-safe,
- and explainable at the contract level,

so that higher-level orchestration (Session 13+) can reason about completeness without ambiguity.

The session plan defined this in terms of:
- expected windows,
- vendor availability,
- materialised coverage,
- ingest attempts,
- and derived status.

This session is now closed with those goals met, with one notable (and positive) simplification.

## 2. What was delivered

### 2.1 Expected window formalised and enforced

**Achieved**

- Expected windows are now a first-class *derived concept*:
  - clamped to vendor dataset availability,
  - aligned to contract lifecycle,
  - consistently reused across:
    - completeness checks,
    - dry-run reporting,
    - retry decisions.

This satisfies Plan §5.1 in full.

### 2.2 Ingest attempt ledger (auditable surface)

**Achieved (with a cleaner implementation than originally planned)**

Instead of a new bespoke “ledger” table, the session introduced:

- `ohlcv_1d_attempts` as an **append-only attempt store**, capturing:
  - contract identity,
  - vendor request window,
  - stored coverage *before* the attempt,
  - derived status and status_detail,
  - vendor_final signal,
  - cost estimates and actual cost,
  - error classification (if any),
  - run timestamp.

This achieves *all* of the accounting goals in Plan §5.3 and §9.1 while:
- avoiding duplication of data already stored by `mxm-dataio`,
- preserving a strict separation between:
  - vendor payload storage,
  - orchestration-level reasoning.

**Conclusion:**  
The plan’s intent is satisfied; the concrete design is better than originally specified.

### 2.3 Deterministic completeness derivation (`derive_state`)

**Achieved**

A pure, test-covered derivation function now classifies each contract deterministically based on:

- mapping availability,
- expected window emptiness,
- current coverage snapshot,
- vendor finality,
- operator intent (`reset_local`),
- latest attempt outcome (errors, budget skips).

Key properties:
- Coverage dominates history.
- Vendor-final partials are treated as terminal *unless* explicitly overridden.
- `reset_local` is a **hard operator override**, even against complete coverage.

This directly fulfils Plan §3.3, §6, and §7.

### 2.4 Correct resolution of “incomplete” ambiguity

**Achieved (and clarified beyond the plan)**

The original plan distinguished several “incomplete” classes.  
In practice, the session converged on a simpler and more robust rule:

- **`ingested`** now covers:
  - fully complete coverage (`ingested_complete`)
  - vendor-final partial coverage (`vendor_final_partial_done`)
- **`complete`** is reserved for *pre-existing* completeness
- **`incomplete`** is reserved exclusively for:
  - retryable, non-vendor-final cases

This removes the semantic overload that originally motivated Session 12.

The result:
- No contract that is “as complete as it will ever be” remains labelled incomplete.
- Update mode decisions become trivial and safe.

This exceeds the clarity target of Plan §2 and §6.

### 2.5 Retry and budget semantics validated

**Achieved**

- Cost caps are enforced strictly and deterministically.
- `skipped_cost_cap` propagates into derived state.
- Retryability is determined solely by:
  - vendor finality,
  - completeness,
  - and explicit operator intent.

Dry-run, cost-cap, and retry logic are now orthogonal and composable.

### 2.6 Dry-run semantics corrected and validated

**Achieved**

Dry-run behaviour now correctly:
- scans existing parquet coverage,
- reports accurate stored_min / stored_max / row_count,
- suppresses vendor calls,
- respects `reset_local` (showing empty coverage when forced).

This makes dry-run a **true planning and inspection tool**, rather than a misleading no-op.

This satisfies Plan §4 and §8 implicitly, even though dry-run was not originally a focus.

### 2.7 End-to-end validation runs

**Achieved**

The following were successfully exercised:

- bootstrap runs with:
  - partial historical coverage,
  - vendor-final limits,
  - controlled cost caps,
- re-runs showing correct `complete_before`,
- dry-run vs non-dry-run parity,
- `reset_local` forcing re-ingest correctly,
- idempotent behaviour after completion.

The system now converges cleanly without silent stalls or infinite retries.

## 3. Comparison to Session-12 plan

| Plan item | Status | Notes |
|---------|--------|------|
| Expected window formalisation | ✅ | Implemented exactly as intended |
| Ingest attempt accounting | ✅ | Achieved via `ohlcv_1d_attempts`, cleaner than planned |
| Deterministic completeness | ✅ | Implemented and test-covered |
| Retry semantics | ✅ | Correctly separated from completeness |
| Vendor-limited finality | ✅ | Explicit and enforced |
| Client-facing inspection | ⚠️ Deferred | Data surfaces exist; thin API can be added later |
| Cross-dataset generalisation | 🚫 | Explicitly deferred as planned |

## 4. What Session 12 *did not* do (by design)

- No product-level meta-orchestrator
- No cross-dataset abstraction
- No ingestion optimisation
- No schema redesign

These remain cleanly staged for Session 13.

## 5. Session 12 exit statement

Session 12 is **successfully closed**.

The OHLCV-1D dataset now has:
- auditable ingest history,
- unambiguous completeness semantics,
- deterministic retry behaviour,
- operator-controllable overrides,
- and truthful dry-run inspection.

This unblocks product-level orchestration with no hidden failure modes.

Proceed to **Session 13**.

