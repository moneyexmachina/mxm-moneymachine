# MXM V1 — Normative Semantics for OHLCV-1D Market Data

## Section 1 — Scope & Authority

### 1.1 Scope

This document defines the **authoritative, normative semantics** for the OHLCV-1D
(daily bars) market-data dataset in MXM V1.

It governs the meaning and interpretation of:

- temporal primitives and windows,
- availability and expectation surfaces,
- stored and observed data,
- completeness and vendor finality,
- attempt statuses and derived states,
- contract-, product-, and system-level reporting.

These semantics apply to:

- the OHLCV-1D orchestrator,
- all inspection and reporting code,
- any future automation, testing, or validation logic that reasons about
  OHLCV-1D coverage or state.

This document does **not** define execution mechanics, performance characteristics,
or future feature behaviour.

### 1.2 Authority

This document is the **single source of truth** for the semantic meaning of OHLCV-1D
states and coverage in MXM V1.

All of the following **must conform** to the definitions herein:

- orchestration logic,
- retry and decision policies,
- inspection and reporting outputs,
- documentation and operator interpretation.

If implementation behaviour diverges from this document, the implementation
**is incorrect**.

Changes to these semantics **must** be made by amending this document first,
and only then updating code to conform.

### 1.3 Relationship to Implementation

The semantics defined here are derived from, and constrained by, the frozen
extracted semantics of the current MXM V1 codebase, including:

- the OHLCV-1D attempts ledger schema,
- the attempts store API,
- expected-window construction logic,
- stored-data normalization and coverage computation,
- contract, product, and system inspection models.

This document **may clarify, disambiguate, or normatively select** among existing
behaviours where multiple interpretations are possible.

This document **must not invent** semantics that are unsupported by the extracted
implementation.

### 1.4 Stability Guarantees

The vocabulary and definitions introduced in this document are **policy-level
concepts** and are intended to be stable across:

- refactors,
- internal schema evolution,
- implementation rewrites.

Low-level representations (schemas, helper functions, internal flags) **may change**
provided that the externally visible semantics defined here remain invariant.

### 1.5 Non-Goals

This document explicitly does **not**:

- propose refactors or architectural changes,
- define new features or future phases,
- optimize or redesign storage formats,
- specify vendor adapters beyond their semantic effects,
- describe UI, dashboards, or visualization concerns.

### 1.6 Rationale

MXM V1 relies on deterministic, explainable reasoning about market-data coverage.
Without a single authoritative semantic reference, correctness degrades into
implicit convention and accidental behaviour.

By separating **what the system means** from **how the system is implemented**,
this document ensures that OHLCV-1D ingestion remains:

- epistemically honest,
- operationally predictable,
- defensible to third-party review,
- stable under automation.

All subsequent sections refine this authority by defining the precise primitives
and states on which MXM V1 depends.


## Section 2 — Time and Window Primitives

### 2.1 Time Standard

All timestamps **are UTC**.

All timestamps **must be interpreted as timezone-aware UTC instants**.
Any timestamp that is timezone-naive **shall be coerced to UTC** before use.

No local timezones, exchange timezones, or daylight-saving adjustments
**shall be used** in OHLCV-1D semantics.

### 2.2 Temporal Granularity

OHLCV-1D data is **day-granular**.

A “day” **is defined** as the 24-hour interval from `00:00:00Z` to
`00:00:00Z` of the following calendar day.

Intraday timestamps **shall not** influence window semantics, except
when deriving observed coverage from stored data.

### 2.3 Half-Open Interval Convention

All windows **are half-open intervals** of the form:

```
[start, end)
```

This means:

- `start` **is included**
- `end` **is excluded**

This convention **must be applied consistently** across:

- interest windows,
- dataset availability,
- lifecycle bounds,
- expected windows,
- stored windows.

No inclusive-end interpretation **is permitted**.

### 2.4 Day-Aligned Window Definition

A **day-aligned window**:

- **must** have `start` and `end` at `00:00:00Z`,
- **must** satisfy `start ≤ end`,
- **represents** an integer number of whole days.

A window with `start == end` **is an empty window**.

### 2.5 Contract Date Inputs

Contract lifecycle inputs originating from refdata **are date-based**.

When converting contract dates to timestamps:

- `first_day_of_interest` **must map to** `00:00:00Z` on that date,
- `last_trading_day` **must map to** the **end-exclusive boundary** of
  `(last_trading_day + 1 day) @ 00:00:00Z`.

