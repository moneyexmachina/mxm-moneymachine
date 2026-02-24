# session_17_plan.md — MXM V1  
## Session 17 — Relative Contracts & Contract Selection

## Purpose

Session 17 establishes **relative contracts** as a first-class, authoritative abstraction in MXM V1.

The goal is to answer, *correctly and reproducibly*:

> “Which contract does ‘M1’, ‘M2’, or ‘Dec1’ refer to on this trading day?”

This session builds the **contract selection engine** that sits directly on top of the trading-calendar substrate completed in Session 16 and directly underneath synthetic asset construction.

No pricing, no holdings, no roll interpolation yet.  
This session is about **selection semantics only**.

## Context and dependency

### Upstream (already complete)
- `TradingCalendar` with observed vs projected authority
- Deterministic trading-day arithmetic
- `last_trading_day` surfaced on all v1 futures contracts
- Contract metadata available via refdata

### Downstream (blocked until this session completes)
- Roll window logic
- Holdings surface materialisation
- Synthetic asset definitions (`M1`, `M2`, `Dec1`, spreads)

Session 17 is therefore a **hard dependency** for all synthetic asset work.

## Scope

### In scope
- Definition of *relative contracts*
- Deterministic contract eligibility and ranking
- Selector specifications (`M1`, `M2`, `Dec1`)
- A reusable, test-covered **RelativeContractEngine**
- Clear, normative semantics for edge cases

### Out of scope
- Roll interpolation
- Holdings surfaces
- Pricing / NAV / P&L
- FX conversion
- Strategies or signals

## Conceptual model (locked for V1)

### 1. Absolute vs relative contracts

- **Absolute contract**  
  A specific futures contract, identified by `instrument_id`.

- **Relative contract**  
  A *rule-based reference* that resolves to an absolute contract *as of a trading date*.

Examples:
- `M1` → front contract
- `M2` → second contract
- `Dec1` → next December contract

A relative contract **has no independent existence** outside `(product_id, as_of_date)`.

### 2. Contract eligibility (normative)

For a given `product_id` and trading date `t`:

A contract `c` is **eligible** iff:

- `last_trading_day(c) > t`

Optional exclusions (V1 default: **off**, but supported):
- minimum business days to LTD (e.g. exclude contracts with `bdays_to_ltd < k`)

Eligibility is evaluated **strictly in trading-day space**, using the product’s trading calendar.

### 3. Relative ranking (normative)

For all eligible contracts of a product on date `t`:

1. Sort contracts by ascending `last_trading_day`
2. Assign ranks:
   - rank 1 → `M1`
   - rank 2 → `M2`
   - …
3. Ranking is **stable and deterministic**

This ranking defines the canonical meaning of `M<n>` in MXM V1.

### 4. Fixed-month selection (normative)

For selectors like `Dec1`:

1. Filter eligible contracts to those with:
   - `contract_month == 12`
2. Sort by `last_trading_day`
3. Select the first (`Dec1`), second (`Dec2`), etc.

This is independent of `M<n>` ranking and evaluated separately.

## Deliverables

### 1. RelativeContractEngine (core)

A new core component providing **all contract-selection semantics**.

#### Primary responsibilities
- enumerate eligible contracts
- rank contracts relative to a trading date
- resolve selector specs into concrete contract IDs

#### Public API (indicative)

```python
class RelativeContractEngine:
    def list_eligible(
        self,
        product_id: str,
        as_of: date,
    ) -> list[InstrumentId]

    def list_relative_contracts(
        self,
        product_id: str,
        as_of: date,
        k: int,
    ) -> list[InstrumentId]

    def relative_rank(
        self,
        product_id: str,
        as_of: date,
        contract_id: InstrumentId,
    ) -> int | None

    def select(
        self,
        product_id: str,
        as_of: date,
        selector: RelativeSelector,
    ) -> InstrumentId
```

All methods are **pure functions** of:
- refdata
- calendars
- input arguments

No caching or mutation inside the engine (caching belongs one layer up).

### 2. Selector specification model

Introduce a small, explicit selector vocabulary.

