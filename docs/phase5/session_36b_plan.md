# Session 36b Plan — Extract Canonical Timestamp Substrate from `mxm-v1` into `mxm-types`

## Summary

During Session 36a, while implementing the reporting storage layer for `mxm-pipeline`, we encountered a foundational design question around timestamp representation.

The immediate practical issue was how to serialize reporting timestamps into SQLite. A quick local solution would have been to keep using Python `datetime` inside `mxm-pipeline` and define a local persistence mapping there.

However, this exposed a deeper architectural inconsistency.

MXM has already done substantial work in `mxm-v1` to establish a **single canonical internal timestamp model**, with explicit representation bridges and clear boundary-vs-kernel separation. That timestamp substrate is no longer merely a `mxm-v1` implementation detail. It is now clearly a **shared MXM foundation** that should be usable across packages, including:

- `mxm-v1`
- `mxm-pipeline`
- future shared packages and storage layers

Therefore, before proceeding further with the `mxm-pipeline` reporting stores, we should carry out a focused extraction:

> Move the canonical timestamp substrate out of `mxm-v1` and into `mxm-types`, while carefully assessing which components genuinely belong to the shared substrate and which remain package-local adapters.

This is now worthwhile because:

- the timestamp model is already conceptually mature
- it is small enough to extract cleanly
- duplication at this point would create unnecessary architectural debt
- `mxm-pipeline` is still early enough that switching to canonical timestamps is cheap

---

## Session Objective

Extract the now-canonical MXM timestamp substrate from `mxm-v1` into `mxm-types`, and update package imports and boundaries accordingly.

This includes clarifying which parts of the existing timestamp handling are:

- **canonical shared substrate**
- **boundary adapters**
- **package-local conveniences**

The output of this session should be a clean, reusable timestamp foundation in `mxm-types` that both `mxm-v1` and `mxm-pipeline` can depend on.

---

## Core Architectural Goal

The key goal is to preserve and generalize the principle already established in `mxm-v1`:

> MXM should have **one canonical internal timestamp representation**, with explicit boundary-layer bridges into pandas, SQLite, strings, Parquet, and other external systems.

This implies:

- no second internal timestamp model in `mxm-pipeline`
- no local near-copy of timestamp substrate utilities
- no wrong-way dependency from `mxm-pipeline` into `mxm-v1`
- no mixing of canonical internal timestamps with boundary-layer types in kernel logic

---

## Why This Session Is Needed Now

Without this extraction, we would be forced into one of two poor states:

### Option A — duplicate locally in `mxm-pipeline`
This would create:

- two timestamp substrate implementations
- likely drift in validation and formatting rules
- eventual cleanup and migration cost

### Option B — import from `mxm-v1`
This would create:

- the wrong dependency direction
- `mxm-pipeline` depending on an application package for core types
- poor package hygiene

Neither is desirable.

Since the timestamp substrate is already developed and currently small enough to move cleanly, extraction now is the right choice.

---

## Main Design Question for the Session

The central question is not whether to extract the timestamp substrate.

That is now relatively clear.

The real question is:

> **What exactly belongs in `mxm-types`, and what should remain outside it?**

This matters because the current `mxm-v1` world includes more than one timestamp-related concern:

1. canonical internal timestamp representation
2. canonical string and integer bridges
3. pandas equivalents and adapters
4. SQLite / storage representations
5. broader temporal semantics elsewhere in the system

We should extract only the genuinely shared and representation-level substrate, not drag half of the boundary layer along with it.

---

## Proposed Scope of Extraction

## 1. Must Move into `mxm-types`

These pieces appear to be true shared substrate and should move.

### Canonical type aliases and dtype constants
- `TSNSScalar`
- `TSNSArray`
- `Int64Array`
- `TS_NS_DTYPE`
- `INT64_DTYPE`

### Canonical scalar constants
- `EPOCH_TS_NS`
- `NAT_TS_NS`

### Canonical predicates and assertions
- `is_ts_ns`
- `assert_ts_ns`
- `is_nat`
- `assert_not_nat`
- `is_ts_ns_array`
- `assert_ts_ns_array`
- `has_nat`
- `assert_no_nat`
- `assert_monotonic_increasing_ts_ns_array`

### Canonical bridge conversions
- `ts_ns_from_int`
- `ts_ns_to_int`
- `ts_ns_from_str`
- `ts_ns_to_str`

### Canonical format policy
The regular expression and exact canonical UTC string contract:
- `YYYY-MM-DDTHH:MM:SS.fffffffffZ`

This is part of the shared representation substrate and should move with it.

---

## 2. Likely Should Move if Present Elsewhere in Compatible Form

If there are already helper functions in `mxm-v1` for explicit conversions between canonical timestamps and pandas representations, these may belong in `mxm-types` **only if** they are still representation-level and not storage/domain-specific.

Examples of candidates:

- canonical `np.datetime64[ns]` ↔ `pd.Timestamp`
- canonical timestamp array ↔ `DatetimeIndex`
- strict UTC-normalizing pandas bridge helpers

However, this should be assessed carefully.

The question is:

> Are these truly general timestamp representation bridges, or are they specific to `mxm-v1` marketdata workflows?

If they are general and cleanly factored, they likely belong in `mxm-types`.

If they are entangled with data-ingestion expectations or frame-shape assumptions, they should remain local for now.

---

## 3. Should Probably Remain Outside `mxm-types`

These should **not** be extracted unless we find a very clean reason to do so.

### SQLite-specific timestamp persistence helpers
Anything like:
- canonical timestamp ↔ SQLite text row field
- row mappers
- SQL-specific adapter behavior