This conversion **must always produce** a day-aligned half-open window.

### 2.6 Dataset Availability Inputs

Vendor dataset availability **is defined** as a half-open UTC timestamp
interval:

```
[dataset_start, dataset_end)
```

The dataset end **must be treated as exclusive**, even if provided as
a boundary timestamp.

Dataset availability **shall cap** all downstream expectations and
availability calculations.

### 2.7 Observed Timestamp Semantics

Observed timestamps derived from stored OHLCV-1D data:

- **are not required** to be day-aligned,
- **must** be UTC,
- **represent** the minimum and maximum `ts_event` values observed.

Observed timestamps **shall not** be compared directly to day-aligned
windows without normalization.

### 2.8 Normalization from Observed to Day Windows

An observed timestamp range:

```
[min_ts, max_ts]
```

**must be normalized** to a day-aligned half-open window as follows:

- `stored_start` **is** `floor_to_utc_day(min_ts)`,
- `stored_end` **is** `floor_to_utc_day(max_ts) + 1 day`.

This normalization **must be used** for all completeness and containment
checks.

### 2.9 Empty Window Semantics

A window **is empty** if and only if:

```
start == end
```

Empty windows **must be preserved explicitly** and **must not be
silently dropped**.

An empty expected window **represents a valid, intentional outcome**
and **is not an error condition**.

### 2.10 Comparison Rules

All window comparisons:

- **must** compare windows of the same alignment class
  (day-aligned to day-aligned),
- **must not** compare observed timestamps directly to expected windows,
- **must respect** half-open semantics strictly.

Implicit coercion or mixed-alignment comparison **is forbidden**.

### 2.11 Rationale

OHLCV-1D correctness depends on precise and uniform treatment of time.
Ambiguity at day boundaries produces silent off-by-one errors that are
operationally catastrophic and difficult to detect.

By enforcing:

- UTC-only semantics,
- half-open intervals,
- explicit day alignment,
- strict normalization rules,

MXM V1 guarantees that time reasoning is deterministic, inspectable,
and stable across ingestion, storage, and reporting layers.


## Section 3 — Surfaces (Interest / Dataset / Lifecycle / Available)

### 3.1 Definition of Surfaces

A **surface** is a day-aligned, half-open UTC window that constrains or
defines the availability and expectation of OHLCV-1D data for a single
contract.

Four surfaces **are defined**:

1. **Interest surface**
2. **Dataset surface**
3. **Lifecycle surface**
4. **Available surface**

Each surface **must be computed independently** before any downstream
derivations.

### 3.2 Interest Surface

The **interest surface** represents MXM’s intent to hold OHLCV-1D data
for a contract.

The interest surface **is defined** solely by refdata:

- `first_day_of_interest`
- `last_trading_day`

The interest surface **must** be constructed as a day-aligned half-open
window:

```
[first_day_of_interest @ 00:00Z,
 (last_trading_day + 1 day) @ 00:00Z)
```

The interest surface:

- **must not** be influenced by vendor availability,
- **must not** be influenced by contract lifecycle metadata,
- **may extend beyond** what the vendor can supply.

The interest surface **represents intent only**, not feasibility.

### 3.3 Dataset Surface

The **dataset surface** represents vendor-declared dataset availability
for OHLCV-1D.

The dataset surface **must be derived** from vendor metadata and **must**
be treated as a half-open UTC window:

```
[dataset_start, dataset_end)
```

The dataset surface:

- **must be day-aligned**,
- **must be interpreted as end-exclusive**,
- **must cap** all expectations and availability.

No data **shall be expected or requested** outside the dataset surface.

### 3.4 Lifecycle Surface

The **lifecycle surface** represents contract-specific activation and
expiration constraints derived from instrument definitions.

The lifecycle surface **is optional**.

When present, it **must** be constructed as follows:

- `activation_floor` **is** the UTC day floor of the activation timestamp,
- `expiration_ceiling` **is** the next UTC day boundary after expiration.

The lifecycle surface **must be day-aligned** and half-open:

```
[activation_floor, expiration_ceiling)
```

If either activation or expiration metadata is missing, the lifecycle
surface **shall be treated as undefined**.

An undefined lifecycle surface **shall not constrain availability**.

### 3.5 Available Surface

The **available surface** represents what the vendor could plausibly
supply for a contract.

The available surface **is defined** as:

