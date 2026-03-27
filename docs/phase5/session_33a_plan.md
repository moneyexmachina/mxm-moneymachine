# session_33a_plan.md

## Session 33a — MXM Business Session Abstraction & Calendar System

## Summary

Session 33 revealed that the observed issues (e.g. degraded market data, missing marks) are not primarily **data problems**, but **time-domain modelling problems**.

We have implicitly treated:

> session ≈ date label

This is only a special case.

We now formalize:

> **A session is a coordinate in an ordered decision-time domain defined by a calendar**

This session establishes:

- a **canonical session abstraction**
- a **calendar as first-class data object**
- a **clean separation between identity and representation**
- a **foundation for deterministic, performant, and extensible time handling**

## Core Insight

### Previous implicit model (v1 so far)

- Session = date label (`np.datetime64[D]`)
- Used as:
  - identity
  - join key
  - index

### Revised model

> **Session = integer ordinal (`session_id`) within a specific calendar (`calendar_id`)**

Formally:

```
(session_id, calendar_id) ∈ CalendarDomain
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

- `calendar` defines interpretation

### External (storage / interchange)

```python
calendar_id: str
session_id: int
```

Optional:
```python
session_label: date  # for readability only
```

## Fundamental Invariant

> **A session_id is only valid under exactly one calendar_id**

Implications:

- session_ids are **not globally meaningful**
- all operations must respect calendar identity
- mixing calendars is an error

## Conceptual Model

> **Calendar = ordered domain + coordinate system**

- `calendar` defines the domain
- `session_id` is a coordinate
- data is a function over that domain:

```
PnL(session_id, contract_id) → value
```

## Design Principles

### 1. Calendar is authoritative

- Defines:
  - ordered sessions
  - valid domain
  - mappings

### 2. Session identity is integer-based

- Enables:
  - fast joins
  - vectorisation
  - slicing
  - memory efficiency

### 3. Labels are representations

- Never used for:
  - joins
  - identity
  - logic

- Only for:
  - debugging
  - inspection
  - plotting

### 4. Separation of concerns

| Concept         | Responsibility                        |
|-----------------|--------------------------------------|
| Calendar        | domain definition + ordering          |
| Session ID      | coordinate within domain              |
| Label           | human-readable representation         |
| Timestamp       | real-world boundary definition        |

## Calendar as First-Class Data Artifact

Calendars are now:

> **immutable, versioned reference-data objects**

Similar in status to:
- futures metadata
- contract specifications
- instrument master data

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
5. timestamps are deterministic
6. construction policy is documented

## Calendar Construction

### Explicit Construction Policy

Calendars must be constructed from a defined policy:

```python
MXMBusinessCalendar.from_business_days(dates: np.ndarray)
```

Where:
- `dates` are pre-filtered valid business sessions

Future extension:
- rule-based construction
- product-specific calendars
- multi-frequency calendars

## MXMBusinessCalendar Interface (v1)

```python
class MXMBusinessCalendar:
    calendar_id: str

    def __len__(self) -> int

    def session_ids(self) -> np.ndarray
    def labels(self) -> np.ndarray

    def session_id_from_label(self, label) -> int
    def label_from_session_id(self, session_id: int)

    def start_ts(self, session_id: int) -> np.datetime64
    def end_ts(self, session_id: int) -> np.datetime64

    def next(self, session_id: int) -> int
    def prev(self, session_id: int) -> int

    def slice(self, start_id: int, end_id: int, inclusive: bool = True) -> np.ndarray

    def contains_label(self, label) -> bool
    def contains_session_id(self, session_id: int) -> bool

    def validate_session_id(self, session_id: int) -> None
