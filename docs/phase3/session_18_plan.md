# session_18_plan.md — MXM V1
## Session 18 — Contract Selection Semantics & Engine

## Purpose

Session 18 implements **deterministic contract selection** for MXM V1.

The goal is to resolve a concrete futures contract as a **pure, inspectable
function** of:

> (product_id, as_of_timestamp, selection_rule)

using the now-stable refdata layer from Session 17c.

This session establishes the **contract identity resolution layer** that all
downstream components (roll logic, synthetic assets, holdings) will depend on.

**Importantly:**  
Session 18 resolves *which contract* is selected — **not how it is named or
labelled**. Contract labelling is deferred explicitly to Session 19.

## Preconditions (satisfied)

- `mxm-refdata` is schema-consistent, type-sound, and tested
- Products expose `period_types: tuple[PeriodType, ...]`
- Contracts can be retrieved and filtered by `PeriodType`
- Trading calendars provide `as_of_session(ts)` semantics

No refdata changes are expected or permitted in this session.

## Conceptual model (locked)

### Two-layer selection model

#### 1. PeriodFilter

Defines the admissible delivery periods.

Structure:
```python
PeriodFilter(
    period_type: PeriodType,
    cycle_elements: frozenset[int] | None
)
```

Semantics:
- `cycle_elements is None` → no filtering (use listing as-is)
- otherwise: only keep periods whose cycle index is in `cycle_elements`
  (e.g. `{12}` for December in a MONTH cycle)

Notes:
- Filtering operates in **period space**, not contract space
- Period ordering is inherited from refdata

#### 2. SelectorRule

Defines ranking and selection within the admissible set.

Structure:
```python
SelectorRule(
    period_filter: PeriodFilter,
    n: int
)
```

Normative semantics:
- Eligible contracts:
  - belong to the filtered periods
  - `last_trading_day > as_of_session`
- Ranking:
  - ascending `last_trading_day`
- Selection:
  - return the `n`-th eligible contract (1-indexed)

## Scope of implementation

### In scope

1. **Selector rule & filter models**
   - Immutable, hashable dataclasses
   - Serializable (config / audit safe)
   - Label-agnostic

2. **ContractSelectorEngine**
   - Public API:
     ```python
     select(product_id, as_of_ts, rule) -> contract_id
     explain(product_id, as_of_ts, rule) -> SelectionExplanation
     ```
   - Responsibilities:
     - resolve `as_of_ts → as_of_session`
     - retrieve contracts via refdata
     - apply `PeriodFilter`
     - enforce eligibility cutoff
     - rank and select deterministically
     - raise typed failures

3. **Failure semantics**
   - `NoEligibleContracts`
   - `RelativeContractUnavailable`
   - `UnknownSelectorRule`
   - No silent fallbacks

4. **Inspection & explanation**
   - Structured explanation including:
     - as_of_session
     - admissible / eligible counts
     - selected contract_id
     - key decision points

### Explicit non-goals (by design)

This session does **not**:

- assign labels such as `M1`, `Dec1`, `Q+1`
- define or resolve `relative_contract_id`
- provide human-readable shorthand identifiers
- implement roll windows or synthetic assets
- introduce persistence or caching
- infer semantics from exchange naming conventions

These are **explicitly deferred to Session 19**.

## Work plan

### Step 1 — Selector rule & filter models
- Implement `PeriodFilter`
- Implement `SelectorRule`
- Define canonical serialisation (dict / YAML-ready)

### Step 2 — Engine skeleton
- Define `ContractSelectorEngine`
- Wire refdata + trading calendar services
- Implement dispatch & input validation

### Step 3 — Core selection logic
- Retrieve contracts by product & period_type
- Apply `PeriodFilter`
- Apply eligibility cutoff (`last_trading_day > as_of_session`)
- Rank by last trading day
- Select `n`

### Step 4 — Failure & boundary tests
- Empty admissible set
- Eligibility cutoff edge cases
- Insufficient depth
- As-of exactly on last trading day

### Step 5 — Explanation surface
- Implement `SelectionExplanation`
- Ensure CLI-printable and serialisable output

## Acceptance criteria

Session 18 is complete when:

1. Contract selection is deterministic and reproducible
2. Selector semantics are explicit, minimal, and tested
3. Failures are typed and non-silent
4. No refdata or roll logic is duplicated
5. Downstream code can rely on stable contract identity resolution

## Explicit hand-off to Session 19

Session 19 will build **on top of Session 18 outputs** and will address:

- Canonical, unambiguous identifiers:
  ```text
  canonical_relative_id
  ```
  (fully specified, stable, machine-safe)

- Optional ergonomic identifiers:
  ```text
  short_id
  ```
  (human-readable, potentially ambiguous, context-dependent)

- Mapping from:
  ```
  (SelectorRule, PeriodFilter, n)
      → canonical_relative_id
      → short_id
  ```

Session 18 intentionally produces **no naming side effects** so that
Session 19 can reason about labels independently and explicitly.

## Session outcome statement (target)

> *“MXM V1 can now resolve contract identity deterministically and
> transparently from product, period intent, and as-of time.
> Naming, labelling, and human ergonomics are deferred cleanly to the
> next layer.”*