- the intersection of the dataset surface and the lifecycle surface,
- or the dataset surface alone if no lifecycle surface exists.

Formally:

```
available = dataset ∩ lifecycle   (if lifecycle exists)
available = dataset               (otherwise)
```

If the intersection is empty, the available surface **is empty**.

The available surface:

- **must be day-aligned**,
- **must be half-open**,
- **represents feasibility**, not intent.

### 3.6 Independence of Surfaces

Each surface:

- **must be computed independently**,
- **must remain inspectable**,
- **must not be collapsed** into another surface.

The interest surface **shall not be clamped** by dataset or lifecycle
constraints.

The dataset surface **shall not encode** lifecycle semantics.

The lifecycle surface **shall not encode** dataset availability.

### 3.7 Surface Persistence Semantics

All surface boundaries:

- **must be persisted explicitly** in attempt records,
- **must be stored as UTC ISO-8601 timestamps**,
- **must preserve empty-window cases**.

Surface emptiness **must be representable** and **must not be inferred
implicitly**.

### 3.8 Rationale

Separating surfaces prevents the silent collapse of intent, feasibility,
and vendor constraints into a single ambiguous window.

This explicit layering:

- preserves operator intent,
- makes vendor limitations visible,
- supports correct reasoning about emptiness, completeness, and finality,
- enables deterministic inspection and reporting.

Without strict surface separation, downstream state derivation becomes
ambiguous, non-auditable, and operationally unsafe.


## Section 4 — Expected Window

### 4.1 Definition

The **expected window** represents the precise OHLCV-1D time span that MXM
expects to hold locally for a given contract.

The expected window **is defined** as a day-aligned, half-open UTC window
derived deterministically from the previously defined surfaces.

The expected window **must** be computed **once per contract per run**
and **must be persisted** as part of the attempt record.

### 4.2 Construction Rules

The expected window **must be constructed** in the following strict order:

1. Start from the **interest surface**.
2. Clamp the interest surface by the **dataset surface**.
3. Further clamp the result by the **lifecycle surface**, if present.

Formally:

```
expected = interest ∩ dataset
expected = expected ∩ lifecycle   (if lifecycle exists)
```

All intersections **must** preserve half-open semantics.

### 4.3 Boundary Semantics

The expected window:

- **must be day-aligned**,
- **must be half-open** `[start, end)`,
- **must use UTC midnight boundaries only**.

The expected start **must equal** the maximum of all applicable surface
starts.

The expected end **must equal** the minimum of all applicable surface
ends.

### 4.4 Empty Expected Window

An expected window **is empty** if and only if:

```
expected_end <= expected_start
```

An empty expected window:

- **must be explicitly represented**,
- **must not be silently dropped**,
- **must be persisted with start == end**,
- **must be marked with `is_empty = true`**.

An empty expected window **indicates** that no OHLCV-1D bars are expected
for the contract under current constraints.

### 4.5 Diagnostic Flags

The following diagnostic flags **must be derived** and persisted together
with the expected window:

- `is_vendor_limited`  
  **is true** if clamping by the dataset surface altered the interest
  window.

- `is_lifecycle_limited`  
  **is true** if clamping by the lifecycle surface altered the window.

These flags:

- **must reflect structural constraints only**,
- **must not depend on local storage state**,
- **must not depend on prior attempts**.

### 4.6 Relationship to Other Windows

The expected window:

- **is a function of surfaces only**,
- **must not depend** on stored data,
- **must not depend** on prior attempt outcomes,
- **must remain stable** across runs unless surfaces change.

The expected window **is not** a statement of completeness, success, or
vendor finality.

### 4.7 Persistence Requirements

The expected window:

- **must be persisted verbatim** in every attempt row,
- **must be stored using UTC ISO-8601 timestamps**,
- **must preserve empty-window cases without coercion**.

Downstream reporting **must trust** the persisted expected window and
**must not recompute it**.

### 4.8 Rationale

The expected window is the central normative reference against which
completeness, ingestion decisions, and reporting are evaluated.

By defining it as a pure function of explicit surfaces, MXM ensures that:

- expectations are deterministic,
- vendor and lifecycle constraints are auditable,
- empty cases are handled explicitly,
- operational logic is separated from storage state.

Any ambiguity at this layer would propagate irreversibly into state
derivation and reporting.


## Section 5 — Stored Window & Observed Data

### 5.1 Definition

