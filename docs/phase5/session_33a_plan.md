# session_33a_plan.md

## Session 33a — MXM Business Session Abstraction & Calendar System (Revised after Session 33b)

## Summary

Session 33 revealed that the core issues encountered (e.g. degraded market data, missing marks, inconsistent backtests) are not primarily **data problems**, but **time-domain modelling problems**.

Session 33b has now established a **canonical timestamp substrate** and removed ambiguity around:

- timestamp representation
- UTC semantics
- pandas vs NumPy handling
- boundary vs kernel separation

We can now proceed with Session 33a on a **clean temporal foundation**.

We formalize:

> **A session is a coordinate in an ordered decision-time domain defined by a calendar, with explicit timestamp boundaries.**

This session establishes:

- a **canonical session abstraction**
- a **calendar as a first-class data object**
- a **clean separation between identity (session_id) and representation (labels, timestamps)**
- a **foundation for deterministic, performant, and extensible time handling**

## Core Insight

### Previous implicit model (v1 so far)

- Session ≈ date label (`np.datetime64[D]`)
- Used as:
  - identity
  - join key
  - index

This conflates:
- identity
- representation
- time semantics

### Revised model (post 33b)

> **Session = integer ordinal (`session_id`) within a calendar, with explicit timestamp boundaries defined in canonical time**

Formally:

```
(session_id, calendar_id) ∈ CalendarDomain
```

With:

```
start_ts, end_ts ∈ TSNSScalar (np.datetime64[ns], UTC)
```

## Canonical Representation

### Internal (compute domain)

```python
session_id: int
calendar: MXMBusinessCalendar
```

- `session_id` is:
  - dense
  - ordered
  - monotonic
  - local to a calendar

- `calendar` defines:
  - mapping
  - ordering
  - timestamp boundaries

### External (storage / interchange)

```python
calendar_id: str
session_id: int
```

Optional:

```python
session_label: date  # informational only
```

## Fundamental Invariant

> **A session_id is only valid under exactly one calendar_id**

Implications:

- session_ids are **not globally meaningful**
- all operations must respect calendar identity
- mixing calendars is an error

## Conceptual Model

> **Calendar = ordered domain + coordinate system + time embedding**

- calendar defines:
  - ordered sessions
  - mapping to labels
  - mapping to timestamps

- session_id is:
  - coordinate in that domain

- timestamps provide:
  - embedding into real-world time

## Design Principles

### 1. Calendar is authoritative

Defines:

- ordered sessions
- valid domain
- mappings:
  - session_id ↔ label
  - session_id → (start_ts, end_ts)

### 2. Session identity is integer-based

Enables:

- fast joins
- vectorisation
- slicing
- memory efficiency

### 3. Timestamps are canonical and explicit

- `start_ts`, `end_ts` are:
  - `TSNSScalar`
  - validated via `timestamps.py`

- no pandas objects in kernel

### 4. Labels are representations

- never used for:
  - joins
  - identity
  - logic

- only for:
  - debugging
  - inspection
  - plotting

### 5. Separation of concerns

| Concept         | Responsibility                                |
|-----------------|-----------------------------------------------|
| Calendar        | domain + ordering + timestamp boundaries       |
| Session ID      | coordinate within domain                       |
| Label           | human-readable representation                  |
| Timestamp       | canonical real-world time embedding            |

## Calendar as First-Class Data Artifact

Calendars are now:

> **immutable, versioned reference-data objects with canonical timestamps**

### Calendar Artifact Properties

- uniquely identified by `calendar_id`
- immutable once published
- deterministic construction
- versioned (e.g. `mxm_business_day_v1`)
- inspectable and reproducible

### Calendar Artifact Invariants

1. `calendar_id` is globally unique
2. content is immutable
3. `session_id ∈ {0, ..., N-1}` (dense)
4. mapping is bijective:
   ```
   session_id ↔ label
   ```
5. timestamps are canonical:
   - `TSNSScalar`
   - non-NaT
   - UTC-consistent
6. timestamp arrays are:
   - monotonic increasing
   - non-overlapping
7. construction policy is documented

## Time Semantics

Each session defines a half-open interval:

```
[start_ts, end_ts)
```

Properties:

- no overlap
- full ordering
- composable
- aligned with canonical timestamp model (Session 33b)

