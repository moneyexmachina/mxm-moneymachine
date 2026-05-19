"""
MXM V1 — Execution engine.

This module defines the internal execution-engine boundary between
generated orders and realised trade outcomes.

At the current stage of the execution design, the relevant
transformation is:

    submitted orders
        ↓ executor
    order executions
        ↓ aggregation
    realised trades + fill prices

This module intentionally defines MXM's own internal execution schema
rather than mirroring any particular broker API directly. Later live
execution engines (for example an Interactive Brokers executor) can map
their richer order lifecycle into these internal objects.

Temporal semantics
------------------
The execution layer distinguishes three different moments:

- order creation time
    carried on the Order object as metadata

- order submission time
    carried optionally on the OrderSubmission object

- execution / fill time
    produced by the executor as part of OrderExecution

MXM V1 execution is session-anchored:
- submitted batches always carry a session label
- perfect backtest execution prices are resolved by session
- timestamp fields remain available for richer simulated or live
  execution engines

All execution-domain instants stored on internal execution objects use the
canonical MXM timestamp representation, np.datetime64[ns]. Pandas timestamps
remain boundary-layer representations and must be converted before constructing
Order, OrderSubmission, or OrderExecution.


Current scope
-------------
The first concrete executor implemented here is:

    PerfectBacktestExecutor

which assumes:

- all submitted orders fill completely
- fill quantity equals order quantity
- fill price is obtained from an injected execution-price accessor
- fill timestamp equals:
    - submission_timestamp, if provided
    - otherwise order.created_at

Later executors may introduce:

- trade cost adjustments
- partial fills
- rejected orders
- delayed fills
- broker order identifiers
- richer execution state transitions
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from mxm.v1.execution.contract_bundles import ContractBundle
from mxm.v1.execution.orders import Order
from mxm.v1.execution.price_accessors import ExecutionPriceAccessor
from mxm.v1.utils.date_utils import coerce_np_day
from mxm.v1.utils.timestamps import (
    TSNSScalar,
    assert_not_nat,
    assert_ts_ns,
)


class ExecutionStatus(str, Enum):
    """
    Internal execution status for one submitted order.

    Only FILLED is used by the first perfect backtest executor, but the
    enum is introduced now to leave room for later richer execution
    lifecycles.
    """

    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class OrderSubmission:
    """
    Submission of a batch of orders to an executor.

    Parameters
    ----------
    orders:
        Orders being submitted for execution.

    session:
        Trading session label anchoring this submission batch.

        Required semantic form:
            np.datetime64[D]

    submission_timestamp:
        Optional canonical MXM timestamp scalar at which the batch is
        submitted.

        Required semantic form, when provided:
            np.datetime64[ns]

        The value must not be NaT.

        In live trading this would typically be the actual submission time.
        Boundary representations such as pandas timestamps, broker timestamps,
        or strings must be converted before constructing `OrderSubmission`.

        In backtests this may be omitted, in which case executors may use other
        available order metadata, for example `Order.created_at`, when a
        timestamped execution fact is required.
    """

    orders: list[Order]
    session: np.datetime64
    submission_timestamp: TSNSScalar | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "session", coerce_np_day(self.session))

        if self.submission_timestamp is not None:
            object.__setattr__(
                self,
                "submission_timestamp",
                assert_not_nat(assert_ts_ns(self.submission_timestamp)),
            )


@dataclass(frozen=True, slots=True)
class OrderExecution:
    """
    Per-order execution outcome.

    `OrderExecution` is an internal MXM execution-domain object and therefore
    stores timestamps using the canonical MXM timestamp representation:

        np.datetime64[ns]

    The timestamp value is timezone-naive at the NumPy level and interpreted
    strictly as UTC by MXM timestamp policy.

    Parameters
    ----------
    order:
        The original submitted order instruction.

    status:
        Execution status for this order.

    filled_quantity:
        Signed realised filled quantity in lots.

    fill_price:
        Fill price for the realised quantity.

    fill_timestamp:
        Canonical MXM timestamp scalar assigned to the fill outcome.

        Required semantic form:
            np.datetime64[ns]

        The value must not be NaT.
    """

    order: Order
    status: ExecutionStatus
    filled_quantity: int
    fill_price: float
    fill_timestamp: TSNSScalar

    def __post_init__(self) -> None:
        if self.filled_quantity == 0:
            raise ValueError("OrderExecution.filled_quantity must be non-zero.")

        object.__setattr__(
            self,
            "fill_timestamp",
            assert_not_nat(assert_ts_ns(self.fill_timestamp)),
        )


@dataclass(frozen=True, slots=True)
class ExecutionResult:
    """
    Aggregate result of executing a submitted batch of orders.

    Parameters
    ----------
    realised_trades:
        Net realised trade quantities aggregated by contract.

    fill_prices:
        Contract-indexed fill prices for realised trades.

        In the current implementation, there is at most one filled order
        per contract in a submitted batch, so this is well-defined as a
        single price per contract.

    order_executions:
        Per-order execution outcomes.

    Notes
    -----
    Later, if multiple orders in the same contract are allowed within a
    single submission batch, fill-price aggregation may need to become
    explicitly volume-weighted or otherwise normalised.
    """

    realised_trades: ContractBundle
    fill_prices: pd.Series
    order_executions: list[OrderExecution]

    def __post_init__(self) -> None:
        self._validate_fill_prices()

    def _validate_fill_prices(self) -> None:
        fill_prices = self.fill_prices

        if fill_prices.index.nlevels != 1:
            raise ValueError(
                "ExecutionResult.fill_prices must have a single-level index."
            )

        fill_prices_index = pd.Index(fill_prices.index, name="contract_id")

        if fill_prices_index.has_duplicates:
            duplicates = fill_prices_index[fill_prices_index.duplicated()].tolist()
            raise ValueError(
                f"ExecutionResult.fill_prices must not contain duplicate "
                f"contract_id values: {duplicates!r}"
            )

        if fill_prices.isna().any():
            raise ValueError(
                "ExecutionResult.fill_prices must not contain missing values."
            )

        if not pd.api.types.is_numeric_dtype(fill_prices):
            raise TypeError("ExecutionResult.fill_prices must be numeric.")


class Executor(ABC):
    """
    Abstract execution engine.

    An executor is a configured machine-like component that accepts a
    submitted batch of orders and produces realised execution outcomes.
    """

    @abstractmethod
    def execute_orders(
        self,
        submission: OrderSubmission,
    ) -> ExecutionResult:
        """
        Execute a submitted batch of orders.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class PerfectBacktestExecutor(Executor):
    """
    Perfect historical backtest executor.

    Parameters
    ----------
    execution_price_accessor:
        Accessor used to determine the fill price for each submitted
        order.

    Behaviour
    ---------
    - every submitted order fills completely
    - fill quantity equals order quantity
    - fill price equals the accessed execution price for the submission
      session
    - fill timestamp equals:
        - submission_timestamp, if present
        - otherwise order.created_at
    """

    execution_price_accessor: ExecutionPriceAccessor

    def execute_orders(
        self,
        submission: OrderSubmission,
    ) -> ExecutionResult:
        """
        Execute all submitted orders as full perfect fills at the
        execution price returned by the accessor.
        """
        order_executions: list[OrderExecution] = []
        realised_quantities: dict[str, int] = {}
        fill_prices_by_contract: dict[str, float] = {}
        seen_contract_ids: set[str] = set()

        for order in submission.orders:
            if order.contract_id in seen_contract_ids:
                raise ValueError(
                    "PerfectBacktestExecutor does not currently allow multiple "
                    f"orders with the same contract_id in one submission: "
                    f"{order.contract_id!r}"
                )
            seen_contract_ids.add(order.contract_id)

            fill_price = self.execution_price_accessor.get_execution_price(
                contract_id=order.contract_id,
                session=submission.session,
            )

            fill_timestamp = (
                submission.submission_timestamp
                if submission.submission_timestamp is not None
                else order.created_at
            )

            execution = OrderExecution(
                order=order,
                status=ExecutionStatus.FILLED,
                filled_quantity=order.quantity,
                fill_price=float(fill_price),
                fill_timestamp=fill_timestamp,
            )
            order_executions.append(execution)

            if order.contract_id in realised_quantities:
                realised_quantities[order.contract_id] += order.quantity
            else:
                realised_quantities[order.contract_id] = order.quantity

            # Current assumption: at most one order per contract in one
            # submission batch. If later multiple orders per contract are
            # allowed, this fill-price aggregation may need refinement.
            fill_prices_by_contract[order.contract_id] = float(fill_price)

        if realised_quantities:
            realised_trades = ContractBundle.from_dict(realised_quantities)
        else:
            realised_trades = ContractBundle.empty()

        if fill_prices_by_contract:
            fill_prices = pd.Series(fill_prices_by_contract, dtype="float64")
            fill_prices.index = pd.Index(fill_prices.index, name="contract_id")
            fill_prices = fill_prices.sort_index()
        else:
            fill_prices = pd.Series(
                dtype="float64",
                index=pd.Index([], name="contract_id"),
            )

        return ExecutionResult(
            realised_trades=realised_trades,
            fill_prices=fill_prices,
            order_executions=order_executions,
        )