**Observed data** represents the factual contents of the local OHLCV-1D store
for a given contract at a specific point in time.

The **stored window** is a normalized, day-aligned, half-open UTC window
derived from observed data.

Observed data **is descriptive only**. It **shall not encode intent,
expectation, or vendor capability**.

### 5.2 Observed Range

The observed range **is defined** as the tuple:

```
(min_ts, max_ts)
```

where:

- `min_ts` **is** the minimum `ts_event` value present in local storage,
- `max_ts` **is** the maximum `ts_event` value present in local storage.

Observed range timestamps:

- **must be tz-aware UTC timestamps**,
- **must not be day-aligned**,
- **must satisfy** `min_ts <= max_ts`.

Observed range **shall not exist** if no rows are present.

### 5.3 Stored Window Derivation

The stored window **is derived deterministically** from the observed range.

If observed range exists, the stored window **must be defined** as:

```
stored_start = floor_to_utc_day(min_ts)
stored_end   = floor_to_utc_day(max_ts) + 1 day
```

The resulting stored window:

- **must be day-aligned**,
- **must be half-open** `[stored_start, stored_end)`,
- **must represent the full days covered by stored bars**.

If observed range does not exist, the stored window **must be absent**.

### 5.4 Row Count Semantics

Observed data **must include** a `row_count` equal to the number of stored
daily bars for the contract.

Row count:

- **must be zero** if and only if no observed data exists,
- **must be greater than zero** if observed range exists,
- **must be persisted** as part of coverage snapshots.

Row count **is authoritative** for determining data presence.

### 5.5 Coverage Snapshots

Coverage snapshots **must be captured** at defined orchestration points:

- **before** any ingestion attempt,
- **after** any ingestion attempt, if ingestion occurred.

Each snapshot **must include**:

- observed range (`min_ts`, `max_ts`),
- derived stored window (if applicable),
- row count,
- storage path reference.

Coverage snapshots **must be persisted verbatim** in the attempts ledger.

### 5.6 Relationship to Expected Window

The stored window:

- **is independent of** the expected window,
- **may extend beyond** the expected window,
- **may be strictly contained** within the expected window,
- **may be absent** even when the expected window is non-empty.

Stored data **shall not redefine** expectations.

### 5.7 Persistence and Trust Model

The stored window:

- **must be derived from persisted data only**,
- **must not be recomputed heuristically**,
- **must not be inferred from attempt status**.

Reporting and completeness logic **must trust** the persisted stored window
representation.

### 5.8 Rationale

Separating observed data from expectations ensures that MXM distinguishes
between *what exists* and *what should exist*.

By deriving the stored window mechanically from observed timestamps:

- coverage is auditable,
- partial ingestion is explicit,
- completeness checks remain deterministic,
- operational errors cannot silently corrupt state.

Any ambiguity in stored window semantics would invalidate downstream
completeness and reporting guarantees.


## Section 6 — Completeness

### 6.1 Definition

**Completeness** is the determination of whether the locally stored OHLCV-1D data
fully covers the **expected window** for a contract.

Completeness **is a boolean property** evaluated relative to:

- the expected window,
- the stored window derived from observed data.

Completeness **shall not** depend on attempt history, cost decisions, or operator intent.

### 6.2 Completeness Predicate (Level 0)

Completeness **must be evaluated** using the following Level-0 predicate:

A contract **is complete** if and only if all of the following hold:

1. The expected window is empty, **or**
2. All of the following conditions are true:
   - stored data exists (`row_count > 0`),
   - stored window exists,
   - `stored_window.start <= expected_window.start`,
   - `stored_window.end   >= expected_window.end`.

This definition **shall be applied strictly** using half-open window semantics.

### 6.3 Empty Expected Window

If the expected window is empty:

- the contract **is complete by definition**,
- no stored data **is required**,
- completeness **must not imply** that data exists.

Empty expected windows **must be surfaced explicitly** and **must not be conflated**
with successful ingestion.

### 6.4 Absence of Stored Data

If the expected window is non-empty and no stored data exists:

- the contract **is incomplete**,
- completeness **must be false**,
- vendor finality **shall not override** incompleteness at this stage.

At least one ingestion attempt **is required** before any terminal classification.

### 6.5 Stored Data Outside Expected Window

Stored data **may extend beyond** the expected window.

Such excess data:

- **shall not affect** completeness negatively,
- **shall not redefine** the expected window,
- **shall not be pruned or ignored** for completeness checks.

