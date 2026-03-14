"""
mxm.v1.pnl

Economic PnL construction layer for MXM V1 backtests.

This module converts the execution state transitions produced by the
backtesting engine into an economic profit-and-loss representation.

Conceptual Position in the Architecture
---------------------------------------

The PnL layer sits *above execution*.

Execution infrastructure is responsible for determining:

    - which holdings were carried into a session
    - which trades were executed during the session
    - the fill prices of those trades
    - the realised holdings after execution

These outcomes are captured in the SessionResult chain produced by the
backtester.

The PnL module consumes those results and computes the *economic
consequences* of those state transitions.

The result is a canonical PnL series representing the realised economic
performance of the strategy across sessions.


PnL Decomposition
-----------------

For each session, total PnL is decomposed into two components:

1. Price-Move PnL

   PnL resulting from the mark-to-market change of positions that were
   carried into the session.

   Conceptually:

       initial_holdings × (mark_t − mark_{t−1})

2. Trade PnL

   PnL resulting from executing trades at prices different from the
   session mark.

   Conceptually:

       realised_trades × (mark_t − fill_price)

Total PnL is defined as:

    total_pnl = price_move_pnl + trade_pnl


Economic Scaling
----------------

PnL calculations must include the economic size of each contract.
For each contract the PnL contribution is scaled by:

    contract_quantity
    × contract_multiplier
    × price_change
    × fx_multiplier

The contract multiplier is obtained from reference data.


FX Translation
--------------

PnL is expressed in the currency of the synthetic asset.

In the full architecture this requires translating contract PnL from
native contract currency into asset currency via FX rates.

For Session 29 only the following behaviour is implemented:

    if contract_currency == asset_currency:
        fx_multiplier = 1.0

    otherwise:
        raise NotImplementedError

A dedicated FX conversion interface is included so that full FX
translation can be implemented in later sessions without changing the
PnL construction logic.


Outputs
-------

The primary outputs of this module are:

    SessionPnL
        Economic result of a single session.

    PnLSeries
        Ordered collection of session PnL values with convenience
        accessors for analysis and plotting.


Responsibilities
----------------

The PnL module is responsible for:

    - computing session-level economic PnL
    - applying contract multipliers
    - applying FX conversion
    - decomposing PnL into price-move and trade components
    - producing a deterministic PnL series

It is not responsible for:

    - order generation
    - execution logic
    - portfolio optimisation
    - strategy design
    - reporting layer formatting

Those concerns belong to other MXM modules.


Design Goal
-----------

The design goal of this module is to provide a single, canonical
representation of economic performance that can be reused across:

    - backtests
    - live trading accounting
    - attribution analysis
    - risk reporting
"""
