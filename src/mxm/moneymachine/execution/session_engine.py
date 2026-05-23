"""
MXM V1 — Session engine.

This module defines the canonical single-session trading-state
orchestration of the MXM execution layer.

Architectural role
------------------
The session engine is intentionally generic. It is not specifically a
backtester, paper-trading runner, or live-trading adapter.

Instead, it defines the common session-step transformation:

    previous_realised_holdings
        ↓ prepare_initial_holdings
    initial_holdings
        ↓ build_target_trades
    target_trades
        ↓ order generation
    implemented_trades + orders
        ↓ execution
    execution_result
        ↓ apply_realised_trades
    realised_holdings

This single-session step can later be embedded inside:

- a historical backtest loop
- a forward simulation loop
- a paper-trading session runner
- a live trading orchestration layer

Current scope
-------------
The engine currently records net state only. Later versions may add
attributed companions for holdings and trades, such as:

- attributed_initial_holdings
- attributed_target_holdings
- attributed_target_trades
- attributed_implemented_trades
- attributed_realised_trades

Those extensions belong to a later attribution-focused refactor.

Temporal semantics
------------------
MXM V1 is session-native at the orchestration layer.

The engine distinguishes:

- previous_session:
    the session from which previous_realised_holdings were carried

- session:
    the current session being processed

Both are session labels, represented canonically as `np.datetime64[D]`.

For the first session in a run, previous_session may be None.

Current implementation choices
------------------------------
- the engine itself is fully session-native
- no synthetic timestamps are introduced here
- timestamped execution facts may be introduced downstream by the
  OrderGenerator and Executor
- any future timestamp-based execution layer should be added as a later
  adapter or execution-model extension, not by smuggling timestamp
  semantics into the V1 session engine
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from mxm.moneymachine.execution.contract_bundles import (
    ContractBundle,
    TargetContractBundle,
)
from mxm.moneymachine.execution.executor import (
    ExecutionResult,
    Executor,
    OrderSubmission,
)
from mxm.moneymachine.execution.holdings import (
    apply_realised_trades,
    prepare_initial_holdings,
)
from mxm.moneymachine.execution.orders import Order, OrderGenerator
from mxm.moneymachine.execution.trades import build_target_trades
from mxm.moneymachine.utils.date_utils import coerce_np_day
from mxm.refdata.api.ref_data_api import (
    RefDataAPI,  # type: ignore[reportMissingTypeStubs]
)


@dataclass(frozen=True, slots=True)
class SessionResult:
    """
    Net result of one trading session step.

    Parameters
    ----------
    previous_session:
        The session from which previous_realised_holdings were carried.

        None indicates that this is the first processed session in the
        run.

    session:
        The current session being processed.

    previous_realised_holdings:
        Realised holdings carried from the previous session.

    initial_holdings:
        Decision-ready holdings after session preparation / housekeeping.

    target_holdings:
        Ideal target holdings for the current session.

    target_trades:
        Ideal desired change from initial_holdings to target_holdings.

    implemented_trades:
        Executable integer-lot trades implied by order generation.

    orders:
        Orders rendered from implemented_trades.

    execution_result:
        Realised execution outcomes for the submitted orders.

    realised_holdings:
        Realised holdings after applying realised trades to
        initial_holdings.

    Notes
    -----
    This object records the full net transition chain for one session.
    Later versions may extend it with attributed companions.
    """

    previous_session: np.datetime64 | None
    session: np.datetime64
    previous_realised_holdings: ContractBundle
    initial_holdings: ContractBundle
    target_holdings: TargetContractBundle
    target_trades: TargetContractBundle
    implemented_trades: ContractBundle
    orders: list[Order]
    execution_result: ExecutionResult
    realised_holdings: ContractBundle

    def __post_init__(self) -> None:
        if self.previous_session is not None:
            object.__setattr__(
                self,
                "previous_session",
                coerce_np_day(self.previous_session),
            )

        object.__setattr__(self, "session", coerce_np_day(self.session))


@dataclass(frozen=True, slots=True)
class SessionEngine:
    """
    Generic single-session trading engine.

    Parameters
    ----------
    ref_data_api:
        Reference-data API used during holdings preparation.

    order_generator:
        Generator used to convert target trades into implemented trades
        and executable orders.

    executor:
        Executor used to submit orders and obtain realised execution
        outcomes.
    """

    ref_data_api: RefDataAPI
    order_generator: OrderGenerator
    executor: Executor

    def run_session(
        self,
        *,
        session: np.datetime64,
        previous_realised_holdings: ContractBundle,
        target_holdings: TargetContractBundle,
        previous_session: np.datetime64 | None = None,
    ) -> SessionResult:
        """
        Run one canonical trading session step.

        Parameters
        ----------
        session:
            The current session label.

        previous_realised_holdings:
            Realised holdings carried from the previous session.

        target_holdings:
            Ideal target holdings for the current session.

        previous_session:
            Optional session label from which previous_realised_holdings
            were carried.

        Returns
        -------
        SessionResult
            Full net transition record for the session.
        """
        session_day = coerce_np_day(session)
        previous_session_day = (
            None if previous_session is None else coerce_np_day(previous_session)
        )

        initial_holdings = prepare_initial_holdings(
            realised_holdings=previous_realised_holdings,
            session=session_day,
            ref_data_api=self.ref_data_api,
        )

        target_trades = build_target_trades(
            initial_holdings=initial_holdings,
            target_holdings=target_holdings,
        )

        order_generation = self.order_generator.generate_orders(
            target_trades=target_trades,
            session=session_day,
        )

        submission = OrderSubmission(
            orders=order_generation.orders,
            session=session_day,
        )

        execution_result = self.executor.execute_orders(submission)

        realised_holdings = apply_realised_trades(
            initial_holdings=initial_holdings,
            realised_trades=execution_result.realised_trades,
        )

        return SessionResult(
            previous_session=previous_session_day,
            session=session_day,
            previous_realised_holdings=previous_realised_holdings,
            initial_holdings=initial_holdings,
            target_holdings=target_holdings,
            target_trades=target_trades,
            implemented_trades=order_generation.implemented_trades,
            orders=order_generation.orders,
            execution_result=execution_result,
            realised_holdings=realised_holdings,
        )