Completeness **is evaluated by containment**, not equality.

### 6.6 Independence from Vendor Finality

Completeness **is orthogonal** to vendor finality.

Vendor finality:

- **shall not** modify the completeness predicate,
- **shall not** convert incomplete coverage into complete coverage,
- **may only** affect higher-level derived states and decisions.

### 6.7 Reporting Semantics

Completeness **must be reported** consistently across:

- contract inspection,
- product-level aggregation,
- system-level aggregation.

Any contradiction between:

- stored window coverage, and
- attempt status indicating completion

**must be treated as an error signal** in reporting layers.

### 6.8 Rationale

Completeness defines the factual boundary between *coverage achieved* and
*coverage missing*.

By grounding completeness strictly in window containment:

- correctness is verifiable,
- retries are explainable,
- partial data cannot masquerade as success,
- reporting remains invariant under refactors.

Any relaxation of this definition would introduce ambiguity into ingestion,
retry policy, and operational trust.


## Section 7 — Vendor Finality

### 7.1 Definition

**Vendor finality** is a declarative property indicating that, given the current
vendor dataset availability and known instrument lifecycle bounds, no additional
vendor data **can** extend the expected window for a contract.

Vendor finality **is not** a statement about local data completeness.

### 7.2 Basis of Vendor Finality

Vendor finality **must be derived** solely from:

- the vendor dataset availability window, and
- the instrument lifecycle bounds (when known).

Vendor finality **shall not** depend on:

- local storage state,
- attempt history,
- ingestion success or failure,
- operator configuration.

### 7.3 Lifecycle-Constrained Finality

If an expiration ceiling exists for a contract:

- the contract **is vendor-final** if and only if
  `dataset_end >= expiration_ceiling`.

In this case:

- no future vendor data **shall** extend the expected window,
- the expected window **is fully determined** by lifecycle constraints.

### 7.4 Dataset-Limited Finality

If lifecycle bounds are unknown or absent:

- vendor finality **shall not be inferred** from dataset availability alone.

A contract **must not** be marked vendor-final solely because:

- the dataset end coincides with or precedes the expected window end.

Vendor finality **requires explicit lifecycle termination**.

### 7.5 Orthogonality to Completeness

Vendor finality **is orthogonal** to completeness.

Specifically:

- vendor finality **shall not** imply completeness,
- vendor finality **shall not** alter the completeness predicate,
- incomplete coverage **remains incomplete** even when vendor-final.

Vendor finality **only constrains future expectations**, not present facts.

### 7.6 Role in State Derivation

Vendor finality **may be used** to derive higher-level operational states.

In particular:

- vendor-final contracts **may** transition to terminal derived states
  even when incomplete,
- such transitions **must not** be expressed as completeness.

Derived states **must preserve** the distinction between:
- “no more data can exist”, and
- “all expected data exists”.

### 7.7 Reporting Semantics

Vendor finality **must be reported explicitly** and independently.

Reports **shall**:

- surface vendor finality as a separate boolean attribute,
- avoid encoding vendor finality into status labels such as “complete”.

Any report implying completeness **must** be justified exclusively
by stored window coverage.

### 7.8 Rationale

Vendor finality explains *why* coverage cannot improve; it does not assert
that coverage is sufficient.

By separating vendor finality from completeness:

- retry logic remains honest,
- partial-but-final data is distinguishable from success,
- operational decisions remain auditable.

Conflating these concepts would erase the difference between
*impossibility* and *achievement*, undermining system truthfulness.


## Section 8 — Attempt Statuses

### 8.1 Definition

An **attempt status** is a canonical, persisted label describing the outcome of a
single orchestration attempt for a specific contract.

Each attempt status **must** represent exactly one attempt row and **must not**
encode derived, aggregated, or inferred meaning.

Attempt statuses **are historical facts** and **shall not change** once recorded.

### 8.2 Authoritative Status Set

The authoritative set of attempt statuses **is fixed** and **shall** consist of
the following values only:

- `unmapped`
- `skipped_empty_expected_window`
- `complete`
- `dry_run`
- `skipped_cost_cap`
- `ingested`
- `incomplete`
- `error`

No additional statuses **may** be introduced without amending this document.

### 8.3 Status Semantics

Each attempt status **shall** have the following precise meaning.

#### 8.3.1 `unmapped`