```

## Time Semantics

Session intervals are defined as:

```
[start_ts, end_ts)
```

- half-open interval
- no overlap
- composable

## Calendar Stability Requirement

> **session_id assignment must be stable within a given calendar_id**

Implications:
- rebuilding the same calendar must produce identical mappings
- otherwise persisted data becomes invalid

Versioning handles changes:

```
mxm_business_day_v1
mxm_business_day_v2
```

## Calendar Registry & Service

### Calendar Registry (persistent)

Responsibilities:
- catalog available calendars
- store metadata
- enforce uniqueness
- track versions and families

Example metadata:

```yaml
calendar_id: mxm_business_day_v1
family: mxm_business_day
version: 1
frequency: daily
label_type: date
timezone: UTC
valid_from: 2010-01-01
valid_to: 2035-12-31
construction_policy: ...
checksum: ...
```

### Calendar Service (runtime)

Responsibilities:
- resolve `calendar_id → calendar`
- load from storage
- cache instances
- return immutable objects

Example:

```python
calendar = calendar_service.get(calendar_id)
```

## Storage Strategy

### Persisted data

Must include:
```
calendar_id
session_id
```

Optional:
```
session_label
```

### Rules

- `session_id` is authoritative
- `session_label` is informational only
- never join on labels

## Runtime Usage Pattern

### In-memory objects

```python
class TargetHoldings:
    calendar: MXMBusinessCalendar
    data: DataFrame  # indexed by session_id
```

- calendar is held by reference (not duplicated)
- session_id interpreted relative to calendar

## Compatibility Rule

> Two session-indexed objects are compatible iff they share the same calendar_id

Enforced via:

```python
assert a.calendar.calendar_id == b.calendar.calendar_id
```

## API Design Rules

### Internal APIs

Must use:
```python
session_id: int
```

Must NOT use:
```python
label: datetime
```

### Boundary APIs (CLI / plotting)

May accept labels:

```python
session_id = calendar.session_id_from_label(label)
```

Then operate exclusively in session_id space.

## Impact on Existing Components

### TargetHoldings

- move from `(date, contract_id)` to `(session_id, contract_id)`
- bind calendar object

### daily_mark

Redefined as:

```
(session_id, contract_id) → mark
```

### Backtester

- iterate over `session_id`
- use labels only for reporting

### Price Accessors (critical)

Must operate in session space:

```python
get_mark_price(contract_id, session_id)
```

NOT:
```python
get_mark_price(contract_id, date)
```

### Market Data Mapping

- source data remains date-based (`daily_stats`)
- mapping step:
  ```
  date → session_id
  ```

## Data Availability (Future Hook)

Recognize:

> calendar domain ≠ data availability

Introduce (later):

```python
is_data_available(session_id, contract_id)
```

Enables:
- imputation
- quality flags
- diagnostics

## Implementation Plan

### Step 1 — Calendar Core

- module:
  ```
  mxm.v1.time.mxm_business_calendar
  ```

- implement:
  - session_id construction
  - label mapping
  - timestamp mapping

### Step 2 — Calendar Artifact & Storage

- define artifact format
- persist calendar
- define metadata

### Step 3 — Calendar Registry

- minimal registry:
  - list of calendars
  - metadata file
  - lookup by calendar_id

### Step 4 — Calendar Service

- implement:
  - loader
  - cache
  - retrieval API

### Step 5 — Unit Tests

Test:

- monotonic ordering
- bijection:
  ```
  session_id ↔ label
  ```
- boundary correctness
- interval correctness
- stability across reload
- validation errors

### Step 6 — Adapters (Temporary)

- label → session_id conversion
- used only at boundaries

### Step 7 — First Consumer

- implement `daily_mark` on session_id basis

## Success Criteria

Session 33a is complete when:

- MXMBusinessCalendar implemented
- calendar_id + session_id model enforced
- calendar artifact + registry exist
- calendar service resolves correctly
- session_id used as canonical coordinate
- mapping is stable and tested

## Non-Goals

- multi-frequency calendars (hourly, intraday)
- event-based scheduling
- distributed registry system
- full pipeline refactor

## Risks & Mitigations

### Over-engineering
- keep v1 minimal
- single calendar sufficient

### Migration complexity
- adapter layer
- incremental refactor

### Readability loss
- persist labels
- use labels in CLI

### Calendar/data mismatch
- explicitly model availability later

## Conclusion

Session 33a establishes the **temporal backbone** of MXM.

We move from:

> session as implicit date label

to:

> session as explicit coordinate in a calendar-defined domain

This enables:

- correctness of time semantics
- deterministic behaviour
- efficient computation
- extensibility to intraday systems
- clean downstream architecture
