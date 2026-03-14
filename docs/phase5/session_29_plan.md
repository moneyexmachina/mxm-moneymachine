# Session 29 – PnL Module and First Synthetic-Asset Backtest

Status: Planned  
Date: 2026-03-XX  
Scope: Economic performance layer on top of SessionResult chains

# 1. Objective

Session 29 will implement the first **PnL layer** for MXM V1.

The goal is to take the output of the execution infrastructure built in Session 28:

    SessionResult chain
        → realised holdings path
        → execution prices
        → session-by-session state transitions

and construct a first canonical **PnL representation** for a synthetic asset backtest.

The session should end with a smoke script that:

- builds a synthetic asset
- backtests it across its session range
- computes session PnL
- plots cumulative PnL
- splits cumulative PnL into:
  - price-move PnL
  - trade PnL

This will complete the first full pipeline from:

    SyntheticAssetSpec
        → SyntheticAsset
        → TargetHoldings
        → Backtester
        → SessionResult chain
        → PnL
        → cumulative equity curve

# 2. Architectural Goal

The PnL layer should sit **above execution**, not inside it.

Execution gives us:

- what we held coming into the session
- what trades we did during the session
- at what fill prices
- what we held after execution

PnL will then compute the economic consequences of that state transition.

This is an important architectural boundary.

Execution is about:

- intent
- orders
- fills
- realised holdings

PnL is about:

- value change
- mark-to-market
- realised economic consequences
- attribution of economic outcomes

# 3. Inputs Available After Session 28

We now have the following relevant objects already implemented:

- `TargetHoldings`
- `Order`
- `OrderExecution`
- `ExecutionResult`
- `SessionResult`
- `BacktestResult`
- `DailyStatsExecutionPriceAccessor`
- historical synthetic-asset target-holdings surfaces

This means Session 29 does **not** need to invent new execution logic.

Instead it can consume:

    BacktestResult.session_results

and map those into a PnL surface.

# 4. Core PnL Decomposition to Implement

The first implementation should decompose session PnL into:

## 4.1 Price-Move PnL

Economic interpretation:

    PnL caused by the mark-to-market change of holdings carried into the session

Conceptually:

    initial_holdings × (session_settle - previous_session_settle)

This is the PnL of being exposed during the session.

## 4.2 Trade PnL

Economic interpretation:

    PnL caused by executing trades at a price different from the session mark

Conceptually:

    realised_trades × (session_settle - fill_price)

For the current `PerfectBacktestExecutor` where:

    fill_price == session_settle

this will initially be zero.

However this decomposition is still essential, because later:

- trade-cost executors
- slippage
- partial fill logic
- adverse fills

will all show up here.

## 4.3 Total PnL

Conceptually:

    total_pnl = price_move_pnl + trade_pnl

This total will then be accumulated into:

    cumulative_pnl

# 5. FX Handling

FX translation must be acknowledged now, but only stubbed for tomorrow.

## 5.1 What we ultimately need

PnL should eventually support:

- contract price move in native contract currency
- translation into synthetic-asset currency
- later translation into reporting currency if desired

This will require:

- FX instruments in `mxm-refdata`
- FX market-data ingestion
- spot FX or equivalent translation surfaces

## 5.2 Session 29 scope

For Session 29, we should implement the **mechanism and architecture** for FX translation, but not the real data plumbing.

Planned behaviour:

- if contract currency == synthetic asset currency:
  - FX multiplier = 1.0

- otherwise:
  - fail loudly or use an explicit placeholder / stub path

The synthetic asset used in the smoke script should therefore be chosen such that:

    PnL is computed in the synthetic asset’s own currency
    without requiring real FX translation

This keeps the design honest without blocking tomorrow’s milestone.

# 6. Proposed Module Structure

New package:

    src/mxm/v1/pnl/

Candidate modules:

    pnl/
        __init__.py
        pnl.py
        price_surfaces.py
        attribution.py
        plotting.py

However, for Session 29 we should remain minimal.

Recommended first implementation:

    pnl/
        __init__.py
        constructor.py
        models.py

Where:

## `models.py`
Defines the canonical PnL result objects.

## `constructor.py`
Builds PnL from `BacktestResult` plus price-access surfaces.

This is likely enough for tomorrow.

# 7. Proposed Core Objects

## 7.1 SessionPnL

One session’s economic result.

Candidate fields:

