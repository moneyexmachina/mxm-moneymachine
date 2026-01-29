# MXM V1 — Session 14c Context Pack  
## Semantic Hardening Closure (Marketdata / OHLCV-1D)

**Session intent:**  
Finish the semantic hardening pass started in Session 14b and bring the entire
`mxm.v1.marketdata` stack to a state that is **confidently semantically correct**,
fully aligned with the normative document, and ready for final multi-product orchestration.

This session is explicitly **bounded**: no new features, no perfectionism,
no speculative refactors.

## What is already complete

1. **Normative semantics document**
   - All sections written and internally consistent.
   - Empty expected windows, ledger authority, and reporting semantics resolved.

2. **Timestamp semantics**
   - `time_utils.py` is the single authority.
   - Canonical internal type: `pd.Timestamp` (UTC).
   - Canonical persisted formats:
     - Control-plane: `fmt_run_ts` (microseconds)
     - Surfaces: `fmt_day_ts` (UTC midnight)
   - Naive timezone strings rejected.
   - Vendor nanosecond timestamps accepted and normalised.
   - Unit tests passing.

These are no longer under debate.

## Session 14c goals (Definition of Done)

By the end of this session:

1. The **attempts ledger schema, store, dataclass, and SELECTs are mechanically aligned**.
2. There is **exactly one canonical definition of completeness**, used everywhere.
3. **Vendor finality has a single meaning**, and no operator-facing output is ambiguous.
4. All remaining timestamp helpers outside `time_utils` are removed or replaced.
5. Inspect (contract / product / system) reports are:
   - deterministic
   - read-only
   - semantically non-contradictory
6. Marketdata can be declared **semantically finished**, pending only a multi-product wrapper.

## Work items for this session

### 1) Ledger schema ↔ store ↔ model alignment (highest priority)

- Resolve the mismatch between:
  - SQLite schema
  - `record_attempt()` write-path
  - `OHLCV1DAttemptRow`
  - SELECT statements

Decision (tentative):
- **Expand the dataclass and SELECTs** to include all persisted fields:
  - `feed`
  - `is_vendor_limited`
  - `is_lifecycle_limited`
  - `cost_used_usd`
  - `cost_charged_usd`

No derived recomputation in inspect paths; the attempt row is authoritative.

### 2) Canonical completeness definition

Decision:
- **`CoverageWindows.complete` is the single source of truth.**

Actions:
- Either remove `is_complete_level0`, or
- Refactor orchestrator logic to use window containment semantics consistently.

Empty expected windows must remain vacuously complete.


### 3) Vendor finality semantic unification

Decision:
- **Persisted `vendor_final` in the attempts ledger is authoritative.**

Actions:
- Remove or rename inspect-derived `vendor_final`.
- Ensure CLIs do not print ambiguous “derived_vendor_final”.
- Reporting consumes only the ledger flag.


### 4) Status vocabulary enforcement

- Canonical attempt statuses are fixed:

- unmapped
skipped_empty_expected_window
skipped_cost_cap
ingested
complete
incomplete
dry_run
error


- Enforce this vocabulary at `record_attempt()` write-time.
- Unknown statuses must raise.

`status_detail` remains free-form but is non-authoritative.

### 5) Retry / error policy closure

Decision:
- MVP policy is **latest-attempt only**.
- No true consecutive error counting in v1.

Actions:
- Remove misleading knobs or comments, or
- Make the limitation explicit in code comments.

No new retry machinery is added.

## Explicit non-goals

- No new ingestion logic.
- No performance tuning.
- No additional reporting features.
- No calendar/session modelling.
- No refactors unrelated to semantic correctness.

## Proof surfaces for session closure

- `inspect_contract.py`:
- No ambiguity between ledger and derived fields.
- Empty expected windows are cleanly represented.

- `inspect_product.py`:
- No “complete but not complete” contradictions.
- Vendor finality counts match ledger semantics.

- `inspect_system.py`:
- Stable, deterministic roll-ups.

- Unit tests include:
- Attempt row round-trip with empty expected window.
- Vendor finality persistence and reporting.
- Completeness agreement between orchestrator and inspect.
- Status vocabulary enforcement.

## Success condition

At the end of Session 14c, it is reasonable to state:

> “Marketdata semantics are finished.  
> Any remaining work is orchestration or scaling, not correctness.”

The next session can then focus purely on the **multi-product wrapper**.
