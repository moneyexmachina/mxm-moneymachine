# session_17b_plan.md — MXM V1
## Session 17b — Contract Selection: Listing Rank, Period Rules, and Selection Cycles

## Purpose

Session 17b implements **fully functional, authoritative contract selection**
on top of the completed temporal and calendar substrate from Session 17a.

The objective is to build a **ContractSelectorEngine** that can deterministically
resolve:

> `(product_id, as_of_timestamp, selector_rule) → instrument_id`

for all relevant selector families, with explicit semantics, typed failures, and
clear architectural separation from downstream synthetic-asset logic.

This session completes the **contract-selection layer** as a hard prerequisite
for:
- roll logic,
- holdings materialisation,
- synthetic assets.

## Context and dependencies

### Upstream (completed)
- Unified MXM-wide time utilities (UTC, tz-aware only)
- Authoritative `TradingCalendar` model
- `as_of_session(ts)` semantics (most recent completed session)
- `calendar_for_product(product_id)` via `TradingCalendarService`
- Delivery-period logic and cycles in `mxm-refdata`
  (period shifting, ordering, and expected contract construction)

### Downstream (blocked until this session completes)
- Synthetic contract definitions
- Roll windows
- Continuous futures
- Spread construction
- Holdings surfaces

## Conceptual architecture (locked for V1)

### Layering

```
UTC timestamp
      ↓
TradingCalendar.as_of_session
      ↓
Session label (datetime64[D])
      ↓
ContractSelectorEngine
      ↓
instrument_id
```

Contract selection operates **exclusively in session-label space**.
Timestamp semantics are fully resolved before rule evaluation.

## Selector taxonomy (normative)

Contract selection rules are explicitly separated by **ranking substrate**.
This avoids ambiguity (e.g. overloading “M1”).

### 1. Listing-rank selectors (exchange / vendor intent)

**Meaning**
> The *n-th eligible listed contract* of a given `period_type`, ordered by
> increasing last trading day.

**Characteristics**
- Defined within a single `(product_id, period_type)` chain
- Reflects exchange/vendor listing structure
- Independent of calendar-period arithmetic
- Canonical “front contract” semantics

**Rule form**
```yaml
kind: listing_rank
period_type: monthly
n: 1
```

**Normative semantics**
- Eligible iff `last_trading_day > as_of_session`
- Order by ascending `last_trading_day`
- `n` is 1-indexed
- Typed failure on empty chain or insufficient depth

### 2. Period selectors (calendar-period intent)

**Meaning**
> Select a contract by delivery-period identity, derived from calendar-period
> logic in `mxm-refdata`.

Examples:
- next calendar month
- next quarter
- next winter / summer season

**Characteristics**
- Uses delivery-period cycles already implemented in refdata
- Maps `(product_id, period_id)` → concrete contract
- Does not define a ranking by itself

**Rule form**
```yaml
kind: period
period_id: <delivery_period_id>
```

or (derived):
```yaml
kind: period_shift
period_type: monthly
offset: 1
```

**Note**
Period selectors may fail if the resulting contract does not exist or is not
eligible as of the session.

### 3. Selection-cycle selectors (strategy / modelling intent)

**Meaning**
> Select the *n-th slot* in a **user-defined contract cycle**, independent of
> exchange listing structure.

Examples:
- December-only contracts (e.g. carbon)
- Benchmark months only
- Custom annual / seasonal ladders

**Characteristics**
- Cycle is an explicit modelling artifact
- Separates *selection intent* from listing reality
- May skip illiquid or unwanted contracts
- Evaluated via mapping cycle slots → concrete contracts → eligibility filter

**Rule form**
```yaml
kind: cycle_rank
cycle_id: dec
n: 1
```

Cycle definitions are:
- explicit,
- serialisable,
- owned by the synthetic-asset layer (but evaluated here).

## ContractSelectorEngine (core deliverable)

### Responsibilities

- Accept `(product_id, as_of_timestamp, rule)`
- Resolve `as_of_timestamp → as_of_session`
- Dispatch rule evaluation by `rule.kind`
- Enforce eligibility and ranking semantics
- Raise typed, explicit errors
- Provide inspectable explanations

