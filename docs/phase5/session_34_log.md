# session_34_log.md

## Session 34 — Daily Mark Integration & Full Synthetic Asset PnL Pipeline

## Status

**Completed**

Session 34 successfully establishes a fully functioning end-to-end pipeline for:

> SyntheticAsset → Execution → Backtest → PnL  
> using **MXM business calendar** and **daily_mark** as the authoritative valuation surface.

## Objective

Replace dependency on `daily_stats` for execution and valuation with a robust, internally consistent framework:

- Introduce **daily_mark** as canonical mark surface
- Introduce **MXM business calendar** as decision-time domain
- Wire both into:
  - execution price access
  - mark-to-market valuation
  - backtesting pipeline

Target outcome:

> Full-history (~15y) backtest producing stable and interpretable PnL.

## Key Architectural Changes

### 1. Daily Mark as Authoritative Mark Surface

Replaced:

- `daily_stats` (vendor-derived, incomplete, inconsistent)

With:

- `daily_mark` (MXM-curated, gap-filled, deterministic)

Properties:

- Defined on MXM business sessions
- Guarantees:
  - continuity (via carry-forward)
  - explicit mark quality semantics
- Decoupled from vendor trading calendar inconsistencies

### 2. MXM Business Calendar Integration

Introduced:

- `MXMBusinessCalendar`
- Explicit construction via:

  - `calendar_base_id`
  - `calendar_start`
  - `calendar_end`

Key shift:

> Session identity is now **internal and deterministic**, not vendor-derived.

This resolves:

- missing trading days
- inconsistent holiday treatment
- degraded vendor coverage

### 3. Price Accessor Refactor

Replaced:

- `DailyStatsExecutionPriceAccessor`
- `DailyStatsMarkPriceAccessor`

With:

- `DailyMarkExecutionPriceAccessor`
- `DailyMarkMarkPriceAccessor`

Key properties:

- Session-native interface
- Product-level lazy loading
- In-memory lookup per product
- Fail-fast semantics on missing data

Important conceptual separation preserved:

- **execution price accessor**
- **mark price accessor**

Even though both currently use `daily_mark`.

### 4. CLI Simplification

Removed:

- `--price-field` argument

Rationale:

- Execution semantics are **not a CLI concern**
- They belong to:
  - strategy specification
  - execution model configuration

Current state:

> Smoke script uses a single canonical execution/mark surface (`daily_mark`)

### 5. Debug Surface Cleanup

Removed:

- `daily_stats` debug utilities
- unused inspection functions

Result:

- Script now reflects **current system reality**
- No leakage of deprecated data pathways

### 6. Typing / Pyright Handling

Issue:

- `matplotlib` lacks sufficiently strict type stubs
- caused `reportUnknownMemberType` errors

Resolution:

- localized suppression at plotting call sites
- no introduction of `Any`

Decision:

> Maintain strict typing discipline; tolerate controlled boundary exceptions.

## Execution Results

### 1. Short-Range Validation

- Date range: ~2 weeks
- Single-contract exposure

Results:

- Correct holdings
- Correct session alignment
- Zero trade PnL under perfect execution
- Plausible price_move PnL

### 2. Full-History Backtest (~15 years)

Run:

- `2010-06-08` → `2025-12-31`

Results:

- ~4000 sessions processed
- Stable execution
- No missing-mark failures
- Continuous PnL series produced

Key output:

- cumulative PnL ~ **267k USD** for outright synthetic

### 3. Term-Structure Spread Validation

Synthetic:

- near vs far contract spread

Results:

- Offset PnL behaviour validated
- Near/far symmetry visible
- Small residual PnL (~-2940 USD over 15y)

Interpretation:

- expected due to:
  - roll timing
  - discrete contract switching
  - mark surface characteristics

## Observations & Insights

### 1. Mark Precision vs Tick Size

Observed:

- PnL increments in multiples of **5 USD**

Derived:

- mark surface is at **0.1 index point resolution**
- contract multiplier = 50

Conclusion:

> Mark precision is **finer than tradable tick (0.25)**

Implication:

- current system models **valuation surface**, not execution microstructure
- acceptable for V1

### 2. Calendar / Data Boundary

Critical insight:

> Missing data is not a data problem — it is a **time-domain modelling problem**

Resolution:

- business calendar defines **when the system exists**
- data layer defines **what can be observed**

This separation is now cleanly implemented.

### 3. First Complete System Loop

This is the first time the system:

- runs on its own time domain
- uses its own valuation surface
- produces a full-history PnL

This marks the transition from:

> "pipeline assembly"

to:

> **"coherent system"**

## Known Limitations / TODO (Session 35+)

### 1. Missing Execution / Mark Handling

Current behaviour:

- hard failure if no price available

Future:

- explicit degraded-mode handling:
  - skip execution
  - carry positions
  - mark as unavailable
  - track data quality

### 2. Execution Model Simplification

Current:

- perfect execution at mark price

Future:

- introduce:
  - slippage
  - partial fills
  - execution price models (close, VWAP, etc.)

### 3. Mark vs Execution Surface Separation

Currently:

- both use `daily_mark`

Future:

- distinct surfaces:
  - execution surface
  - valuation surface

### 4. Numerical Precision

Observed:

- floating-point artifacts (`1414.999999...`)

Future:

- consider:
  - integer PnL representation
  - or decimal normalization layer

## Conclusion

Session 34 establishes:

> A fully operational, internally consistent MXM V1 backtesting system.

The system is now:

- temporally coherent
- data-robust
- architecturally modular

This represents a **major foundation milestone**.

## Next Step

Session 35:

- degraded execution / mark handling
- robustness layer for real-world operation

## Reflection

This session required:

- stepping back from implementation
- rethinking fundamental assumptions:
  - time
  - data
  - valuation

The introduction of:

- **MXM business calendar**
- **daily_mark**

was not an incremental fix, but a **conceptual correction**.

This is now encoded in the system.
