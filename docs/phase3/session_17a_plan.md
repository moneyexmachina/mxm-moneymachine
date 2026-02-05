# session_17a_plan.md — MXM V1
## Session 17a — Time Primitives & Trading-Calendar Bridge for Contract Selection

## Purpose

Session 17a hardens the **time and calendar substrate** required for Session 17
(contract selection).

We make two improvements:

1. Promote the existing timestamp and date normalization logic (`time_utils.py`,
   `date_utils.py`) from being a marketdata-local concern to a **shared MXM V1
   utility surface**.

2. Extend the trading-calendar layer with the minimum missing bridge needed for
   contract selection:

   - `calendar_for_product(product_id)` lookup
   - `as_of_session(as_of_ts)` mapping from UTC timestamp to *current or most
     recent trading session label*

No contract selection logic is implemented in this session. This is a strict
dependency for Session 17.

## Context

### Existing (already implemented)
- `TradingCalendar` stores session labels as `datetime64[D]` in `trading_days`
  (observed + projected surface).
- `time_utils.py` / `date_utils.py` exist inside `marketdata/` and enforce
  timezone-aware timestamps (UTC normalization) for marketdata semantics.

### Missing (blocks Session 17)
- A universal, MXM-wide time coercion/normalization layer accessible by all
  modules (not only marketdata).
- A deterministic mapping from a UTC timestamp to a trading-session label under
  a product calendar.
- A product-level lookup to obtain the correct `TradingCalendar`.

## Scope

### In scope
1. Refactor utilities:
   - Move `marketdata/time_utils.py` and `marketdata/date_utils.py` into
     `mxm/v1/utils/` (or equivalent shared location).
   - Update import paths across marketdata and any other modules that use them.
   - Ensure that timestamp normalization and coercion are uniformly applied
     across MXM V1.

2. Calendar bridge:
   - Implement `calendar_for_product(product_id)` in the trading-calendar layer
     (either as a method on a calendar service/registry or equivalent existing
     mechanism).
   - Implement `as_of_session(as_of_ts)` using the product calendar, mapping a
     UTC timestamp to a trading-session label.

### Out of scope
- Contract selection rules, selector models, or ranking logic (Session 17 proper).
- Any modelling of intraday session start/end times or exchange-specific cutoffs.
- Roll logic, pricing, holdings, synthetic assets.

## Normative semantics (to lock in this session)

### 1. Timestamp semantics (MXM V1)
- All timestamps handled in MXM V1 are **timezone-aware**.
- All timestamps are normalized to **UTC** for storage and interoperability.
- A single shared utility surface provides coercion and validation helpers.

### 2. Trading-day semantics
- `TradingCalendar.trading_days` are **session labels**, dtype `datetime64[D]`.
- They are not interpreted as UTC “day intervals”.

### 3. `as_of_session(as_of_ts)` semantics (MXM V1)
- Input: `as_of_ts` is timezone-aware and normalized to UTC by shared time utils.
- Output: the **current or most recent trading-session label** for the product
  calendar.

MXM V1 minimal semantics (sufficient for Session 17):
- Determine `as_of_date = date(as_of_ts in UTC)`
- Return the most recent trading-day label `d` such that `d <= as_of_date`
  (i.e. previous-or-same trading day label under the product’s TradingCalendar)

If `as_of_date` is before the first available trading day in `trading_days`,
raise a typed exception (e.g. `CalendarOutOfRange`).

This minimal semantics avoids intraday cutoffs while remaining deterministic and
consistent with “session labels” framing.

## Deliverables

### A. Shared utilities
- New shared paths (target):
  - `mxm/v1/utils/time_utils.py`
  - `mxm/v1/utils/date_utils.py`

Requirements:
- Preserve existing public function semantics used by marketdata.
- Add any missing docstrings that clarify:
  - “timezone-aware only”
  - “UTC normalized”
  - conversion between `datetime`, `date`, and `numpy datetime64` where needed

### B. Calendar bridge
Implement both:

1) `calendar_for_product(product_id)`
- Must return the correct `TradingCalendar` instance for the product.
- Should reuse existing refdata knowledge (product → calendar_id) if present.
- Should not introduce new persistence or caching.

2) `TradingCalendar.as_of_session(as_of_ts)`
- Must implement the normative semantics above.
- Must be fast (`searchsorted`-based) and deterministic.


## Work plan

### Step 0 — Inventory & alignment (30–45 min)
- Identify current file locations:
  - `marketdata/time_utils.py`
  - `marketdata/date_utils.py`
- Identify current imports of those modules across `mxm/v1`.
- Identify existing calendar lookup mechanism:
  - is there already a registry/service class?
  - is product → calendar_id stored in refdata?

### Step 1 — Refactor time utilities (60–90 min)
- Move `time_utils.py` and `date_utils.py` into `mxm/v1/utils/`.
- Update imports in:
  - marketdata module
  - calendars module (if needed)
  - any other downstream module referencing them
- Run unit tests and any quick smoke tests to confirm no behavioural changes.

### Step 2 — Implement `calendar_for_product` (45–75 min)
- Add a method on the appropriate service/registry (preferred) rather than on
  `TradingCalendar` itself.
- Ensure:
  - deterministic lookup
  - clear error on unknown product_id or missing calendar mapping

### Step 3 — Implement `as_of_session` (60–90 min)
- Implement on `TradingCalendar` (or a thin helper alongside it), using:
  - UTC timestamp normalization from shared time utils
  - `searchsorted` / existing index utilities for `datetime64[D]`
- Implement typed error for out-of-range.

### Step 4 — Tests (60–90 min)
Add unit tests covering:
- `time_utils` import path migration (at least one smoke test ensuring the
  functions are still callable and behave identically).
- `as_of_session`:
  - exact trading day → returns itself
  - weekend / holiday → returns previous trading day
  - date before first calendar day → raises `CalendarOutOfRange`
- `calendar_for_product`:
  - correct calendar returned for a known product_id
  - unknown product_id → typed error

### Step 5 — Documentation (30–45 min)
Add/update a short doc section (location flexible):
- “Time primitives in MXM V1”
- “TradingCalendar session labels”
- “as_of_session semantics”

This documentation exists to prevent future accidental reintroduction of
non-UTC or “UTC-day interval” assumptions.

## Proposed file changes (indicative)

### Refactor
- Move:
  - `mxm/v1/marketdata/time_utils.py` → `mxm/v1/utils/time_utils.py`
  - `mxm/v1/marketdata/date_utils.py` → `mxm/v1/utils/date_utils.py`
- Update imports accordingly.

### Calendar bridge
- `mxm/v1/calendars/trading_calendar.py` (or equivalent)
  - add `as_of_session`
  - add any helper: `prev_or_same_trading_day_label`
- `mxm/v1/calendars/service.py` (or equivalent)
  - add `calendar_for_product`

## Acceptance criteria

Session 17a is complete when:

1. `time_utils` and `date_utils` are accessible from `mxm/v1/utils/` and used
   consistently across MXM V1.

2. The trading-calendar layer can:
   - return the correct calendar for a product (`calendar_for_product`)
   - resolve any UTC timestamp to a session label (`as_of_session`)

3. The behaviour is:
   - deterministic
   - test-covered
   - documented

4. Contract selection (Session 17) can depend on:
   - `as_of_session` for timestamp → session-label resolution
   - shared time utils for UTC enforcement

## Session outcome statement (target)

> *“MXM V1 now has a universal time-coercion utility surface and a deterministic
> trading-calendar bridge from UTC timestamps to session labels. Contract
> selection can proceed without ambiguity about time interpretation.”*
