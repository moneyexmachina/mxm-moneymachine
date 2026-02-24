# session_18_log.md — MXM V1  
## Session 18 — Contract Selection Semantics & Engine (Completed)

## Session intent

Session 18 aimed to implement a **deterministic, inspectable contract-selection engine** for MXM V1.

The objective was to resolve a concrete futures contract as a pure function of:

    (product_id, as_of_timestamp, selector_rule)

using the now-stable `mxm-refdata` layer (post Session 17c) and the authoritative
trading calendar service.

This session deliberately excluded:

- roll logic,
- synthetic assets,
- persistence,
- human-readable naming,
- canonical relative identifiers.

The sole goal was to establish a stable and minimal **contract identity resolution layer**.

## Conceptual model (locked)

### Two-layer selection model

#### 1. PeriodFilter

Defines admissible delivery periods.

```python
PeriodFilter(
    period_type: PeriodType,
    cycle_elements: frozenset[int] | None
)
```

Semantics:

- `cycle_elements is None` → no subset filtering  
- otherwise → keep only periods whose cycle index is in the set  
  (e.g. `{12}` for December in a monthly cycle)

Filtering operates in **period space**, not contract naming space.

#### 2. SelectorRule

Defines selection depth within admissible periods.

```python
SelectorRule(
    period_filter: PeriodFilter,
    n: int
)
```

Normative semantics:

- Eligible contracts:
  - belong to admissible periods
  - satisfy `last_trading_day > as_of_session`
- Ranking:
  - ascending `last_trading_day`
  - deterministic tie-break by `contract_id`
- Selection:
  - return the `n`-th eligible contract (1-indexed)

## Engine semantics (implemented)

For a given `(product_id, as_of_timestamp, rule)`:

1. Resolve `as_of_timestamp → as_of_session` via `TradingCalendar.as_of_session`
2. Retrieve full contract chain from `RefDataAPI.get_contracts_for_product`
3. Apply `PeriodFilter`
4. Apply eligibility predicate  
   `last_trading_day > as_of_session`
5. Sort deterministically:
   - `last_trading_day` ascending
   - `contract_id` ascending (tie-break)
6. Select `n`-th eligible contract

Failure semantics:

- `NoEligibleContracts`
- `RelativeContractUnavailable`

No silent fallbacks.

## Implementation highlights

### 1. PeriodIndex

Introduced `PeriodIndex` as a lightweight, immutable lookup layer
constructed from `RefDataAPI.get_periods()`.

Purpose:

- authoritative period resolution
- stable period ordering reuse
- avoid repeated API lookups

### 2. ContractSelectorEngine

- Immutable dataclass
- Built via:

```python
ContractSelectorEngine.build(refdata, calendars)
```

Public API:

```python
select(product_id, as_of_ts, rule) -> contract_id
explain(product_id, as_of_ts, rule) -> SelectionExplanation
```

`explain()` produces a fully serialisable inspection artifact:

- product_id
- as_of_utc
- as_of_session
- rule surface
- selected_contract_id
- outcome
- failure_type
- structured details

### 3. Human smoke script

Created interactive script:

```
scripts/contracts/smoke_contract_selection.py
```

Capabilities:

- Point-in-time explain surface
- Daily time-series generation:
  
  ```
  date -> selected contract_id
  ```

- Produces a step-function "FuturesContractSeries"
  for relative selection rules (e.g. front-by-LTD).

Example:

```bash
poetry run python scripts/contracts/smoke_contract_selection.py \
    --product cme_emini_snp500_futures \
    --start 2026-01-01 --end 2026-06-30 \
    --rule M1
```

Output:

```
unique : 3 contracts
changes:
  2026-01-01 -> Mar-2026
  2026-03-21 -> Jun-2026
  2026-06-20 -> Sep-2026
```

This confirmed:

- Correct eligibility semantics
- Deterministic boundary behavior
- Stable contract switching at LTD transitions

## Important observation (naming semantics)

The “M1” rule preset selects:

> the nearest eligible contract by last trading day

It does **not** mean:

> the next calendar month

This distinction is crucial.

Session 18 resolves **identity by rule**, not **calendar-relative naming**.

This directly motivates Session 19.

## Tests

Added comprehensive unit tests:

- PeriodFilter validation
- SelectorRule validation
- Eligibility boundaries
- Depth exhaustion
- Deterministic ordering
- Explain surface shape

All tests passing (108 total across MXM V1).

## Dependencies integrated

Session 18 required upstream improvements to `mxm-refdata`:

- `PeriodCycle` and `PeriodCycleMembership` domain + ORM
- `get_period_by_id` / `get_periods_by_id`
- RefDataAPI deterministic contract ordering

Refdata upgraded to version `0.2.1`.

Smoke rebuild confirms:

- cycles present
- memberships unique
- calendar mapping validated

## Explicit non-goals (still deferred)

Session 18 does NOT:

- define canonical relative identifiers
- provide short ergonomic names
- create roll windows
- infer exchange naming semantics
- implement synthetic assets
- implement persistence or caching at selector level

## Acceptance criteria (verified)

1. Deterministic contract identity resolution ✓  
2. Explicit and minimal semantics ✓  
3. Typed failure surface ✓  
4. No duplication of refdata or roll logic ✓  
5. Stable foundation for synthetic assets ✓  

## Session outcome statement

> “MXM V1 can now resolve contract identity deterministically and transparently from product, period intent, and as-of time. Naming, labelling, and human ergonomics are cleanly deferred to the next layer.”

## Next session: 19 — Contract Labelling Layer

Session 19 will introduce:

- `canonical_relative_id`
- `short_id`
- Mapping from selector intent → label surface
- Explicit distinction between:
  - Front-by-LTD
  - Calendar-relative
  - Cycle-relative (e.g. Dec-only)

Session 19 will sit **above** the Session 18 engine without modifying it.

**Session 18: Complete.**