## MXMBusinessCalendar Interface (v1)

```python
class MXMBusinessCalendar:
    calendar_id: str

    def __len__(self) -> int

    def session_ids(self) -> np.ndarray
    def labels(self) -> np.ndarray

    def start_ts(self, session_id: int) -> TSNSScalar
    def end_ts(self, session_id: int) -> TSNSScalar

    def session_id_from_label(self, label) -> int
    def label_from_session_id(self, session_id: int)

    def next(self, session_id: int) -> int
    def prev(self, session_id: int) -> int

    def slice(self, start_id: int, end_id: int, inclusive: bool = True) -> np.ndarray

    def contains_label(self, label) -> bool
    def contains_session_id(self, session_id: int) -> bool

    def validate_session_id(self, session_id: int) -> None
```

## Integration with Session 33b

Session 33a now explicitly depends on:

- `TSNSScalar`
- `TSNSArray`
- `assert_ts_ns`
- `assert_not_nat`
- `assert_ts_ns_array`
- `assert_no_nat`
- `assert_monotonic_increasing_ts_ns_array`

These are used to enforce:

- timestamp validity
- monotonicity
- boundary correctness

## Calendar Construction

### Input

```python
dates: ndarray[datetime64[D]]
```

These are:

- pre-filtered business days
- derived from trading calendar / policy

### Construction Steps

1. assign dense `session_id`
2. map `label = date`
3. derive:
   - `start_ts = date @ 00:00:00 UTC`
   - `end_ts = next date @ 00:00:00 UTC`
4. validate:
   - canonical dtype
   - no NaT
   - monotonicity
   - interval consistency

## Calendar Stability Requirement

> **session_id assignment must be stable within a given calendar_id**

Implications:

- deterministic construction
- identical inputs → identical calendar
- required for persisted data consistency

## Storage Strategy

Persist:

```
calendar_id
session_id
```

Optional:

```
session_label
```

Rules:

- session_id is authoritative
- labels are informational only
- never join on labels

## Runtime Usage Pattern

```python
class TargetHoldings:
    calendar: MXMBusinessCalendar
    data: DataFrame  # indexed by session_id
```

- calendar is held by reference
- session_id interpreted relative to calendar

## Compatibility Rule

> Two session-indexed objects are compatible iff they share the same calendar_id

## Impact on Existing Components

### TargetHoldings
- `(date, contract_id)` → `(session_id, contract_id)`

### daily_mark
- `(session_id, contract_id) → mark`

### Backtester
- iterate over `session_id`

### Price Accessors
- must accept `session_id`

### Market Data Mapping
- `date → session_id` mapping layer required

## Implementation Plan (Revised)

### Step 1 — Calendar Core (with canonical timestamps)

- implement:
  - session_id construction
  - label mapping
  - start_ts / end_ts (TSNSScalar)
  - invariant checks using timestamps module

### Step 2 — Unit Tests

Test:

- bijection:
  - session_id ↔ label
- timestamp validity:
  - correct dtype
  - non-NaT
- monotonicity:
  - start_ts increasing
  - end_ts increasing
- interval correctness:
  - no overlap
  - start < end
- stability:
  - rebuild identical

### Step 3 — Minimal Integration

- use calendar in one consumer:
  - e.g. `daily_mark` or synthetic asset pipeline

### Step 4 — Adapter Layer (Temporary)

- label → session_id conversion
- boundary only

## Success Criteria

Session 33a is complete when:

- MXMBusinessCalendar implemented
- canonical timestamps used for boundaries
- invariants enforced via timestamps module
- session_id becomes canonical coordinate
- calendar is deterministic and tested

## Non-Goals

- multi-frequency calendars
- intraday sessions
- distributed registry
- full pipeline refactor

## Risks & Mitigations

### Over-engineering
- keep single calendar
- minimal API

### Migration complexity
- incremental adoption

### Calendar/data mismatch
- handle later via availability model

## Conclusion

Session 33a builds directly on Session 33b.

We now move from:

> implicit date-based sessions

to:

> explicit session coordinates with canonical timestamp boundaries

This enables:

- correct time semantics
- deterministic backtests
- clean system architecture
- future extensibility

## Next Step

Proceed with:

> **Implementation of MXMBusinessCalendar using canonical timestamps**