- The contract **could not** be resolved to a vendor instrument identity.
- No vendor call **was attempted**.
- The expected window **was derived** without lifecycle bounds.

This status **is blocking**.

#### 8.3.2 `skipped_empty_expected_window`

- The derived expected window **was empty**.
- No vendor call **was attempted**.
- Local storage **must not** be modified.

This status **is terminal** for the contract.

#### 8.3.3 `complete`

- No vendor call **was attempted**.
- Local data **already satisfied** the completeness predicate, or
- the contract **was vendor-final** and previously ingested.

This status **must not** imply that a vendor call occurred.

#### 8.3.4 `dry_run`

- The orchestrator **evaluated** the contract.
- No vendor call **was executed** due to dry-run mode.
- No local storage **was modified**.

This status **is non-terminal** and **non-authoritative** for completeness.

#### 8.3.5 `skipped_cost_cap`

- A vendor call **was not executed** due to budget constraints.
- Either:
  - the estimated cost exceeded remaining budget, or
  - remaining budget was exhausted.

This status **is non-terminal** and **may be retried**.

#### 8.3.6 `ingested`

- A vendor call **was executed**.
- Data **was written** to local storage.
- Post-ingest completeness **may or may not** have been achieved.

Completeness **must be evaluated separately**.

#### 8.3.7 `incomplete`

- A vendor call **was executed**.
- Local data **does not** satisfy the completeness predicate.
- The contract **is not vendor-final**.

This status **is non-terminal** and **requires further ingestion**.

#### 8.3.8 `error`

- An exception **occurred** during orchestration.
- The attempt **did not complete successfully**.
- Error type and message **must** be recorded.

This status **may** be retryable or terminal depending on classification.

### 8.4 Status vs. Windows

Attempt statuses **shall not** encode:

- window completeness,
- vendor finality,
- lifecycle knowledge.

Attempt statuses **must** be interpreted together with:

- expected window,
- stored window,
- vendor finality flags.

Any logic requiring window comparison **must not** rely on status alone.

### 8.5 Status Persistence Rules

For each contract considered in a run:

- exactly one attempt status **must** be recorded,
- status recording **must** occur even if the run halts afterward,
- status recording **must** precede any loop termination.

Attempt rows **are append-only**.

### 8.6 Rationale

Attempt statuses describe *what happened*, not *what is true*.

By constraining statuses to operational facts:

- historical audits remain reliable,
- derived state logic remains pure,
- reporting avoids conflation of process and outcome.

This separation ensures that orchestration behavior can evolve
without rewriting historical meaning.


## Section 9 — Derived States

### 9.1 Definition

A **derived state** is a deterministic, non-persisted classification of a contract
computed from authoritative inputs.

Derived states **are not stored**, **shall not be recorded**, and **must be
recomputable** at any time from persisted facts.

Derived states **exist solely** to drive orchestration decisions.

### 9.2 Authoritative Inputs

Derived states **must be derived exclusively** from the following inputs:

- the latest attempt row for the contract (if any),
- the derived expected window,
- the current stored coverage snapshot,
- the vendor finality flag,
- the mapping status of the contract,
- the operator reset flag (if provided).

No other inputs **may** influence derived state computation.

### 9.3 Authoritative State Set

The authoritative set of derived states **is fixed** and **shall** consist of:

- `DONE`
- `BLOCKED_UNMAPPED`
- `BLOCKED_EMPTY_EXPECTED`
- `NEEDS_INGEST`
- `RETRYABLE_ERROR`
- `FINAL_ERROR`
- `SKIPPED_BUDGET`
- `UNKNOWN`

No additional derived states **may** be introduced without amending this document.

### 9.4 Precedence Rules

Derived state evaluation **must** apply the following precedence rules, in order:

1. Structural blockers
2. Operator overrides
3. Coverage-based completion
4. Vendor finality allowances
5. Attempt-based signals
6. Default fallback

Later rules **shall not** override earlier ones.

### 9.5 State Semantics

Each derived state **shall** have the following meaning.

#### 9.5.1 `BLOCKED_UNMAPPED`

- The contract **is not mapped** to a vendor instrument.
- No ingestion **can** occur.

This state **is terminal** until mapping exists.

#### 9.5.2 `BLOCKED_EMPTY_EXPECTED`

- The expected window **is empty**.
- No data **is expected** to exist.

This state **is terminal**.

#### 9.5.3 `DONE`

- Either:
  - the stored window **is complete** relative to the expected window, or
  - the contract **is vendor-final** and **has any stored data**.

