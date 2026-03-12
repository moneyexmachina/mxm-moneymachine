from __future__ import annotations

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
The engine distinguishes:

- previous_session:
    the session from which previous_realised_holdings were carried

- session:
    the current session being processed

For the first session in a run, previous_session may be None.

Current implementation choices
------------------------------
- the session timestamp is used as:
    - the order created_at timestamp
    - the order submission_timestamp

This keeps the first implementation simple and deterministic. Later
versions may separate these timestamps if needed.
"""

from dataclasses import dataclass

import pandas as pd
from mxm_refdata.api.ref_data_api import (
    RefDataAPI,  # type: ignore[reportMissingTypeStubs]
)

from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle
from mxm.v1.execution.executor import ExecutionResult, Executor, OrderSubmission
from mxm.v1.execution.holdings import (
    apply_realised_trades,
    prepare_initial_holdings,
)
from mxm.v1.execution.orders import Order, OrderGenerator
from mxm.v1.execution.trades import build_target_trades
from mxm.v1.utils.time_utils import UtcTimestampInput, to_utc_ts


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

    previous_session: pd.Timestamp | None
    session: pd.Timestamp
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
                to_utc_ts(self.previous_session),
            )

        object.__setattr__(self, "session", to_utc_ts(self.session))


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
        session: UtcTimestampInput,
        previous_realised_holdings: ContractBundle,
        target_holdings: TargetContractBundle,
        previous_session: UtcTimestampInput | None = None,
    ) -> SessionResult:
        """
        Run one canonical trading session step.

        Parameters
        ----------
        session:
            The current session timestamp.

        previous_realised_holdings:
            Realised holdings carried from the previous session.

        target_holdings:
            Ideal target holdings for the current session.

        previous_session:
            Optional session timestamp from which
            previous_realised_holdings were carried.

        Returns
        -------
        SessionResult
            Full net transition record for the session.
        """
        session_ts = to_utc_ts(session)
        previous_session_ts = (
            None if previous_session is None else to_utc_ts(previous_session)
        )

        initial_holdings = prepare_initial_holdings(
            realised_holdings=previous_realised_holdings,
            session=session_ts.to_datetime64(),
            ref_data_api=self.ref_data_api,
        )

        target_trades = build_target_trades(
            initial_holdings=initial_holdings,
            target_holdings=target_holdings,
        )

        order_generation = self.order_generator.generate_orders(
            target_trades=target_trades,
            created_at=session_ts,
        )

        submission = OrderSubmission(
            orders=order_generation.orders,
            submission_timestamp=session_ts,
        )

        execution_result = self.executor.execute_orders(submission)

        realised_holdings = apply_realised_trades(
            initial_holdings=initial_holdings,
            realised_trades=execution_result.realised_trades,
        )

        return SessionResult(
            previous_session=previous_session_ts,
            session=session_ts,
            previous_realised_holdings=previous_realised_holdings,
            initial_holdings=initial_holdings,
            target_holdings=target_holdings,
            target_trades=target_trades,
            implemented_trades=order_generation.implemented_trades,
            orders=order_generation.orders,
            execution_result=execution_result,
            realised_holdings=realised_holdings,
        )
