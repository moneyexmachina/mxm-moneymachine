# Session 30 — Temporal Semantics and First End-to-End Asset PnL

Status: Planned  
Date: 2026-03-XX  
Scope: Temporal semantics, execution boundary clarification, and completion of the first fully functioning SyntheticAsset → PnL pipeline.

# 1. Objective

Session 30 will establish a **clean and explicit temporal model** for MXM V1 and complete the first fully working end-to-end pipeline:

```
SyntheticAssetSpec
    ↓
SyntheticAsset runtime
    ↓
TargetHoldings
    ↓
Backtester
    ↓
SessionResults
    ↓
PnLSeries
```

The session will resolve the architectural ambiguity discovered in Session 29:

> The system currently mixes **session labels** and **timestamps (instants)**.

The goal is to define a clear boundary between the two temporal domains and make that boundary explicit in the code.

Once resolved, the `smoke_synthetic_asset_pnl.py` script should run successfully and produce deterministic economic output.

# 2. Temporal Semantics Model

The MXM system uses **two distinct temporal representations**.

These must never be implicitly interchanged.

## 2.1 Session Labels (Calendar Domain)

Session labels represent **trading sessions as calendar identities**, not moments in time.

Example:

```
2025-01-02
```

Properties:

- label only
- not timezone aware
- not an instant
- identifies a session within a calendar

Representation:

```
np.datetime64[D]
```

Used in:

```
TradingCalendar.trading_days
ContractSeries
ComponentContracts
ComponentWeights
TargetHoldings
Backtester session iteration
SessionResult.session
SessionResult.previous_session
```

These objects operate in the **session domain**.

## 2.2 Timestamps (Timeline Domain)

Timestamps represent **precise instants in UTC time**.

Example:

```
2025-01-02 14:30:00+00:00
```

Representation:

```
pd.Timestamp (tz="UTC")
```

Used for:

```
order submission timestamps
order fill timestamps
FX conversion lookup
schedule open/close boundaries
timestamp → session mapping
```

These objects operate in the **timeline domain**.

# 3. Explicit Domain Boundary

Conversion between session labels and timestamps must be **explicit and centralized**.

Two bridges exist:

## 3.1 Session → Timestamp

Used when submitting orders in a backtest.

Example mapping:

```
submission_timestamp =
    calendar.session_open(session_label)
```

or

```
submission_timestamp =
    calendar.session_close(session_label)
```

This conversion belongs in:

```
SessionEngine
```

## 3.2 Timestamp → Session

Used when mapping real-time timestamps to sessions.

Example:

```
session_label =
    calendar.timestamp_to_session(timestamp)
```

This logic belongs in:

```
TradingCalendar.schedule
```

# 4. Investigation Tasks

Before modifying code, confirm current system behaviour.

## 4.1 Inspect Daily Stats Indexing

Verify how `daily_stats` market data is indexed.

Possibilities:

```
(contract_id, trading_date)
```

or

```
(contract_id, timestamp)
```

Expected:

```
(contract_id, trading_date)
```

If correct, then mark price lookup should be **session-domain**, not timestamp-domain.

## 4.2 Audit Temporal Usage

Audit the following modules:

```
Backtester
SessionEngine
ExecutionPriceAccessor
MarkPriceAccessor
PnL constructor
```

Confirm whether they require:

```
SessionLabel
or
UTC timestamp
```

Correct any misuse.

# 5. Required Code Changes

## 5.1 Backtester

Ensure backtester iterates over **session labels only**.

No conversion to timestamps during iteration.

Example:

```
sessions = target_holdings.frame.index.get_level_values("session")
```

## 5.2 SessionEngine

Introduce the explicit **session → timestamp bridge** here.

Example concept:

```
submission_timestamp =
    calendar.session_open(session_label)
```

Executor should operate on timestamps.

## 5.3 TargetHoldings

Confirm that the session index is consistently represented as:

```
np.datetime64[D]
```

No timestamp coercion should occur inside the holdings surface.

## 5.4 Price Accessors

Confirm correct temporal domain:

```
MarkPriceAccessor → session label
ExecutionPriceAccessor → timestamp
```

Adjust interfaces if necessary.

# 6. Smoke Script Completion

After resolving the temporal boundary, run:

```
poetry run python scripts/pnl/smoke_synthetic_asset_pnl.py \
  --asset-id cme_emini_snp500_futures_cont_hmuz1_wr_lr_3_1 \
  --start 2025-01-02 \
  --end 2025-01-16
```

Expected outputs:

```
dev_plots/pnl/synthetic_asset/
    synthetic_asset_pnl__*.png
    synthetic_asset_pnl__*.json
```

Verification points:

- backtest completes without timestamp mismatch
- cumulative PnL plotted successfully
- trade PnL ≈ 0 under perfect execution

This will confirm the **first full economic pipeline**.

# 7. Deliverables for Session 30

1. Clear temporal semantics specification.
2. Correct session vs timestamp usage across execution boundary.
3. Successful run of `smoke_synthetic_asset_pnl.py`.
4. Deterministic cumulative PnL plot.

# 8. Subsequent Session Roadmap

Once the temporal model is stable and the pipeline runs end-to-end, development can proceed to higher-level improvements.

## Session 31 — Execution Realism

Introduce realistic execution behaviour:

```
fill_price ≠ settlement
slippage model
execution delay
```

Improve economic realism of the backtest.

## Session 32 — FX Conversion

Implement full FX conversion support:

```
SpotFXConverter
FX market data ingestion
PnL FX attribution
```

Extend PnL decomposition to include FX components.

## Session 33 — Market Data Performance

Measure and optimize market-data access:

```
daily_stats access profiling
caching improvements
vectorised lookup
```

Goal: remove potential backtest bottlenecks.

## Session 34 — Synthetic Asset Runtime Persistence

Persist runtime surfaces:

```
component_contracts
component_weights
target_holdings
```

Enable caching and reuse of asset constructions.

## Session 35 — High-Performance Trade Simulation

Introduce faster simulation kernel:

```
vectorised trade simulation
NumPy kernel
optional Numba acceleration
```

Goal: accelerate large-scale strategy evaluation.

# 9. Milestone

Successful completion of Session 30 establishes the **first closed economic loop** in MXM:

```
SyntheticAssetSpec
      ↓
SyntheticAsset runtime
      ↓
TargetHoldings
      ↓
Backtest execution
      ↓
SessionResults
      ↓
PnLSeries
```

From this point onward, the system transitions from **infrastructure construction** to **economic experimentation and performance improvement**.

End of Session 30 plan.
