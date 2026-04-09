# session_34_plan.md

## Session 34 — Wire `daily_mark` into Synthetic Asset Execution & PnL for Full-History Backtests

## Summary

Session 33 established and operationally validated a new curated valuation dataset:

> **`daily_mark` = authoritative MXM contract-level valuation surface on the MXM business-session domain**

This resolved the dataset and orchestration side of the degraded-mark problem:

- `daily_stats` remains the vendor-faithful observed daily surface
- `daily_mark` now provides robust, policy-governed marks across the MXM business calendar
- whole-product `daily_mark` derivation now works for real data and is properly classified across:
  - built
  - skipped_unchanged
  - skipped_out_of_calendar_range
  - unmapped
  - error

However, the synthetic-asset backtest and PnL pipeline still consume `daily_stats` through the existing price-accessor layer.

As a result, the full-history synthetic-asset backtest is still blocked not by absence of `daily_mark`, but by the fact that:

> **execution and valuation have not yet been rewired to consume the new authoritative mark surface**

Session 34 therefore focuses on the integration step:

> **replace `daily_stats`-based price access in the synthetic-asset smoke backtest / PnL path with `daily_mark`-based access, and use this to attempt a clean full-history synthetic-asset cumulative PnL run**

This is explicitly a functional integration session, not yet a performance-optimization session.

## Objective

Achieve a working end-to-end run of:

- realised `SyntheticAsset`
- target holdings
- historical backtest
- contract/session-level PnL
- cumulative synthetic-asset PnL plot

over the full available history, using:

> **`daily_mark` as the contract-level price surface for both execution reference pricing and mark-to-market valuation**

in the current MVP semantics.

Success means:

- `smoke_synthetic_asset_pnl.py` runs over a full-history range for one target synthetic asset
- the run no longer fails due to missing daily marks from degraded vendor `daily_stats`
- the script produces a cumulative PnL plot and metadata file
- any remaining failures are of a new class (i.e. no longer the Session 33 degraded-mark problem)

## Why this is the correct next step

The current system now has a clean conceptual separation:

- `daily_stats` = observed daily vendor surface
- `daily_mark` = authoritative valuation surface for MXM

The PnL / backtest layer should consume the latter.

Although in principle execution-price access and mark-price access are separate concerns, in the current MVP system we do **not** yet model:

- failed fills
- partial fills
- zero available volume
- delayed execution due to unavailable price

Therefore, in current v1 semantics, the most coherent operational choice is:

> **use `daily_mark` for both execution reference price access and mark-to-market price access**

This is explicitly an MVP integration decision, not a final execution model.

Later sessions may split these concerns again once execution realism is expanded.

## Scope

### In scope

- inspect current price-accessor layer
- identify where `daily_stats` is currently used for:
  - execution reference pricing
  - mark-to-market pricing
- add `daily_mark`-based accessor(s)
- wire those accessors into `smoke_synthetic_asset_pnl.py`
- update smoke script calendar-service usage to match the new business-calendar identity model if required
- run short-range smoke check
- run full-history synthetic-asset smoke backtest
- inspect first remaining failure, if any

### Out of scope

- performance profiling / runtime optimization
- introducing no-fill / zero-volume execution semantics
- redesigning global orchestration architecture
- integrating `daily_mark` derivation into a permanent production scheduler
- advanced diagnostics or dashboards beyond what is needed to get the smoke backtest working

## Expected Architectural Change

### Before

`smoke_synthetic_asset_pnl.py` currently uses:

- `DailyStatsExecutionPriceAccessor`
- `DailyStatsMarkPriceAccessor`

so both execution and valuation depend on `daily_stats`.

### After

For current MVP semantics, the smoke script should use:

- `DailyMarkExecutionPriceAccessor` (new or equivalent replacement)
- `DailyMarkMarkPriceAccessor` (new or equivalent replacement)

both backed by:

- `daily_mark/api.py`
- `calendar_id = mxm_business_calendar.calendar_id`

This means the price-accessor layer must move from a vendor-observation keyed interface toward an MXM-business-session keyed valuation interface.

## Key Design Questions to Resolve During Session 34

### 1. What is the narrowest substitution point?

We want the smallest safe change.

Likely answer:

- keep `SessionEngine`, `Backtester`, and `build_pnl_series(...)` unchanged
- replace only the price-accessor implementation(s)

### 2. What access shape do execution and valuation currently require?

Need to inspect the current accessor protocol carefully:

- what arguments are passed into the execution price accessor?
- what arguments are passed into the mark price accessor?
- does one work by submission timestamp and the other by session label?
- where do we need session-id / contract-id translation?

### 3. How do we map from current call signatures into `daily_mark` reads?

Likely current-state assumptions:

- `daily_stats` accessors may still use:
  - `contract_id`
  - session date / timestamp
  - product_id via refdata

Need to determine whether a `daily_mark` accessor can:
- use current session labels directly
- or needs explicit session-id lookup through the MXM business calendar

