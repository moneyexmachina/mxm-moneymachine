# session_33b_plan.md

## Session 33b — Canonical Timestamp Model & Cross-Layer Time Translation

### Summary

Session 33a established that MXM requires an explicit business-session abstraction based on:

- `calendar_id`
- dense integer `session_id`
- an immutable `MXMBusinessCalendar`

During that work, a deeper prerequisite became clear:

> before we can implement a clean calendar and session model, we must first define the canonical timestamp model that sits underneath it.

The current system still uses a pandas-first UTC timestamp model. That was a reasonable early choice, but it is no longer aligned with the emerging MXM architecture.

We now want:

- a canonical internal timestamp substrate
- a clean boundary between internal and outer-layer time representations
- explicit translations across:
  - NumPy
  - pandas
  - Parquet
  - SQLite

This session defines that timestamp model and introduces the minimum viable utility layer needed to support the rest of Session 33.

## Core Insight

The calendar/session redesign exposed that MXM still lacks a fully explicit answer to:

> what is a timestamp, internally, in MXM?

That answer must be defined before the business calendar can be implemented cleanly, because each session in the calendar will ultimately be represented by:

- `start_ts`
- `end_ts`

and these must rest on a stable, canonical timestamp substrate.

## Canonical Timestamp Policy

### Timestamp as concept

A timestamp is an instant in time.

It is **not inherently**:
- UTC
- Unix time
- nanoseconds since epoch
- pandas Timestamp
- NumPy datetime64

Those are representation choices.

### MXM canonical timestamp representation

MXM adopts:

> **`np.datetime64[ns]` as the canonical internal timestamp type**

with the following interpretation:

- time scale: POSIX-style linear time
- epoch anchor: Unix epoch (`1970-01-01T00:00:00`)
- precision: nanoseconds
- interpretation convention: UTC

Thus:

- canonical internal timestamp values are `np.datetime64[ns]`
- canonical internal timestamp vectors are `ndarray[datetime64[ns]]`

## Layered Time Representation

We define one canonical model and several explicit representations.

### Canonical internal layer

- Type:
  - `np.datetime64[ns]`
- Role:
  - internal domain logic
  - calendar boundaries
  - canonical compute inputs
  - time comparisons
  - persisted time reconstruction

### Outer pandas layer

- Scalar:
  - `pd.Timestamp`
- Vector/container:
  - `pd.DatetimeIndex`
  - pandas datetime Series

Role:
- tabular ingestion
- reporting
- inspection
- CLI / debugging convenience
- outer adapter layer only

Policy:
- pandas time objects are **not canonical**
- they must be translated to canonical NumPy timestamps before entering internal MXM logic

### Parquet layer

Role:
- persisted tabular data artifacts

Policy:
- persisted timestamp columns must round-trip losslessly to canonical `np.datetime64[ns]`
- Parquet is a storage representation, not a distinct timestamp semantics layer

### SQLite layer

Role:
- metadata
- registry state
- control-plane storage

Policy:
- timestamps in SQLite are stored as canonical ISO8601 UTC strings
- SQLite timestamp handling is explicit and human-inspectable
- SQLite is not a canonical compute layer

## Cross-Layer Translation Requirement

We now explicitly require translation paths between the active layers.

### Scalar translations

- ISO8601 UTC string ↔ `np.datetime64[ns]`
- Python `datetime` ↔ `np.datetime64[ns]`
- `pd.Timestamp` ↔ `np.datetime64[ns]`

### Vector/container translations

- `pd.DatetimeIndex` ↔ `ndarray[datetime64[ns]]`
- pandas datetime Series ↔ `ndarray[datetime64[ns]]`
- persisted Parquet timestamp column ↔ canonical timestamp array
- SQLite ISO string column ↔ canonical timestamp values

## Design Principle: One Canonical Model, Many Adapters

MXM must not develop four competing timestamp systems.

Instead:

