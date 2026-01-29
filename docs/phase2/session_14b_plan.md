# session_14b_plan.md
# MXM V1 — Session 14b Plan: Semantics Conformance Pass (OHLCV-1D)

**Purpose:** Align the implemented OHLCV-1D ingestion, state logic, ledger, and inspect/reporting surfaces with the normative semantics document.  
**Scope:** `datasets/ohlcv_1d/*`, attempts ledger schema + store, inspect models/reports, and any shared time/window utilities directly involved.

## 1) Deliverables (Definition of Done)

1. The attempts ledger schema, write-path, read-path, and dataclass model are **fully consistent** (fields, naming, types, nullability).
2. Timestamp and window primitives are **canonical and uniform** across:
   - attempts ledger persisted strings
   - orchestrator formatting
   - inspect parsing / DayRange invariants
3. Status vocabulary, derived states, and reporting semantics are **stable, explicit, and non-ambiguous**.
4. The codebase contains a small set of **conformance tests** that lock in the semantics (unit tests; no vendor calls).
5. Any unavoidable divergence from normative semantics is resolved by either:
   - a code change, or
   - a normative document correction (only if the code is already clearly correct and the doc was wrong).

## 2) Concrete TODO List (Implementation Work)

### A. Ledger schema ↔ store ↔ model alignment (highest priority)

**A1. Add missing fields to `OHLCV1DAttemptRow` (or intentionally remove them from schema).**
- Schema includes: `feed`, `is_vendor_limited`, `is_lifecycle_limited`, `cost_used_usd`, `cost_charged_usd`.
- `record_attempt()` writes: `feed`, `is_vendor_limited`, `is_lifecycle_limited`, `cost_used_usd`, `cost_charged_usd`.
- `OHLCV1DAttemptRow` currently lacks: `feed`, `is_vendor_limited`, `is_lifecycle_limited`, `cost_used_usd`, `cost_charged_usd`.
- Read SELECTs omit: `feed`, `is_vendor_limited`, `is_lifecycle_limited`, `cost_used_usd`, `cost_charged_usd`.

**Action:** Choose one of:
- (Preferred) Expand dataclass + SELECTs to include all persisted fields, or
- Trim schema + write-path to match the reduced model.

**A2. Make “attempt row is authoritative” mechanically true.**
- Ensure inspect/report paths never need to “re-derive” fields that already exist in the row.
- Persisted `expected_start/end`, `is_empty`, `vendor_final` must be readable everywhere.

**A3. Enforce “exactly one row per contract considered” with tests.**
- Unit-test orchestrator loop guarantees `record_attempt()` is called once per eligible contract, including unmapped/skip/error paths.

### B. Timestamp canonicalization (avoid latent ordering/format drift)

**B1. Pick one canonical UTC string format for persisted timestamps and use it everywhere.**
Current state:
- `attempts_store._fmt_ts()` emits **second resolution** `...%SZ`.
- `orchestrator._utc_now_iso_z()` emits **microsecond resolution** `...%fZ`.
- SQLite `created_at` default emits `%fZ` (fractional seconds).

**Action:** Decide and enforce:
- Either: `YYYY-MM-DDTHH:MM:SSZ` everywhere, or
- `YYYY-MM-DDTHH:MM:SS.ssssssZ` everywhere.

Then:
- Update `attempts_store._fmt_ts` and `orchestrator._utc_now_iso_z` and any other formatter helpers to match.
- Ensure lexicographic sorting remains valid (it will, provided format is consistent and fixed-width).

**B2. Make “day-aligned” expectations explicit.**
- Expected/interest/dataset/lifecycle boundaries must be UTC midnight.
- Add assert/guard utilities to enforce midnight alignment at construction time (or at persist time).

### C. Window primitives and empty-window handling (resolve explicit ambiguity)

**C1. Decide: must `DayRange` allow empty windows?**
Current state:
- `inspect.models.DayRange` docstring says `start < end`, but code allows `start == end` because it only rejects `start > end`.
- Orchestrator persists empty expected windows with `expected_start == expected_end` and `is_empty = 1`.

**Action:** Choose one and make it consistent:
- Option 1 (recommended): Allow empty windows as a first-class representation.
  - Update `DayRange` docstring invariant to `start <= end`.
  - Ensure `.is_empty` is meaningful and used where needed.
- Option 2: Forbid empty `DayRange`.
  - Change ledger representation of empty expected windows (this is likely worse; it breaks “persisted expected is authoritative”).

**C2. Fix `contract_coverage_from_attempt_row` empty-window failure mode.**
- It currently raises if `DayRange` construction fails.
- With Option 1 above, this becomes unnecessary; empty expected windows should be representable.

### D. Completeness semantics (ensure all pathways use the same criterion)

**D1. Lock in one canonical definition for completeness and enforce its use.**
Current state:
- Orchestrator uses `is_complete_level0(...)` based on stored_min/max and expected window.
- Inspect layer uses `CoverageWindows.complete` via `stored_window.contains(expected)`.

These must be consistent. If they differ, decide which is authoritative.

**Action:**
- Either move orchestrator to compute completeness using the same “window containment” primitive used by inspect, or
- Implement `CoverageWindows.complete` in terms of the same Level-0 rule (including the `target_end - 1 day` logic) and document why.

**D2. Define completeness for empty expected windows.**
- `CoverageWindows.complete` currently treats empty expected as vacuously complete.
- Ensure this matches the orchestrator’s skip status and product/system rollups.