### 4. Where should `calendar_id` live in the accessor?

Likely answer:

- the `daily_mark` accessors should be constructed with:
  - `calendar_id`
  - maybe `root`
  - maybe `ref_data_api` if identity lookup is still needed

This should avoid leaking calendar internals elsewhere.

## Proposed Work Plan

### Step 1 — Inspect current accessor layer

Open and review:

- `mxm.v1.execution.price_accessors`

Clarify:

- the current abstract contracts / expected interface
- how `DailyStatsExecutionPriceAccessor` is queried
- how `DailyStatsMarkPriceAccessor` is queried

Deliverable:
- precise statement of the accessor contract(s) that `daily_mark` must satisfy

### Step 2 — Implement `daily_mark`-based price accessor(s)

Create accessor implementations that consume:

- `daily_mark/api.py`

and return:

- `mark_px`

for the correct `(calendar_id, contract_id, session_id)` context.

Important:
- keep the implementation simple and deterministic
- do not over-generalize yet
- match existing accessor call contracts as closely as possible

### Step 3 — Update `smoke_synthetic_asset_pnl.py`

Replace:

- `DailyStatsExecutionPriceAccessor`
- `DailyStatsMarkPriceAccessor`

with the new `daily_mark`-based accessors.

Also update the script’s MXM business calendar service usage if still stale with respect to:

- `calendar_base_id`
- derived effective `calendar_id`

Ensure the script passes the effective calendar identity through consistently.

### Step 4 — Run short-range smoke check

Before a full-history run, execute the script over a short recent interval.

Goal:
- verify accessor wiring
- catch API / session-domain mismatches early
- avoid long debug cycles

### Step 5 — Run full-history synthetic-asset smoke backtest

Run the script over the full target historical span for the chosen synthetic asset.

Goal:
- produce full cumulative PnL
- confirm Session 33 degraded-mark failures are eliminated

### Step 6 — Diagnose first remaining failure if needed

If the full-history run still fails:

- identify the new bottleneck precisely
- ensure it is not a residual `daily_stats` dependency
- record the next architectural issue cleanly

## Likely Files to Touch

### Primary

- `src/mxm/v1/execution/price_accessors.py`
- `src/mxm/v1/marketdata/datasets/daily_mark/api.py` (only if a small API extension is needed)
- `scripts/pnl/smoke_synthetic_asset_pnl.py`

### Possibly

- any thin utility layer needed for session-id / calendar-id translation
- tests for the new `daily_mark` accessor(s)

## Expected Tests / Validation

### Unit-level

Add tests for the new `daily_mark` accessor(s):

- correct lookup by `contract_id`
- correct use of `calendar_id`
- correct handling of missing surfaces / missing rows
- consistent price return semantics

### Smoke-level

Run:

- short recent range
- then full-history range

and inspect:

- successful backtest completion
- session-level PnL frame
- contract-level PnL frame
- cumulative PnL plot generation
- metadata output

## Success Criteria

Session 34 is successful if:

1. `smoke_synthetic_asset_pnl.py` is rewired to use `daily_mark`
2. short-range smoke run succeeds
3. full-history smoke run for one target synthetic asset succeeds
4. cumulative PnL plot is produced
5. remaining problems, if any, are no longer caused by missing degraded vendor daily marks

A particularly strong success outcome would be:

> the full-history synthetic-asset cumulative PnL plot finally runs end to end, using the new `daily_mark` valuation layer, without special-case intervention.

## Risks / Expected Failure Modes

### 1. Accessor call contract mismatch

The execution / PnL layers may expect a different lookup domain than `daily_mark` currently exposes.

Mitigation:
- inspect the accessor interface carefully before implementing replacements

### 2. Residual hidden `daily_stats` dependencies

Even after replacing the main accessors, another downstream module may still implicitly depend on `daily_stats`.

Mitigation:
- trace failures carefully and replace only what is actually needed

### 3. Session label vs session_id mismatch

`daily_mark` is keyed by business-session identity.
Downstream code may still be operating partly in day-label or timestamp space.

Mitigation:
- make the accessor boundary responsible for translation where needed

### 4. New backtest failure class

The full-history run may reveal a different historical issue unrelated to marks.

Mitigation:
- treat that as a successful outcome of Session 34 if the degraded-mark problem is clearly removed

## Deliverables

By the end of Session 34 we want:

- `daily_mark`-based accessor(s) implemented
- `smoke_synthetic_asset_pnl.py` updated
- one successful full-history synthetic-asset smoke backtest run
- cumulative PnL plot saved to disk
- clear record of any remaining downstream issue if the run still does not complete

## Closing Note

Session 33 solved the data and orchestration side of the degraded-mark problem.

Session 34 is the integration step that should finally cash that work into the thing we actually wanted all along:

> **a stable full-history synthetic-asset PnL run on explicit MXM business-session semantics**

If this succeeds, the next session can return to the postponed topic:

> profiling, runtime analysis, and optimization of the full synthetic-asset backtest / PnL pipeline.
