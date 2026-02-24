# session_20_plan.md — MXM V1  
## Session 20 — InstrumentSeries (Rule Realisation Layer)

## Position in architecture

Sessions completed:

- **Session 18** — Deterministic contract selection engine  
- **Session 19** — Relative contract identifiers (canonical + short)

We now move from:

    (product_id, as_of_ts, rule) -> contract_id

to:

    (product_id, rule, session_index) -> time-indexed contract path

Session 20 introduces the **InstrumentSeries** layer.

This is the realisation of a `SelectorRule` over a product’s trading calendar.

It is the missing intermediary between:

- rule-level intent
- synthetic asset construction
- eventual target holdings and trades

## Purpose

An InstrumentSeries represents:

> “For this product and this rule, which concrete contract is active at each trading session?”

It is a **time-indexed identity surface**.

It does **not**:

- perform any asset-level logic
- define roll events
- compute holdings
- execute trades
- perform risk or sizing logic

It simply resolves identity over time.

## Conceptual Model

Given:

- `product_id`
- `SelectorRule`
- trading sessions index (from product calendar)
- time range `[start_session, end_session]`

We compute:

    session_t -> contract_id_t

using `engine.explain(...)`.

This produces:

- contract identity path
- period identity path
- contract switch boundaries

## Important Terminology Lock

### Contract Switch (InstrumentSeries-level)

A **contract switch** occurs when:

    contract_id[t] != contract_id[t-1]

This is a property of the rule realisation only.

It is NOT a roll event.

### Roll Event (Asset-level, future session)

A roll event occurs when:

- aggregate target lots per concrete contract change
- and the change is induced by underlying contract identity transitions

Roll events are defined only at the synthetic asset layer.

Session 20 defines contract switches only.

## Scope of Implementation

### 1. InstrumentSeriesSpec

Minimal spec:

```python
InstrumentSeriesSpec(
    product_id: str,
    rule: SelectorRule,
    start_session: np.datetime64,
    end_session: np.datetime64,
)
```

The trading calendar index is derived from:

```
TradingCalendarService.calendar_for_product(product_id)
```

Sessions between start and end inclusive.

### 2. InstrumentSeries Artifact

Fields (minimum viable V1):

```python
InstrumentSeries(
    product_id: str,
    canonical_relative_id: str,
    short_rel_id: str,
    sessions: np.ndarray,                # datetime64[D]
    contract_ids: list[str],
    period_ids: list[str],
    switch_points: list[SwitchEvent],
)
```

Where:

```python
SwitchEvent(
    session: np.datetime64,
    from_contract_id: str,
    to_contract_id: str,
)
```

Invariants:

- `len(sessions) == len(contract_ids)`
- `contract_ids[i]` corresponds to `sessions[i]`
- No None values (fail hard on selection failure in V1)
- `switch_points` derived deterministically from contract_ids

### 3. Builder Function

```
build_instrument_series(
    engine: ContractSelectorEngine,
    product_id: str,
    rule: SelectorRule,
    start_session,
    end_session,
) -> InstrumentSeries
```

Implementation outline:

1. Retrieve product calendar.
2. Generate session index in range.
3. For each session:
   - call `engine.explain(product_id, session, rule)`
   - require `outcome == "selected"` (else raise)
   - record contract_id and period_id
4. Compute switch_points.
5. Attach canonical + short labels from rule.
6. Return InstrumentSeries.

### 4. Failure Semantics (V1)

InstrumentSeries is a structural layer.

Selection failure inside the range is treated as:

- Hard failure (raise)
- No partial series allowed

Rationale:

- A gap indicates incomplete refdata or invalid range.
- Silent continuation would corrupt downstream synthetic construction.

## Test Plan (Session 20)

Tests should verify:

- Stable contract path for front-month rule.
- Contract switch occurs at expected session.
- Canonical and short IDs attached.
- No switch when rule constant.
- Hard failure when selection fails mid-range.

## Deliverable Definition

Session 20 complete when:

- InstrumentSeriesSpec and InstrumentSeries classes exist.
- Builder function implemented.
- Switch detection logic implemented.
- Tests green.
- REPL demo shows contract path and switch points.

# Forward Roadmap

## Session 21 — SyntheticAssetSpec (Physical Instrument Definition)

Define:

```python
SyntheticAssetSpec(
    asset_id: str,
    base_currency: str,
    unit: str,
    legs: list[LegSpec],
)
```

LegSpec:

- `product_id`
- `SelectorRule` (or canonical id reference)
- `exposure_basis`: "lots" | "physical"
- `exposure_map`: deterministic mapping from synthetic unit -> leg unit

Synthetic asset defines:

- its own natural physical unit
- deterministic replication map
- no FX hedging (strategy concern)
- no vol targeting
- no notional targeting

This formalises synthetic assets as **instruments**, not strategies.

## Session 22 — SyntheticAssetTargetHoldings

Given:

- InstrumentSeries for each leg
- SyntheticAssetSpec
- target synthetic units over time

Compute:

- leg exposures
- leg lots
- aggregate per-contract lots
- contract-level deltas

This is where asset-level roll events become defined:

    roll_event[t] occurs when aggregate contract lots change
    due solely to underlying contract switch.

## Session 23 — Trade Surface

Transform target lots:

    lots[t] - lots[t-1] -> trade instructions

Still deterministic.

No execution logic yet.

## Architectural Stack After Session 23

1. SelectorRule — intent
2. InstrumentSeries — identity over time
3. SyntheticAssetSpec — physical instrument definition
4. SyntheticAssetTargetHoldings — lots over time
5. Trade surface — contract-level deltas
6. Strategy — sizing, FX, risk targeting

## Strategic Significance

Session 20 transitions MXM from:

- single timestamp contract selection

to:

- continuous contract identity modelling.

This unlocks:

- synthetic continuous contracts
- calendar spreads
- structured instruments
- deterministic roll mechanics

It is the foundational bridge toward target holdings.

## Status

Session 20 is planned.

It builds directly on Sessions 18–19.

No changes to selection engine semantics are required.
InstrumentSeries is a pure consumer of engine output.

Next action: implement InstrumentSeries.