#### Supported selectors (V1)

- **Rank-based**
  ```yaml
  kind: rank
  n: 1        # M1
  ```

- **Fixed month**
  ```yaml
  kind: month
  month: 12   # December
  offset: 1   # Dec1
  ```

These specs must be:
- serialisable
- hashable
- printable
- comparable (for testing and naming)

### 3. Relative-contract grids (intermediate artifact)

Provide a convenience helper:

```python
relative_contract_grid(
    product_id: str,
    dates: Sequence[date],
    k: int,
) -> list[InstrumentSeries]
```

Where each `InstrumentSeries[i]` represents:
- the contract ID for `M(i+1)` across time

This is an **intermediate building block**:
- not persisted
- used later by roll / holdings builders

### 4. Performance guarantees

Contract selection must be fast enough to support:

- thousands of trading days
- multiple selectors per product
- repeated calls during holdings materialisation

Implementation requirements:
- vectorised operations where possible
- no per-date Python loops in hot paths
- reuse of calendar index lookups (`searchsorted`-based)

Benchmarks to be added in-session.

## Edge cases (must be handled explicitly)

### 1. No eligible contracts
- Occurs before first listing or after final expiry
- Behaviour:
  - raise a typed exception (`NoEligibleContracts`)
  - never silently return `None`

### 2. Insufficient depth
- Asking for `M2` when only one eligible contract exists
- Behaviour:
  - raise `RelativeContractUnavailable`

### 3. Non-trading-day input
- `as_of` must be a trading day
- Behaviour:
  - strict by default (raise)
  - optional explicit normalisation wrapper allowed

### 4. Observed vs projected boundary
- Selection logic must not care *where* the calendar came from
- But inspection tooling must make it visible when projected calendars are in use

## Work plan

### Step 0 — Inventory & alignment (30–45 min)
- Identify refdata surfaces for:
  - contracts per product
  - contract months
  - last trading days
- Verify calendar IDs per product

### Step 1 — Eligibility & ranking core (90–120 min)
- Implement eligibility filtering
- Implement deterministic ranking by LTD
- Unit tests on synthetic calendars and mock contracts

### Step 2 — Selector resolution (60–90 min)
- Implement rank-based selectors
- Implement fixed-month selectors
- Validate behaviour across year boundaries

### Step 3 — Relative grids & helpers (60 min)
- Implement `list_relative_contracts`
- Implement `relative_contract_grid`
- Validate shape and stability

### Step 4 — Performance validation (45–60 min)
- Benchmark:
  - 10–15 years of daily dates
  - 5–10 contracts per product
- Confirm selection is not a bottleneck

### Step 5 — Tests (90–120 min)
Tests must cover:
- eligibility boundaries
- rank transitions around expiry
- December selection across years
- error cases
- strict vs normalised input

### Step 6 — Documentation (45–60 min)
Add:
- `docs/normative/relative_contracts.md`

Covering:
- definition of M<n>
- definition of fixed-month selectors
- eligibility rules
- error semantics

## File layout (proposed)

### Code
- `mxm_v1/synth/relative_contracts.py`
  - `RelativeContractEngine`
  - selector models
- `mxm_v1/synth/selectors.py`
  - selector definitions and parsing helpers
- `mxm_v1/synth/tests/test_relative_contracts.py`

### Docs
- `mxm_v1/docs/normative/relative_contracts.md`

## Acceptance criteria

Session 17 is complete when:

1. For any v1 product and any trading day:
   - `M1`, `M2`, `Dec1` resolve deterministically
2. All selection logic is:
   - calendar-aware
   - test-covered
   - free of implicit assumptions
3. Relative contract logic is isolated:
   - no roll logic
   - no pricing logic
4. Failures are explicit and typed
5. Performance is acceptable for downstream materialisation

## Session outcome statement (target)

> *“Relative contracts are now a formally defined, deterministic abstraction in MXM V1.  
> The system can answer which contract is meant by M1, M2, or Dec1 on any trading day, and all downstream synthetic-asset work can rely on this without ambiguity.”*
