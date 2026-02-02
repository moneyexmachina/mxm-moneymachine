# MXM V1 — Session 14e Context Pack
## Status Vocabulary Pass (Enforce Normative Semantics)

**Phase:** 2 (Marketdata) — final consolidation  
**Focus:** Status vocabulary + consistency across orchestration, attempts ledger, and inspection rollups  
**Authority:** `normative_semantics.md` (pasted in prior thread; treated as single source of truth)

## 0. Objective

Perform a disciplined “status vocabulary pass” across the OHLCV-1D marketdata module:

1. **Enforce** the authoritative attempt-status set and its meaning (Section 8).
2. **Enforce** the derived-state set and precedence rules (Section 9).
3. **Remove** any accidental redefinition of semantics in inspection and reporting (Section 10).
4. **Audit and tighten** the *writer surfaces* (orchestrators) to ensure every status is produced in a way that matches the doc.
5. **Audit and tighten** the *reader surfaces* (inspect rollups) so they interpret statuses exactly as defined, and never smuggle in new meaning.

**Deliverable:** a coherent, consistent status/state/action vocabulary that is:
- deterministic,
- auditable,
- non-overloaded,
- aligned across layers.

## 1. Ground Truth & Non-Negotiables (Summary)

### 1.1 Attempt statuses are facts
Attempt statuses are **persisted facts** (“what happened”), not system truth.

- Exactly one status per attempt row.
- Append-only.
- No later reinterpretation.

### 1.2 Completeness is window containment only
Completeness is **only**:

- empty expected → complete
- otherwise stored_window contains expected

Statuses **never** imply completeness.

### 1.3 Vendor finality is orthogonal to completeness
Vendor finality **explains why coverage cannot improve**; it does not assert completeness.

### 1.4 Inspection/reporting are read-only
Inspection/reporting:
- do not compute coverage differently,
- do not change status meaning,
- do not do time manipulation beyond explicit parsing views.

## 2. Vocabulary Surfaces (Where Meaning Can Drift)

We will audit and enforce semantics at these four surfaces:

### 2.1 Attempt-status writer surface
Where `Attempt.status` / `Attempt.status_detail` are assigned and persisted.

**Primary:** OHLCV-1D orchestrator (and any upstream layer that writes attempts).

### 2.2 Derived-state computation surface
Where we compute a derived state (non-persisted) to drive decision logic:

- `DONE`
- `BLOCKED_UNMAPPED`
- `BLOCKED_EMPTY_EXPECTED`
- `NEEDS_INGEST`
- `RETRYABLE_ERROR`
- `FINAL_ERROR`
- `SKIPPED_BUDGET`
- `UNKNOWN`

These are **not** statuses. These are internal decision classifications.

### 2.3 Decision/action surface
Where the orchestrator chooses what to do this run:
- skip
- ingest
- halt
- retry later
- etc.

This must be separate from:
- attempt status (facts),
- completeness (truth),
- derived state (policy classification).

### 2.4 Inspection/reporting surface
Where we interpret the latest attempt per contract_key and roll up to product/system.

Inspection must:
- trust persisted facts,
- compute completeness only via coverage.py,
- apply product/system status rules from Section 10 **in order**.

## 3. Authoritative Vocabularies (From Normative Doc)

### 3.1 Attempt statuses (authoritative set)
**Must be exactly:**
- `unmapped`
- `skipped_empty_expected_window`
- `complete`
- `dry_run`
- `skipped_cost_cap`
- `ingested`
- `incomplete`
- `error`

No new statuses without doc amendment.

### 3.2 Derived states (authoritative set)
**Must be exactly:**
- `DONE`
- `BLOCKED_UNMAPPED`
- `BLOCKED_EMPTY_EXPECTED`
- `NEEDS_INGEST`
- `RETRYABLE_ERROR`
- `FINAL_ERROR`
- `SKIPPED_BUDGET`
- `UNKNOWN`

### 3.3 Product status (authoritative set + precedence)
Product status ∈ {`never_run`, `done`, `partial`, `blocked`, `error`}

Rules must be applied in this order:
1. `never_run` if no attempts exist
2. `done` if all contracts complete AND none are unmapped/cost-blocked/error
3. `error` if any contract error or inconsistent completeness
4. `blocked` if any unmapped or cost-blocked and no errors
5. `partial` otherwise

### 3.4 System status
No global status; classify products independently per product rules.

## 4. Known Risk Areas (Where Bugs Tend to Hide)

### 4.1 Overloading the word “complete”
There are *three* “complete-ish” concepts that must not be conflated:
- Attempt status `complete` (no vendor call; local data already complete OR vendor-final + previously ingested)
- Contract completeness `windows.complete` (pure coverage truth)
- Derived state `DONE` (includes vendor-final + has-any-data case)