This state **does not assert completeness** in the vendor-final case.

#### 9.5.4 `NEEDS_INGEST`

- The contract **is mapped**.
- The expected window **is non-empty**.
- The stored window **is missing or incomplete**.
- The contract **is not vendor-final**, or has no stored data.

This state **requires** an ingestion attempt.

#### 9.5.5 `SKIPPED_BUDGET`

- The latest attempt **was skipped** due to budget constraints.

This state **is non-terminal** and **may** transition once budget is available.

#### 9.5.6 `RETRYABLE_ERROR`

- The latest attempt **ended in error**.
- The error **is not classified** as systemic or terminal.

This state **permits retry** subject to retry policy.

#### 9.5.7 `FINAL_ERROR`

- The latest attempt **ended in error**.
- The error **is classified** as systemic or terminal.

This state **requires operator intervention**.

#### 9.5.8 `UNKNOWN`

- The contract **cannot be classified** under the defined rules.

This state **must** halt orchestration.

### 9.6 Reset Override

If the operator reset flag is set:

- `DONE` **shall not** be returned,
- `NEEDS_INGEST` **must** be returned unless blocked by emptiness or mapping.

Reset **shall not** override structural blockers.

### 9.7 Purity Requirement

Derived state computation **must be pure**:

- no IO,
- no vendor calls,
- no mutation,
- no persistence.

The same inputs **must always** yield the same derived state.

### 9.8 Rationale

Derived states separate *decision logic* from *historical fact*.

By enforcing purity and precedence:

- orchestration behavior is predictable,
- retries are controlled,
- blocking conditions are explicit.

This design prevents accidental coupling between past execution outcomes
and present system truth.


## Section 10 — Reporting Semantics (Contract / Product / System)

### 10.1 Purpose

Reporting **is** a read-only interpretation layer over persisted attempt data.

Reporting **must not** trigger ingestion, mutation, retries, or vendor calls.

Reporting **shall** reflect the latest persisted facts and derived semantics only.

### 10.2 Authoritative Inputs

All reports **must** be derived exclusively from:

- the latest attempt row per `contract_key`,
- the persisted attempt fields,
- deterministic window and completeness rules defined in this document.

Reports **shall not** infer state from external systems or live storage scans.

### 10.3 Contract-Level Reporting

#### 10.3.1 Unit of Reporting

The contract-level report **is defined** per unique `contract_key`.

Exactly one attempt row **shall** be considered: the latest attempt by
`(run_ts_utc, created_at, attempt_uid)` ordering.

#### 10.3.2 Contract Coverage Model

A contract report **must** expose:

- identity fields (`product_id`, `contract_id`, `contract_key`),
- coverage surfaces (interest, dataset, lifecycle),
- derived windows (available, expected),
- stored observed range and stored window,
- completeness relative to expected,
- vendor finality,
- the latest attempt summary.

The expected window **must** be taken verbatim from the persisted attempt row.

#### 10.3.3 Contract Completeness Reporting

Contract completeness **shall** be reported as follows:

- `True` if the stored window fully contains the expected window,
- `False` if the stored window does not contain the expected window,
- `False` if no stored window exists and expected is non-empty,
- `True` if the expected window is empty.

Vendor finality **shall not** override window-based completeness reporting.

### 10.4 Product-Level Reporting

#### 10.4.1 Unit of Reporting

The product-level report **is defined** as the aggregation of all contract-level
reports for a given `product_id`.

Each contract **shall** contribute exactly once.

#### 10.4.2 Product Status Classification

The product status **shall** be classified as one of:

- `never_run`
- `done`
- `partial`
- `blocked`
- `error`

#### 10.4.3 Product Status Rules

Product status **must** be determined using the following rules:

- `never_run`  
  **is** returned if no attempts exist for the product.

- `done`  
  **is** returned if all contracts are complete and no contracts are
  unmapped, cost-blocked, or in error.

- `error`  
  **is** returned if any contract reports an error or inconsistent completeness.

- `blocked`  
  **is** returned if any contract is unmapped or cost-blocked and no errors exist.

- `partial`  
  **is** returned otherwise.

These rules **must** be applied in the order listed.

#### 10.4.4 Product Counts

Product-level reports **must** include counts of:

- total contracts,
- complete contracts,
- incomplete contracts,
- empty-expected contracts,
- vendor-final contracts,
- unmapped contracts,
- cost-blocked contracts,
- error contracts.

