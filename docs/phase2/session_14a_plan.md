# MXM V1 — Session 14a Plan
## Semantic & State Cleanup — Coverage, Completeness, and Temporal Correctness

**Session:** 14a (cleanup / clarification pass)  
**Parent session:** MVP S14 — Observability, Coverage, and Market Data Access  
**Phase:** Phase 2 — Market Data Completion (Tail)

## 1. Purpose of this session

Sessions 8–13 delivered **functional ingestion and orchestration**.  
Session 14 delivered **working inspection and coverage reporting**.

This session exists to **slow down deliberately** and ensure that the system’s
reported states are:

- semantically precise
- internally consistent
- defensible to a third party
- stable under automation

This is a *clarification and hygiene pass*, not a feature build.

## 2. Scope

### In scope

#### 2.1 Temporal semantics (control plane)

- UTC timestamps vs UTC day labels
- Dataset availability timestamps
- Watermark progression
- Window stepping logic
- Vendor-final detection
- Canonical formatting and parsing
- Removal of pandas from control-plane timestamp logic

#### 2.2 Coverage and completeness semantics

- Formal definition of:
  - `complete`
  - `incomplete`
  - `empty_expected`
  - `vendor_final`
  - `blocked`
  - `error`
- Relationship between:
  - interest window
  - dataset availability window
  - lifecycle window
  - expected window
  - stored / observed window

#### 2.3 State derivation logic

- Contract-level state derivation
- Product-level aggregation rules
- System-level aggregation rules
- Consistency checks between:
  - attempt status
  - coverage windows
  - derived completeness

#### 2.4 Inspection semantics

- Ensure inspection reports reflect **states**, not implementation artefacts
- Ensure labels are:
  - mutually exclusive
  - clearly named
  - stable over time
  - explainable without code inspection

## 3. Explicit non-goals

This session deliberately does **not**:

- add new ingestion logic
- refactor attempt schemas
- add dashboards or GUIs
- fully type-safe vendor adapters
- optimise performance
- deploy or automate runs

## 4. Temporal semantics — agreed foundations

### 4.1 Timestamp classes

#### Control-plane timestamps (strict)

Used for logic and comparisons:

- `run_ts_utc`
- `ts_recv_last`
- dataset availability timestamps
- expected window boundaries

Rules:
- always UTC
- timezone-aware
- canonical ISO8601Z with microseconds
- parsed and manipulated via `time_utils`

#### System-plane timestamps (loose)

Used for ordering and display only:

- `created_at`
- `updated_at`

Rules:
- may have millisecond precision
- not parsed for logic
- never used for interval math

### 4.2 Daily bar semantics

- OHLCV daily bars are labelled by **UTC day**
- A bar labelled `YYYY-MM-DDT00:00:00Z` represents the entire UTC day
- Coverage logic operates in **day-label space**, not exchange session space
- Vendor timestamps must be mapped into day labels explicitly

## 5. Coverage surfaces (conceptual model)

For each contract we reason over four surfaces:

1. **Interest window**  
   What MXM cares about  
   (refdata: first_day_of_interest → last_trading_day)

2. **Dataset availability window**  
   What the vendor dataset can provide  
   (metadata: dataset_range.start → dataset_range.end)

3. **Lifecycle window**  
   When the instrument actually existed  
   (activation → expiration)

4. **Stored window**  
   What is currently persisted locally

Derived concepts:

- **Available window** = dataset ∩ lifecycle
- **Expected window** = interest ∩ available
- **Observed window** = min/max of stored data

## 6. Completeness semantics

### 6.1 Contract-level completeness

A contract is **complete** iff:

- expected window is non-empty AND
- stored window fully covers expected window

A contract is **empty_expected** iff:

- expected window is empty by construction
- this is *not* an error

A contract is **incomplete** iff:

- expected window is non-empty AND
- stored window does not fully cover it

### 6.2 Vendor finality (orthogonal concept)

A contract is **vendor_final** iff:

- vendor watermark is within tolerance of dataset end

Notes:
- vendor_final does **not** imply completeness
- vendor_final only explains *why* incompleteness may persist

## 7. Attempt status vs derived state

### 7.1 Attempt status (ledger-level)

Describes what happened in a run:

- `complete`
- `ingested`
- `skipped_*`
- `error`
- `dry_run`

### 7.2 Coverage state (derived)

Describes what data exists:

- `complete`
- `incomplete`
- `empty_expected`

**Rule:**  
Attempt status and coverage state must never be conflated.

## 8. Product- and system-level aggregation

### 8.1 Product-level rules (to be validated)

- Product is **complete** if all contracts are complete or empty_expected
- Product is **incomplete** if at least one contract is incomplete
- Product is **blocked** if incompleteness is solely due to cost limits
- Product is **error** if any contract is in error state

### 8.2 System-level rules

- Aggregate product states
- Identify:
  - never-run products
  - stalled products
  - progressing products

## 9. Concrete tasks for Session 14a

1. Audit all state labels and predicates
2. Ensure mutual exclusivity of states
3. Verify aggregation logic matches definitions
4. Align inspection scripts with semantic definitions
5. Remove any accidental or implicit state derivation
6. Add clarifying docstrings and comments where needed

## 10. Success criteria

Session 14a is successful if:

- every reported state can be explained unambiguously
- inspection output matches conceptual definitions exactly
- there is no confusion between:
  - “could not ingest”
  - “did not ingest”
  - “should not ingest”
- the system feels boring, legible, and trustworthy