### E. Vendor finality semantics (eliminate split-brain)

Current state:
- `ExpectedWindow.vendor_final` is computed as `(expiration_ceiling is not None) and (dataset_end >= expiration_ceiling)`.
- `CoverageWindows.vendor_final` in inspect is computed as `expected == available` (dataset ∩ lifecycle).

These are different concepts.

**E1. Decide what “vendor_final” means operationally and keep only one meaning.**
Given the ledger already persists `vendor_final`:
- The persisted `vendor_final` must be treated as the authoritative flag for reporting.
- Any derived “vendor_final-like” property in inspect must be renamed if it remains.

**Action options:**
- Option 1 (recommended): Keep ledger `vendor_final` as “dataset has advanced beyond expiration ceiling”, and rename inspect-derived property to something else (e.g. `expected_equals_available`).
- Option 2: Change how `vendor_final` is computed in expected.py to match `expected==available` and update derivations accordingly (this is a larger semantic shift).

**E2. Remove `derived_vendor_final` from operator-facing outputs or explicitly label it as non-authoritative.**
- The inspect CLI currently prints `derived_vendor_final: {w.vendor_final}` which will mislead operators if it differs from the ledger flag.

### F. Status vocabulary stability (attempt statuses)

**F1. Canonicalize the attempt status enum and enforce it at write-time.**
Current observed set:
- `unmapped`
- `skipped_empty_expected_window`
- `complete`
- `dry_run`
- `skipped_cost_cap`
- `ingested`
- `incomplete`
- `error`

**Action:**
- Create a single canonical `AttemptStatus` (Enum or Literal union) used by:
  - orchestrator
  - attempts_store
  - inspect models
- Enforce that `record_attempt(status=...)` rejects unknown statuses.

**F2. Make status_detail semantics stable.**
- Define whether status_detail is:
  - free-form text, or
  - structured vocabulary (prefix-based), or
  - both with constraints.
- Ensure logs/reports can rely on it.

### G. Derived state logic and retry policy (tighten semantics to match doc)

**G1. Align `derive_state` and `decide_action` to the normative model.**
Key checks:
- “coverage beats history” must remain true.
- `vendor_final` must not yield DONE in the absence of any local data (already implemented).
- `reset_local` must force NEEDS_INGEST (already implemented).

**G2. Implement true consecutive error counting or remove the configuration knob.**
- Current `_consecutive_error_count` returns 1 or 0 because only latest attempt is fetched.
- Either:
  - add `list_recent_attempts_for_contract(contract_id, limit=N)` and compute consecutive errors, or
  - remove/relabel the policy setting to reflect MVP reality.

### H. Reporting semantics conformance

**H1. Make product/system rollups use authoritative definitions.**
Current state:
- Product/system rollups use attempt status buckets for unmapped/cost/error.
- Completeness is inferred from `c.windows.complete` for all other statuses.

**Action:**
- Ensure “complete” means completeness-by-window; if attempt status says complete but windows disagree, it must be surfaced as an inconsistency fault (already partially done).
- Ensure empty expected windows are handled coherently across counts and rollups.

**H2. Ensure reports are strictly read-only and deterministic.**
- No vendor calls.
- No local-store scanning inside inspect paths beyond what is already persisted in attempts rows (optional future improvement).

## 3) Decisions Still To Take (Resolve Explicitly)

1. **Canonical timestamp format**
   - Seconds-only vs microseconds across run_ts_utc/created_at and persisted window boundaries.

2. **Empty expected windows**
   - Allow empty `DayRange` (recommended) vs forbid (would force schema/workarounds).

3. **Single definition of completeness**
   - “Level-0 min/max rule” vs “stored_window contains expected” as the canonical rule.

4. **Meaning of vendor_final**
   - Keep persisted semantic (dataset advanced beyond expiration) vs change to “expected==available”.
   - If both are useful, one must be renamed to avoid semantic collision.

5. **Ledger/model breadth**
   - Expand `OHLCV1DAttemptRow` to cover all schema columns vs shrink schema to match current read model.

6. **Retry policy correctness**
   - Implement true consecutive error counting vs declare MVP policy as “latest-attempt only”.

7. **Status_detail contract**
   - Free-form vs constrained structured strings.

## 4) Suggested Execution Order (Fast Path)

1. Decide (1) timestamp format and (2) empty window handling.
2. Align ledger schema ↔ store ↔ dataclass ↔ SELECTs (A).
3. Resolve vendor_final split-brain (E).
4. Resolve completeness canonical rule (D).
5. Canonicalize status vocabulary and enforce it (F).
6. Add conformance tests (minimal but decisive):
   - empty expected row round-trip
   - vendor_final persistence and reporting
   - completeness agreement between orchestrator + inspect
   - status vocabulary enforcement
7. Run a small real ingestion and verify inspect commands behave deterministically.

## 5) Proof Surfaces (Session Closure)

- `poetry run python scripts/marketdata/ops/inspect_system.py` prints stable product rows without semantic contradictions.
- `poetry run python scripts/marketdata/ops/inspect_product.py --product-id ...` shows:
  - correct empty_expected counts,
  - correct vendor_final interpretation (authoritative),
  - no “complete-but-not-complete” mismatches.
- `poetry run python scripts/marketdata/ops/inspect_contract.py --contract-key ...` prints:
  - authoritative `vendor_final` and unambiguous derived diagnostics.
- Unit test suite includes at least:
  - attempts row round-trip with empty expected window
  - vendor_final semantics test
  - status vocabulary test