### Explicit non-responsibilities

- Pricing
- Roll logic
- Holdings / weights
- Persistence
- Caching

## Public API (locked for V1)

```python
class ContractSelectorEngine:

    def select(
        self,
        product_id: str,
        as_of: datetime,
        rule: SelectorRule,
    ) -> InstrumentId

    def explain(
        self,
        product_id: str,
        as_of: datetime,
        rule: SelectorRule,
    ) -> SelectionExplanation

    def list_supported_kinds(self) -> tuple[str, ...]
```

Optional (inspection-only, may be added later):
```python
def candidates(
    product_id: str,
    as_of: datetime,
    rule: SelectorRule,
) -> Sequence[InstrumentId]
```

## Failure semantics (normative)

All failures are **typed and explicit**.

- `NoEligibleContracts`
  - no eligible contracts exist for the rule
- `RelativeContractUnavailable`
  - rule depth exceeds available candidates
- `UnknownSelectorRule`
  - unsupported or malformed rule
- `ContractNotFound`
  - period / cycle resolves to no concrete contract

Silent fallbacks are forbidden.

## Work plan

### Step 0 — Inventory & alignment (30–45 min)
- Confirm refdata APIs for:
  - enumerating contracts by `(product_id, period_type)`
  - retrieving `last_trading_day`
- Confirm delivery-period resolution helpers
- Confirm existing exceptions to reuse or extend

### Step 1 — Selector rule models (60–90 min)
- Implement `selectors.py`:
  - immutable, hashable rule dataclasses
  - discriminated by `kind`
- Implement:
  - `ListingRankRule`
  - `PeriodRule` / `PeriodShiftRule`
  - `CycleRankRule` (structure only; logic later)
- Implement `SelectionExplanation` model

### Step 2 — Listing-rank implementation (90–120 min)
- Implement `_select_listing_rank` in `ContractSelectorEngine`
- Enforce eligibility and ordering semantics
- Add unit tests:
  - rank transitions around expiry
  - insufficient depth
  - empty chain

This completes **exchange-style contract selection**.

### Step 3 — Period selector implementation (60–90 min)
- Implement `_select_period`:
  - resolve delivery-period via refdata
  - map to concrete contract
  - enforce eligibility
- Tests:
  - valid period resolution
  - missing contract
  - ineligible contract

### Step 4 — Selection cycles (90–120 min)
- Define cycle specification model:
  - ordered list of period selectors or slots
- Implement `_select_cycle_rank`:
  - map cycle slots → concrete contracts
  - filter by eligibility
  - rank by cycle order
- Tests:
  - Dec-only cycle
  - insufficient depth
  - mixed-period cycles

### Step 5 — Explanation & inspection (45–60 min)
- Populate `SelectionExplanation.details` with:
  - as_of_session
  - candidate universe summary
  - rule-specific reasoning
- Ensure output is CLI-printable and serialisable

### Step 6 — Documentation (45–60 min)
Add:
- `docs/normative/contract_selection.md`

Covering:
- selector taxonomy
- ranking substrates
- time semantics
- examples (`listing_rank`, `period`, `cycle_rank`)
- explicit non-goals

## Acceptance criteria

Session 17b is complete when:

1. `ContractSelectorEngine` can deterministically resolve contracts for:
   - listing-rank rules,
   - period selectors,
   - selection cycles.

2. Selection works for **any UTC timestamp**, via `as_of_session`.

3. All selector families have:
   - explicit semantics,
   - typed failures,
   - test coverage.

4. No selection logic leaks into:
   - pricing,
   - roll logic,
   - synthetic assets.

5. Downstream work (synthetics) can depend on:
   - stable selector semantics,
   - inspectable explanations,
   - reproducible outcomes.

## Session outcome statement (target)

> *“MXM V1 now has a fully specified, time-aware contract-selection engine.
> Relative contracts, period-based selection, and modelling-driven selection
> cycles are resolved deterministically and transparently.
> Synthetic-asset construction can proceed without ambiguity about contract
> identity.”*