- `previous_session`
- `session`
- `price_move_pnl`
- `trade_pnl`
- `total_pnl`

Potentially later:

- `price_move_fx_pnl`
- `trade_fx_pnl`
- `fees`
- `slippage_pnl`
- `contract_level_breakdown`

## 7.2 PnLSeries

Ordered collection of `SessionPnL`.

Candidate responsibilities:

- validation of session ordering
- conversion to DataFrame
- cumulative sums
- convenience access for plotting

# 8. Required Data Inputs for PnL Construction

The PnL constructor will need:

## 8.1 Session results

From:

    BacktestResult.session_results

Specifically:

- `previous_session`
- `session`
- `initial_holdings`
- `execution_result.realised_trades`
- `execution_result.fill_prices`

## 8.2 Session marks

We need mark prices per contract and session.

For now:

- use settlement prices from daily_stats
- through an accessor / lookup layer similar to execution pricing

The simplest first approach is to reuse the existing price-access machinery conceptually, but for PnL construction we may want a more direct batch lookup surface rather than repeated scalar calls.

# 9. First-Pass PnL Semantics

For each `SessionResult` at session `t`:

## 9.1 Price-move PnL

Use the holdings that were active entering the session:

    initial_holdings(t)

and compare marks between:

    previous_session
    session

This means the first session in a run has no prior mark, so:

- either define price-move PnL = 0 on first session
- or explicitly treat first session as lacking a previous mark

Recommended first behaviour:

    price_move_pnl(first session) = 0.0

This is simple and deterministic.

## 9.2 Trade PnL

Use:

- realised trades during session `t`
- fill prices from execution result
- session mark at `t`

Conceptually:

    realised_trades(t) × (mark_t - fill_price_t)

In the current perfect-fill backtest, this will evaluate to zero.

That is acceptable and desirable.

# 10. Contract Multipliers and Unit Scaling

A crucial point for PnL is that contract quantities are not enough.

We must multiply by the contract’s economic size.

Therefore the constructor must include the appropriate multiplier concept, likely derived from refdata:

    contract_pnl =
        position_or_trade_quantity
        × contract_multiplier
        × price_difference
        × fx_multiplier

For Session 29:

- wire in the contract size / multiplier path properly
- wire in FX multiplier as placeholder/stub if same-currency only

This ensures the PnL module is economically meaningful, not merely arithmetic on raw price differences.

# 11. Testing Strategy for Session 29

We should build this in the same style as Session 28:

- define the semantic promises first
- write deterministic unit tests
- then write the smoke script

Recommended test layers:

## 11.1 PnL object tests
- ordering validation
- cumulative sum behaviour

## 11.2 constructor tests
- first-session price-move PnL = 0
- correct price-move PnL for carried holdings
- correct trade PnL from fill-price deviations
- total PnL decomposition matches sum of components
- placeholder FX path behaves correctly

## 11.3 smoke test
- backtest synthetic asset
- produce non-empty PnL series
- generate cumulative plot

# 12. Smoke Script Goal

Create a script along the lines of:

    scripts/execution/smoke_synthetic_asset_pnl.py

Pipeline:

    build synthetic asset
        → backtest target holdings
        → construct pnl series
        → print session-level pnl summary
        → plot cumulative pnl

Plot should include:

- cumulative total PnL
- cumulative price-move PnL
- cumulative trade PnL

This will provide the first visible economic output of the system.

# 13. Expected Outcome

At the end of Session 29, MXM V1 should support:

    SyntheticAsset
        → TargetHoldings
        → Backtester
        → BacktestResult
        → PnLSeries
        → cumulative PnL plot

This will complete the first end-to-end historical simulation loop from asset definition to economic output.

# 14. Deferred Work

The following should remain explicitly deferred beyond Session 29:

- real FX instrument support and FX market-data ingestion
- reporting-currency translation
- fees / commissions
- slippage-aware trade PnL
- per-contract and per-intent attribution surfaces
- performance scaling / vectorisation session
- large-scale backtest optimisation

# 15. Summary

Session 29 will implement the first **PnL layer** of MXM V1.

It will consume `SessionResult` chains and construct a canonical economic performance surface with decomposition into:

- price-move PnL
- trade PnL
- total PnL
- cumulative PnL

A smoke script will then backtest a synthetic asset and plot its cumulative PnL, providing the first full economic demonstration of the MXM trading stack.
