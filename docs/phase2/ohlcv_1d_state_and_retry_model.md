# MXM V1 — OHLCV-1D State & Retry Model (Phase 2)

**Status:** Draft  
**Scope:** Phase 2 — Market Data Completion  
**Applies to:** `datasets/ohlcv_1d` orchestrator and meta-orchestrator  
**Introduced in:** S12.2

## 1. Purpose

This document defines the **derived state model** and **retry decision logic** for
OHLCV-1D ingestion in MXM V1.

The goal is to separate:

1. **Observed outcomes** (attempt ledger rows),
2. **Derived operational state** (small, stable, policy-relevant),
3. **Execution decisions** (attempt, noop, stop).

This separation ensures:
- deterministic behaviour,
- idempotent retries,
- clean reasoning about partial data, vendor limits, and failures.

## 2. Background

Each orchestrator run records **exactly one attempt row per contract considered**
in the append-only `ohlcv_1d_attempts` ledger.

Attempt rows record:
- expected window surfaces,
- coverage snapshots,
- outcome status,
- vendor finality,
- error information (if any).

The **derived state** is computed from:
- the latest attempt (if any),
- the current expected window,
- the current storage coverage.

The derived state drives retry behaviour.

## 3. Action Space (Minimal)

All orchestration decisions reduce to one of:

- `noop` — take no ingestion action for this contract
- `attempt_ingest` — attempt vendor ingestion
- `stop_run` — stop the orchestrator run (systemic failure)

These actions are produced by a decision function and executed by the orchestrator.

## 4. Derived State Vocabulary

The system uses a **small, stable derived state enum**.

These states are **policy-level concepts** and should remain stable even if
low-level attempt statuses evolve.

### 4.1 State Definitions

#### DONE

> No further ingestion action is possible or necessary under current surfaces.

Includes:
- fully complete coverage, or
- partial coverage where `vendor_final == true`.

Action: `noop`

#### BLOCKED_UNMAPPED

> The contract cannot be ingested because no vendor mapping exists.

This is not an error condition.

Action: `noop`

#### BLOCKED_EMPTY_EXPECTED

> The expected window is empty after intersecting:
> interest × dataset availability × lifecycle.

There is nothing to ingest.

Action: `noop`

#### NEEDS_INGEST

> Further vendor ingestion may improve coverage.

Includes:
- no coverage,
- partial coverage with `vendor_final == false`,
- first-time attempts,
- dry-run observations,
- budget-skipped attempts.

Action: `attempt_ingest`

#### RETRYABLE_ERROR

> A previous ingestion attempt failed due to a transient operational error.

Examples:
- network timeouts,
- temporary vendor API failures,
- transient database locks.

Action: `attempt_ingest` (subject to retry policy)

#### FINAL_ERROR

> A non-recoverable failure under current assumptions.

Examples:
- repeated identical failures exceeding retry limits,
- vendor-final expected window with persistent failure,
- schema incompatibility,
- corrupted local storage.

Action:
- `noop` (per-contract), or
- `stop_run` if classified as systemic.

#### SKIPPED_BUDGET

> Ingestion was skipped due to run-level budget constraints.

This is not a data state and does not imply completion.

Action: `noop` (eligible in future runs)

#### UNKNOWN

> State derivation failed or invariants were violated.

This indicates a bug or corruption.

Action: `stop_run`

## 5. Derived State → Action Mapping

| Derived State | Default Action |
|--------------|----------------|
| DONE | `noop` |
| BLOCKED_UNMAPPED | `noop` |
| BLOCKED_EMPTY_EXPECTED | `noop` |
| SKIPPED_BUDGET | `noop` |
| NEEDS_INGEST | `attempt_ingest` |
| RETRYABLE_ERROR | `attempt_ingest` (policy-gated) |
| FINAL_ERROR | `noop` or `stop_run` |
| UNKNOWN | `stop_run` |

## 6. Derivation Principles

1. **Coverage beats history**  
   Derived state should prefer *current coverage vs expected window* over
   prior attempt status.

2. **Vendor finality is decisive**  
   If `vendor_final == true`, retries cannot improve coverage.

3. **Errors are not incompleteness**  
   Operational failures must be distinguished from missing data.

4. **Budget is not state**  
   Budget skips do not change data completeness.

## 7. Reference Function Signatures

### 7.1 State Derivation

```python
derive_state(
    *,
    latest_attempt: OHLCV1DAttemptRow | None,
    expected_window: ExpectedWindow,
    coverage_now: CoverageSnapshot | None,
) -> DerivedState
```

This function must be:
- pure,
- deterministic,
- side-effect free.

### 7.2 Decision Logic

```python
decide_action(
    *,
    state: DerivedState,
    policy: RetryPolicy,
    budgets: BudgetContext,
    latest_attempt: OHLCV1DAttemptRow | None,
) -> Decision
```

The decision includes:
- action (`noop`, `attempt_ingest`, `stop_run`),
- reason (for reporting/debugging).

## 8. Non-Goals (Phase 2)

- No automatic mapping rebuilds.
- No conditional local resets.
- No cross-dataset coordination.
- No long-term state persistence beyond the attempts ledger.

These may be introduced in later phases.

## 9. Rationale

This model ensures that:
- ingestion is idempotent,
- retries are controlled and explainable,
- vendor limitations are handled explicitly,
- operational failures do not silently corrupt state.

It provides a stable foundation for:
- retry/backoff policies,
- meta-orchestrator scheduling,
- operator diagnostics and reporting.