**Invariant:** Only `windows.complete` is the completeness predicate.

### 4.2 Vendor-final partial vs “complete”
Vendor-final + incomplete coverage must not become “complete”; it can be “DONE” at derived-state level, and “partial” at reporting level unless windows are complete.

### 4.3 Status_detail sprawl
`status_detail` tends to accumulate overloaded meaning. We must decide:
- which details are allowed per status,
- which details are purely diagnostic (and should not affect logic),
- which details are used by inspection bucketing (if any).

### 4.4 “Dry run” semantics
`dry_run` must never be treated as success or failure. It is “non-authoritative”.

### 4.5 “ingested” vs “incomplete”
`ingested` indicates a vendor call + write occurred; completeness may still be false.
`incomplete` indicates vendor call + data still incomplete + not vendor-final.

We must ensure the orchestrator uses them consistently.

## 5. Work Plan (Session 14e)

### Step A — Inventory (mechanical)
1. Enumerate all status writes in code:
   - locate all assignments to `status = ...` and `status_detail = ...`
   - locate all branches on `row.status` / `AttemptSummary.status`

2. Enumerate all distinct `status_detail` values currently produced.

3. Enumerate all distinct attempt statuses present in the SQLite attempts table (optional but valuable).

**Exit:** a concrete list of observed statuses/details and the files that write them.

### Step B — Align writer surface (orchestrator)
For each attempt status, confirm:
- the condition under which it is written,
- whether vendor call occurred,
- whether storage was modified,
- whether the meaning matches Section 8.

Check especially:
- `complete` vs `ingested` vs `incomplete`
- `skipped_empty_expected_window`
- budget gating (`skipped_cost_cap`)
- unmapped conditions
- exception handling → `error`

**Exit:** orchestrator emits only allowed statuses; each status conforms to its definition.

### Step C — Align derived-state computation
If a derived-state function exists, enforce:
- state set matches Section 9,
- precedence rules match Section 9.4,
- reset override behaviour matches Section 9.6,
- vendor-final allowance is present only where permitted.

**Exit:** derived states are pure, deterministic, and policy-correct.

### Step D — Align inspection/readers and rollups
1. Contract inspection must:
   - trust persisted expected window,
   - build windows via coverage.py,
   - surface: `windows.complete`, `vendor_final`, `is_empty`, and the attempt status.

2. Product/system rollups must:
   - compute completeness from `windows.complete`,
   - bucket blockers from attempt status (`unmapped`, `skipped_cost_cap`, `error`),
   - treat “status==complete but windows.complete==False” as **error signal** (per Section 6.7 / 10.7),
   - apply product status precedence order exactly (Section 10.4.3).

**Exit:** inspection layer is interpretation only; no semantic reinvention.

### Step E — Proof sweep (status-focused)
- `rg` check that only the authoritative attempt statuses are used as string literals.
- `pytest` / `pyright` clean.
- Run one product inspect report and one system report and sanity check:
  - no contradictions,
  - “done” implies all contracts complete,
  - vendor-final incomplete appears as incomplete (contract truth), not complete.

## 6. Outputs (What “Done” Looks Like)

### Code invariants
- Attempt statuses in code are exactly the authoritative set.
- Derived states are exactly the authoritative set.
- Inspection computes completeness only from coverage.py.
- `status_detail` is either:
  - constrained to a documented enumeration, or
  - explicitly declared “diagnostic only” and not used for logic.

### Operator invariants
- No report implies completeness without `windows.complete == True`.
- “Vendor final” is always surfaced separately.
- Product/system statuses match the normative precedence rules.

## 7. Practical File Map (Likely Touch Points)

**Writer surface:**
- `mxm/v1/marketdata/datasets/ohlcv_1d/orchestrator.py` (or equivalent)
- wherever attempt rows are persisted

**Semantic core:**
- `mxm/v1/marketdata/datasets/ohlcv_1d/coverage.py` (already canonical)

**Inspection surface:**
- `mxm/v1/marketdata/inspect/contracts.py`
- `mxm/v1/marketdata/inspect/product.py`
- `mxm/v1/marketdata/inspect/system.py`
- `mxm/v1/marketdata/inspect/models.py`

## 8. Session 14e First Question (Start Here)

Paste (or point to) the code in the OHLCV-1D orchestrator where:
- `Attempt.status` and `Attempt.status_detail` are set,
- any derived state is computed,
- any “complete / ingested / incomplete / vendor-final” decision branches exist.

We will then:
1) map each branch to Section 8/9 semantics,
2) identify any overloading or divergence,
3) produce the minimum patch to bring it into conformance.