Counts **must** be derived from contract-level reports only.

### 10.5 System-Level Reporting

#### 10.5.1 Unit of Reporting

The system-level report **is defined** as an aggregation across all products
with at least one recorded attempt.

#### 10.5.2 System Product Rows

Each product **must** contribute one system-level row containing:

- product identifier,
- product status,
- status reason,
- contract counts,
- last run timestamp,
- last run mode.

#### 10.5.3 System Status Semantics

System-level reporting **shall not** compute a single global status.

Each product **must** be classified independently using product-level rules.

### 10.6 Freshness Semantics

Freshness **is defined** solely by the maximum `run_ts_utc` across relevant
attempt rows.

Freshness **does not imply** vendor recency or market completeness.

### 10.7 Consistency Rules

Reporting **must** satisfy the following consistency rules:

- A contract reported as complete **must** satisfy window completeness rules.
- A contract reported as incomplete **must not** be counted as complete.
- A product reported as `done` **must not** include any incomplete contracts.

Violations **must** be surfaced as error classifications.

### 10.8 Rationale

Reporting semantics provide a deterministic, auditable view of system state
without altering it.

By enforcing strict read-only aggregation and explicit status rules:

- operators can reason about coverage safely,
- orchestration logic remains isolated,
- historical truth is preserved without reinterpretation.


## Section 11 — Invariants & Non-Negotiables

### 11.1 Authority of Persisted Facts

- The attempts ledger **is** the sole authoritative record of operational history.
- Persisted attempt rows **must not** be rewritten, amended, or reinterpreted after insertion.
- Derived views **shall** be recomputable from persisted rows without loss of meaning.

### 11.2 Determinism

- All derivations **must** be pure, deterministic, and side-effect free.
- Given identical persisted inputs, derived states and reports **shall** be identical.
- No derivation **may** depend on wall-clock time, external services, or mutable global state.

### 11.3 Time Semantics

- All timestamps **must** be UTC.
- All day-aligned windows **must** be half-open `[start, end)`.
- All window boundaries **shall** be normalized to UTC midnight.
- Mixed or ambiguous timezone representations **are forbidden**.

### 11.4 Window Consistency

- Interest, dataset, lifecycle, available, expected, and stored windows **must** obey half-open semantics.
- Empty windows **must** be represented explicitly with `start == end`.
- Stored observed ranges **must not** be compared directly to expected windows without normalization.

### 11.5 Completeness Integrity

- Completeness **is defined** solely by window containment rules.
- Completeness **must not** be inferred from attempt status strings.
- Vendor finality **shall not** override window-based completeness checks.

### 11.6 Vendor Finality Integrity

- Vendor finality **must** be derived only from dataset advancement relative to lifecycle expiration.
- Vendor finality **shall not** imply local completeness in the absence of stored data.
- Vendor finality **must** be persisted explicitly and **shall not** be recomputed implicitly in reports.

### 11.7 Attempt Semantics

- Exactly one attempt row **must** be recorded per contract per orchestrator consideration.
- Attempt statuses **must** remain stable once introduced.
- Attempt statuses **shall not** encode derived state semantics.

### 11.8 Derived State Separation

- Derived states **must** be computed, not persisted.
- Derived states **shall** remain policy-level abstractions.
- Changes to orchestration logic **must not** alter historical attempt semantics.

### 11.9 Reporting Purity

- Reporting **must** be strictly read-only.
- Reports **shall not** trigger ingestion, retries, deletions, or vendor calls.
- Reports **must** reflect only persisted attempts and deterministic derivations.

### 11.10 Error Signaling

- Invariant violations **must** surface as explicit error classifications.
- Silent correction, auto-repair, or implicit coercion **is forbidden**.
- Inconsistent states **shall** be treated as operator-visible faults.

### 11.11 Evolution Rules

- New attempt statuses **may** be added but **must not** change the meaning of existing ones.
- New derived states **may** be introduced only as refinements, not reinterpretations.
- Backward compatibility of persisted data **is mandatory**.

### 11.12 Rationale

These invariants enforce a hard separation between fact, interpretation, and action.

By declaring these constraints non-negotiable:

- historical truth remains stable,
- reasoning remains auditable,
- orchestration logic remains evolvable without data corruption,
- operators retain trust in system outputs.

Any violation of these rules **is** a correctness failure, not a recoverable condition.