These belong at the storage boundary, not in the core type substrate.

### Parquet-specific or schema-specific adapters
Anything specific to:
- Arrow
- Parquet schema handling
- table serialization

These are storage adapters, not type substrate.

### Business/session/calendar semantics
Anything involving:
- business days
- sessions
- exchange calendars
- calendar labels
- date truncation under session semantics

These are higher-level temporal semantics, not canonical timestamp substrate.

### Generic parsing of non-canonical timestamps
Anything that accepts arbitrary input formats should remain out of the substrate.
The substrate should stay strict.

---

## Expected Extraction Boundary

The desired end state is approximately:

### `mxm-types`
Owns:
- canonical MXM timestamp representation
- canonical timestamp assertions and invariants
- canonical equivalent bridge representations
- strict conversion between canonical internal form and canonical string/int forms
- possibly strictly general pandas bridge helpers, if clean and generic

### `mxm-v1`
Owns:
- marketdata-specific timestamp usage
- SQLite adapters for marketdata stores
- pandas helpers tied to marketdata frame contracts
- business calendar and session semantics
- any domain-specific time logic built on top of the substrate

### `mxm-pipeline`
Owns:
- reporting-store persistence adapters using the shared timestamp substrate
- execution/reporting timestamp usage built on the shared canonical type

---

## Concrete Tasks for Session 36b

## 1. Audit the current timestamp-related code in `mxm-v1`
Review what currently exists beyond the canonical `timestamps.py` substrate.

Questions to answer:

- Is `timestamps.py` self-contained enough to extract directly?
- What timestamp-related helpers elsewhere depend on it?
- Which additional helpers are general enough to move into `mxm-types`?
- Which helpers are really storage-, pandas-, or domain-boundary-specific?

This audit should be explicit, not assumed.

---

## 2. Decide the extraction boundary
Write down a clear decision for each candidate group:

- move now
- leave in `mxm-v1`
- possibly move later

This is the most important conceptual part of the session.

The extraction should remain tight and principled.

---

## 3. Add the timestamp substrate to `mxm-types`
Create the appropriate module(s) in `mxm-types`.

Likely something like:

```text
mxm_types/
  timestamps.py
```

or equivalent package-local naming, depending on the package’s existing structure.

Copy or adapt the selected substrate code into `mxm-types`, preserving:

- semantics
- strictness
- docstrings
- canonical formatting rules

Avoid opportunistic redesign unless strictly necessary for package fit.

---

## 4. Add / update tests in `mxm-types`
The extracted timestamp substrate should have direct test coverage in its new home.

At minimum cover:

- scalar type checks
- NaT rejection behavior
- array checks and monotonicity
- int round-trips
- canonical string round-trips
- rejection of malformed strings
- canonical formatting guarantees

The tests should ensure extraction preserved behavior exactly.

---

## 5. Update `mxm-v1` to import from `mxm-types`
Replace local imports from the old `mxm-v1` timestamp substrate with the new shared source.

The goal is to verify that:

- the extraction boundary is viable in practice
- `mxm-v1` still works unchanged semantically
- the new ownership boundary is real, not just theoretical

If the old local module remains temporarily as a compatibility shim, that should be a deliberate short-lived decision, not an accident.

---

## 6. Update `mxm-pipeline` reporting models to use canonical timestamps
Once `mxm-types` exposes the shared canonical timestamp type, update:

- `FlowRun`
- `TaskRun`
- `TaskAttempt`
- `ExecutionEvent`
- `SemanticEvent`

to use canonical MXM timestamps instead of Python `datetime`.

This will restore architectural consistency before store implementation proceeds.

---

## 7. Reassess local reporting persistence adapters
Once the canonical substrate is shared, decide what still needs to exist locally in `mxm-pipeline`.

Most likely:
- a small reporting `serde.py` remains appropriate
- but it should now bridge:
  - canonical `np.datetime64[ns]`
  - canonical string form for SQLite
  - canonical JSON text for payloads

rather than:
- Python `datetime`
- ad hoc string formatting

---

## Non-Goals

This session should **not** turn into a broad time-system redesign.

Specifically, we should not:

- redesign the canonical timestamp model
- redesign business calendar/session semantics
- generalize all storage adapters into `mxm-types`
- extract pandas-heavy domain logic unless it is clearly representation-level
- pause for broader packaging cleanup beyond what the timestamp extraction requires

The point is to relocate an already-settled substrate, not reopen the entire time architecture.

---

## Success Criteria

By the end of Session 36b:

- `mxm-types` owns the canonical MXM timestamp substrate
- the extracted boundary is explicit and justified
- tests for the timestamp substrate pass in `mxm-types`
- `mxm-v1` is updated to use the shared version
- `mxm-pipeline` can use the shared canonical timestamp type directly
- we are ready to proceed with reporting `serde.py` and the SQLite stores without introducing a second internal timestamp model

---

## Expected Benefit for Session 36a Continuation

Completing this extraction will unblock the reporting-store work cleanly.

Instead of defining local compromises in `mxm-pipeline`, we will be able to build:

- canonical timestamp-bearing reporting models
- canonical timestamp persistence mappings
- SQLite stores aligned with broader MXM temporal policy

That will make the storage layer simpler, more principled, and easier to evolve across packages later.

---

## Immediate Next Step After Session 36b

Resume Session 36a storage implementation with:

1. `mxm-pipeline` reporting models switched to canonical timestamps
2. local reporting `serde.py` bridging canonical timestamps to SQLite text
3. `FlowRunsStore`
4. the remaining reporting stores
5. store integration tests