> **one canonical timestamp model**
>
> plus
>
> **explicit adapters for each storage or interface layer**

This avoids hidden drift and keeps internal semantics coherent.

## Boundary vs Kernel Principle

Timestamp handling follows the same architecture we agreed for the wider system:

### Boundary / adapter zones

Responsibilities:
- parsing
- coercion
- validation
- normalization
- conversion from pandas / strings / Python datetime
- conversion to reporting/storage representations

These layers may be defensive.

### Internal compute/kernel zones

Responsibilities:
- assume canonical timestamp inputs
- operate only on `np.datetime64[ns]`
- avoid repeated coercion and repeated type enforcement

This is where performance-sensitive code lives.

## Module Refactor Direction

### Current state

The existing module:

- `mxm/v1/utils/time_utils.py`

defines a pandas-first timestamp model.

That is no longer aligned with the intended architecture.

### Target structure

We introduce a new split:

#### 1. `mxm/v1/utils/timestamps.py`

Authoritative canonical timestamp substrate.

Responsibilities:
- canonical dtype definition
- scalar coercion into `np.datetime64[ns]`
- vector coercion into `datetime64[ns]` arrays
- assertions / validation helpers
- parsing / formatting
- basic arithmetic helpers
- canonical `now`

#### 2. `mxm/v1/utils/pandas_time.py`

Pandas adapter layer.

Responsibilities:
- `pd.Timestamp` ↔ canonical timestamp
- `DatetimeIndex` ↔ canonical timestamp array
- pandas Series normalization for outer tabular workflows

#### 3. `mxm/v1/utils/storage_time.py` (optional now, or deferred)

Storage-specific helpers.

Responsibilities:
- SQLite ISO formatting/parsing
- Parquet round-trip preparation helpers if needed

For v1, this may remain minimal or partly deferred if current persistence paths are already working.

## Minimum Viable Scope for Session 33b

This session is not about building a grand time framework.

It is about establishing the minimum timestamp substrate needed to unblock Session 33a and the original Session 33.

Therefore the minimum viable deliverable is:

1. a canonical timestamp policy
2. a new `timestamps.py` core module
3. a thin pandas adapter layer
4. a clear migration path away from pandas-first internals
5. one or two first consumers using the new substrate

## Proposed `timestamps.py` Scope (v1 minimal)

### Constants / aliases

- canonical timestamp dtype:
  - `datetime64[ns]`
- canonical type aliases for scalar and vector use

### Core helpers

- `to_ts_ns(...)`
  - coerce supported scalar inputs into canonical `np.datetime64[ns]`

- `to_ts_ns_array(...)`
  - coerce supported vector/container inputs into canonical array form

- `assert_ts_ns(...)`
  - assert scalar/canonical timestamp invariant

- `assert_ts_ns_array(...)`
  - assert vector canonical invariant

- `parse_ts(...)`
  - parse ISO8601 UTC string into canonical timestamp

- `fmt_run_ts(...)`
  - format canonical timestamp into ISO8601 UTC run/control-plane string

- `fmt_day_ts(...)`
  - format canonical day-aligned timestamp into canonical day string

- `utc_now_ts()`
  - canonical current timestamp

- `add_days(...)`
  - canonical day-shift helper

- `floor_to_day(...)`
  - UTC day-floor

- `ceil_to_day(...)`
  - next UTC day boundary if not already aligned

## Proposed `pandas_time.py` Scope (v1 minimal)

- `pd_timestamp_to_ts_ns(...)`
- `ts_ns_to_pd_timestamp(...)`
- `datetimeindex_to_ts_ns_array(...)`
- `ts_ns_array_to_datetimeindex(...)`
- optional Series helpers for outer tabular normalization

This module is strictly adapter-side, not canonical.

## Treatment of Existing `time_utils.py`

We should not attempt a giant rewrite in one move.

### Proposed transition

- introduce the new canonical module first
- reclassify existing functions into:
  - canonical time substrate
  - pandas boundary helpers
