# Session 32 — MXM Business Calendar: Design, Construction, and Integration

## Objective

Define, construct, and integrate the **MxMBusinessCalendar** as the authoritative
decision-time calendar for MXM, and align the Synthetic Asset layer with this
calendar while preserving correct market-structure semantics.

This session establishes:
- a clear ontology for calendars in MXM
- a first implementation of MXM business days
- a controlled integration path into synthetic asset construction
- a basis for resolving missing mark/settlement issues

## 1. Problem Statement

During extended backtests, we observed failures such as:

    Missing mark price for session (e.g. 2010-07-05, 2010-09-06, 2010-11-25)

These correspond to US holidays where:
- trading calendars report sessions
- but no settlement prices (`settle_px`) are available

This reveals a mismatch:

    TradingCalendar ≠ “days on which MXM can operate”

## 2. Calendar Ontology (V1)

We now distinguish three conceptual layers:

### 2.1 TradingCalendar (existing)

Represents:
- exchange-defined trading sessions
- contract lifecycle geometry
- authoritative source for:
  - session labels
  - LTD positioning
  - contract selection

Properties:
- product-specific
- derived from exchange data
- includes sessions where:
  - trading may be thin
  - settlement may not exist

### 2.2 SettlementCalendar (not implemented)

Conceptually:
- days where settlement prices exist

In V1:
- not explicitly modelled
- implicitly inferred from data availability

### 2.3 MXMBusinessCalendar (new)

Represents:

    "Days on which MXM chooses to operate"

Meaning:
- make decisions
- construct target holdings
- mark positions
- run PnL

Properties:
- global (not product-specific)
- conservative (excludes problematic days)
- aligned with:
  - liquidity
  - settlement availability
  - operational feasibility

## 3. Design Decision

We adopt:

> Synthetic assets are **strategies**, not market representations.

Therefore:

- SyntheticAsset surfaces should be expressed on **MxMBusinessCalendar**
- TradingCalendar remains a **lower-layer reference system**

## 4. Construction of MXMBusinessCalendar (V1)

### 4.1 Base input

Use:
- `TradingCalendar` for a representative product (initially ES futures)

### 4.2 Filtering rule

Exclude:

- US federal holidays (full closure set)
  - New Year’s Day
  - MLK Day
  - Presidents’ Day
  - Good Friday
  - Memorial Day
  - Juneteenth (>= 2021)
  - Independence Day (observed)
  - Labor Day
  - Thanksgiving
  - Christmas

Source:
- `holiday_rules.py`

### 4.3 Result

Construct:

```python
business_days = trading_calendar.trading_days - holidays
```

With:
- same dtype: `datetime64[D]`
- strictly increasing
- observed_end inherited from trading calendar

### 4.4 Implementation components

- `mxm_business_calendar.py`
  - immutable calendar model

- `mxm_business_calendar_service.py`
  - builds and caches the singleton MXM calendar
  - initial implementation:
    - derived from ES trading calendar
    - filtered by US holiday rules

## 5. Integration Strategy

### 5.1 Key Principle

Do NOT replace TradingCalendar globally.

Instead:

> Separate **market-time logic** from **machine-time logic**

## 6. Synthetic Asset Layer — Calendar Split

### 6.1 Two roles of calendars

#### A. Market-structure (TradingCalendar)

Used for:
- contract selection
- anchor series construction
- LTD-based roll timing inputs

#### B. Machine-operation (MxMBusinessCalendar)

Used for:
- session grid of outputs
- decision days
- target holdings
- PnL evaluation

### 6.2 Required architectural shift

Current state:
- single `TradingCalendarService` used everywhere

Target state:
- dual-calendar usage

```text
TradingCalendarService → market structure
MxMBusinessCalendar    → strategy execution timeline
```

## 7. Component Weights — Key Decision

### Question

Should `bdays_to_ltd` use:
- trading days?
- MXM business days?

### Decision (leaning)

Use:

> **MXM business days to LTD**

Rationale:
- roll timing should reflect actual executable opportunities
- holidays are not valid roll days
- produces conservative and operationally consistent behaviour

Implication:
- semantics shift from:
    "exchange trading days to expiry"
  to:
    "MXM decision days to expiry"

## 8. Integration Plan

### Step 1 — Build MXMBusinessCalendar

- implement service
- verify calendar output
- inspect coverage visually (CLI)

### Step 2 — Move session grid to MXM business days

Target:
- SyntheticAsset outputs indexed by MXM business days

Likely entry point:
- `build_component_contracts(...)`

### Step 3 — Preserve TradingCalendar usage where required

Keep TradingCalendarService in:

- `_build_anchor_contract_series_for_component`
- `build_contract_series`
- contract lifecycle logic

### Step 4 — Adjust `bdays_to_ltd`

Options:

#### A. Minimal (first pass)
- keep current implementation
- but only evaluate on MXM business days

#### B. Full (preferred)
- redefine:
    `bdays_to_ltd = count of MXM business days until LTD`

This requires:
- adapting `build_bdays_to_ltd_series`

### Step 5 — Reconcile surfaces

Ensure:

- `ComponentContracts.frame.index` = MXM business days
- `ComponentWeights.frame.index` = MXM business days
- no downstream filtering required in backtest

## 9. Dependency Refactor

### Current

```python
calendar_service: TradingCalendarService
```

### Target

Split dependencies:

```python
trading_calendar_service: TradingCalendarService
mxm_business_calendar: MxMBusinessCalendar
```

Reason:
- these are not interchangeable objects
- they serve fundamentally different roles

## 10. Non-Goals (Session 32)

- multi-exchange calendar composition
- dynamic liquidity-based filtering
- explicit SettlementCalendar implementation
- cross-product calendar harmonisation

## 11. Expected Outcome

After integration:

- No missing mark price errors on holidays
- Clean PnL construction on valid business days only
- Synthetic assets aligned with actual trading capability
- Clear separation between:
  - market structure
  - machine operation

## 12. Follow-Up Work

- refine MXM business-day definition (early closes, half days)
- introduce multi-product intersection calendars
- possibly formalise SettlementCalendar
- improve inspection tooling for:
  - calendar vs data coverage
  - missing session diagnostics

## Summary

We introduce a **single, global MXMBusinessCalendar** representing when the
machine operates.

We retain **TradingCalendar** for contract and market structure.

We integrate the two by:

> building market-aware support using TradingCalendar  
> expressing strategy outputs on MXMBusinessCalendar

This establishes a clean separation between:
- **what the market allows**
- **what MXM chooses to do**
