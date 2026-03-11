# Session 28 – Positions, Trades, and Initial Execution Simulator

Status: 📋 Planned  
Date: 2026-03-XX  
Scope: Execution layer introduction (Positions → TargetTrades → ExecutedTrades → Positions)

# 1. Objective

Session 28 introduces the **execution state transition layer** of MXM.

Up to Session 27 the system constructs **intended asset exposures**:

```
SyntheticAssetSpec
    ↓
ComponentContracts
    ↓
ComponentWeights
    ↓
TargetHoldings
```

However, real trading systems operate through **state transitions** driven by execution.

Session 28 introduces the missing abstractions:

```
Positions
TargetTrades
ExecutedTrades
TradeExecutor
Backtest simulator
```

These objects allow the system to simulate how intended holdings become realised positions over time.

# 2. Core Concept

Execution introduces **stateful evolution**.

The canonical state transition becomes:

```
Positions(t)
TargetHoldings(t)
    ↓
TargetTrades(t)
    ↓
TradeExecutor
    ↓
ExecutedTrades(t)
    ↓
Positions(t+1)
```

Important properties:

* target trades depend on **current realised positions**
* execution may deviate from intent
* realised positions determine **risk and PnL**

This layer is therefore the foundation for:

```
backtesting
execution modelling
cost modelling
risk calculation
PnL attribution
```

# 3. Objects to Introduce

Session 28 introduces the following new abstractions.

# 3.1 Positions

Represents **realised holdings state**.

Conceptually:

```
(contract_id) → position
```

Positions represent the state **entering a session**.

Example:

```
contract_id                 position
cbot_corn_futures.Mar2020   1
cbot_corn_futures.May2020   0
```

Key properties:

* contract-level representation
* no dependency on synthetic asset components
* canonical contract exposure surface

Structure candidate:

```
Positions
    asset_id
    canonical_id
    frame
```

Frame structure:

```
contract_id -> position
```

Positions will later become the input to:

```
risk engine
PnL engine
portfolio aggregation
```

# 3.2 TargetTrades

Represents **intended trades** required to move from current positions to target holdings.

Definition:

```
TargetTrades = TargetHoldings − CurrentPositions
```

Conceptually:

```
(contract_id) → trade_quantity
```

Positive values represent buys.

Negative values represent sells.

Example:

```
contract_id                 target_trade
cbot_corn_futures.Mar2020   -1
cbot_corn_futures.May2020   +1
```

This abstraction represents **intent**, not execution.

# 3.3 ExecutedTrades

Represents **actual trades executed by the system**.

Initial version will assume:

```
ExecutedTrades == TargetTrades
```

Future versions may introduce:

```
partial fills
slippage
liquidity limits
rejected orders
queueing effects
market impact
```

Structure candidate:

```
ExecutedTrades
    session
    frame
```

Frame:

```
(contract_id) → executed_trade
```

# 3.4 TradeExecutor

A component responsible for converting **TargetTrades into ExecutedTrades**.

Initial implementation:

```
PerfectExecutor
```

Assumptions:

```
100% fill
no delay
no slippage
no costs
```

API concept:

```
execute(
    target_trades,
    market_data,
) → executed_trades
```

Even if trivial initially, the abstraction is important because it isolates:

```
execution logic
market microstructure modelling
liquidity constraints
```

# 3.5 Backtest Simulator

A simple simulator that evolves positions through time.

Initial state:

```
Positions = empty
```

For each session:

```
1. compute TargetTrades
2. execute trades
3. update Positions
```

State update:

```
Positions(t+1) = Positions(t) + ExecutedTrades(t)
```

This produces a time evolution of:

```
positions
trades
```

which later enables:

```
PnL attribution
risk calculations
strategy evaluation
```

# 4. Initial Scope

Session 28 will implement a **minimal but semantically complete execution model**.

Assumptions:

```
single synthetic asset
single stream of TargetHoldings
perfect execution
no transaction costs
```

This keeps complexity minimal while establishing correct architecture.

# 5. Proposed Module Structure

New modules inside:

```
mxm/v1/execution/
```

Candidate layout:

```
execution/

positions.py
target_trades.py
executed_trades.py
executor.py
simulator.py
```

Alternatively the simulator may remain within synthetic_assets initially.

Final placement can be decided during implementation.

# 6. Smoke Script

A new smoke script will demonstrate the execution pipeline.

Example:

```
scripts/execution/smoke_synthetic_asset_backtest.py
```

Pipeline:

```
load SyntheticAssetSpec
build SyntheticAsset
run simulator from empty positions
print:

positions evolution
executed trades
target trades
```

This provides human inspection of the system behaviour.

# 7. Key Design Principles

Session 28 continues the MXM design principles:

### deterministic state surfaces

Every object must produce deterministic representations.

### strict schema validation

Each object validates:

```
index structure
column structure
numeric invariants
```

### explicit separation of intent and execution

```
TargetTrades ≠ ExecutedTrades
```

even if identical in the first implementation.

### modular architecture

Execution is isolated from:

```
synthetic asset construction
risk modelling
PnL calculation
```

# 8. Expected Outcome

At the end of Session 28 the system will support:

```
SyntheticAsset
    ↓
TargetHoldings
    ↓
TargetTrades
    ↓
ExecutedTrades
    ↓
Positions evolution
```

This enables the first **true backtest simulation** capability within MXM.

# 9. Future Extensions

This layer enables future additions:

```
transaction costs
market impact
liquidity constraints
portfolio aggregation
multi-asset strategies
risk engine
PnL attribution
```

# 10. Summary

Session 28 introduces the **execution and state evolution layer**.

New abstractions:

```
Positions
TargetTrades
ExecutedTrades
TradeExecutor
Backtest simulator
```

This moves MXM from **static asset construction** to **dynamic trading system simulation**.

The result is a foundation for the full backtesting and risk architecture of MXM V1.

