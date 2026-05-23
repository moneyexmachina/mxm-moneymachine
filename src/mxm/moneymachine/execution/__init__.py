"""
MXM V1 — Execution Layer

This module introduces the execution and state evolution layer of the
Money Ex Machina trading system.

Up to Session 27 the system constructs *intended exposures* through the
synthetic asset pipeline:

    SyntheticAssetSpec
        ↓
    ComponentContracts
        ↓
    ComponentWeights
        ↓
    TargetHoldings

These objects describe the *desired contract exposures* of a strategy,
but they do not yet represent the realised state of a trading system.

The execution layer bridges this gap by modelling how intended holdings
become realised positions through trading.

The core state transition is:

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

This layer therefore introduces the first **stateful evolution** in MXM.
It forms the foundation for:

    - backtesting
    - execution modelling
    - transaction cost modelling
    - risk calculations
    - PnL attribution
    - portfolio aggregation

Key abstractions introduced here include:

    Positions
        Realised contract exposures entering a trading session.

    TargetTrades
        Intended trades required to move from current positions to
        target holdings.

    ExecutedTrades
        Trades actually executed by the system.

    TradeExecutor
        Component responsible for converting TargetTrades into
        ExecutedTrades. The initial implementation assumes perfect
        execution.

    BacktestSimulator
        A deterministic simulator that evolves positions across
        trading sessions.

The initial implementation assumes:

    - single synthetic asset
    - perfect execution
    - no transaction costs
    - no liquidity constraints

These simplifications allow the architecture to be established while
keeping the execution model minimal. Future extensions will introduce
more realistic execution behaviour.

Design principles for this module follow the broader MXM architecture:

    - deterministic state surfaces
    - strict schema validation
    - explicit separation of intent and execution
    - modular system boundaries

The execution layer marks the transition from **static asset construction**
to **dynamic trading system simulation** within MXM V1.
"""