- gradually migrate internal consumers
- eventually deprecate or slim down `time_utils.py`

## Impact on Session 33a

Session 33b is a prerequisite because Session 33a requires:

- `MXMBusinessCalendar.start_ts`
- `MXMBusinessCalendar.end_ts`

and those should be represented canonically as:

- `np.datetime64[ns]`

not pandas Timestamps.

Thus Session 33b directly unblocks a cleaner implementation of Session 33a.

## Impact on Original Session 33

Original Session 33 was about:

- degraded data
- business-day/calendar correctness
- repaired daily mark logic
- full-history synthetic asset cumulative PnL

This timestamp work matters because it removes one more source of semantic ambiguity before:

- building `daily_mark`
- mapping date-based market data into session_id space
- running the full historical backtest cleanly

## Implementation Plan

### Step 1 — Write timestamp policy into code

- create `mxm/v1/utils/timestamps.py`
- define canonical dtype and docstring policy

### Step 2 — Implement scalar canonicalization

- ISO string → `datetime64[ns]`
- Python datetime → `datetime64[ns]`
- pandas Timestamp → `datetime64[ns]`
- integer epoch-ns → `datetime64[ns]`

### Step 3 — Implement vector canonicalization

- NumPy arrays
- pandas `DatetimeIndex`
- pandas datetime Series

All canonicalized to:
- `ndarray[datetime64[ns]]`

### Step 4 — Implement formatting helpers

- canonical ISO run timestamp formatting
- canonical day timestamp formatting
- SQLite-friendly ISO formatting/parsing

Keep minimal.

### Step 5 — Introduce pandas adapter module

- move pandas-specific helpers behind explicit adapter names
- keep pandas out of the canonical module except where unavoidable for boundary translation

### Step 6 — Identify first consumers

Minimal first consumers:
- calendar timestamp boundaries
- any nearby utility code currently depending on pandas-first timestamps

### Step 7 — Leave kernel code clean

Do not spread coercion checks into hot paths.

Boundary validation only.

## Success Criteria

Session 33b is complete when:

- MXM has an explicit canonical timestamp policy
- `np.datetime64[ns]` is established as internal timestamp truth
- pandas is clearly demoted to boundary/adapter role
- conversion helpers exist for scalar and vector timestamp forms
- the new timestamp substrate is ready to support Session 33a calendar work

## Non-Goals

- redesigning all marketdata storage immediately
- migrating all existing modules in one pass
- introducing DuckDB / Polars / new storage stack
- full leap-second or alternate time-scale modelling
- building a generalized temporal framework

## Risks & Mitigations

### Risk: over-engineering
Mitigation:
- keep the scope minimal
- build only what Session 33a needs next

### Risk: migration churn
Mitigation:
- introduce new modules first
- migrate incrementally
- preserve compatibility where practical

### Risk: repeated runtime validation in hot paths
Mitigation:
- enforce boundary vs kernel discipline explicitly

### Risk: semantic confusion during transition
Mitigation:
- use explicit naming:
  - canonical NumPy time helpers
  - separate pandas adapters

## After Session 33b

The sequence becomes:

### Session 33b
Canonical timestamp substrate

### Session 33a
MXM business calendar + session_id model

### Session 33 (original continuation)
- repair daily mark / availability logic
- map date-based surfaces into session_id space
- run full cumulative synthetic-asset PnL across history

## Expected Payoff

Completing Session 33b should make Session 33a materially cleaner and reduce ambiguity in:

- calendar boundaries
- time comparisons
- time persistence
- pandas vs NumPy handling

That, in turn, should make it easier to finally return to the original goal:

> run the synthetic asset cumulative PnL cleanly over the full historical range

## Conclusion

Session 33b is a small but foundational prerequisite session.

It establishes the timestamp substrate that the new business-session system will stand on.

We are not changing direction.

We are clarifying the layer beneath the new calendar so that the calendar itself can be implemented cleanly, minimally, and correctly.
