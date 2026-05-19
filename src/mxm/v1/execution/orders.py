"""
MXM V1 — Order generation.

This module defines the boundary between target-trade intent and executable
order instructions.

At the current stage of the execution design, the relevant transformation is:

    target_trades
        ↓ order generation policy
    implemented_trades
        ↓ order rendering + timestamp assignment
    orders

Conceptually:

- target_trades are ideal desired changes in holdings and may be fractional
- implemented_trades are executable integer-lot trade quantities after applying
  an implementation policy such as block rounding
- orders are explicit executable instructions derived from implemented trades

This module is intentionally focused on the portfolio-side implementation of
intent. It does not yet model execution quality, partial fills, routing, or
broker order lifecycle. Those concerns belong later in the execution / routing
layer.

Temporal semantics
------------------
MXM distinguishes session labels from timestamps.

Session labels are calendar-domain identifiers represented as:

    np.datetime64[D]

They identify trading sessions and are used as inputs to order generation.

Order creation times are timeline-domain instants represented internally as
canonical MXM timestamps:

    np.datetime64[ns]

These timestamps are timezone-naive NumPy values interpreted strictly as UTC
under the MXM timestamp policy.

`generate_orders(...)` accepts a session label and resolves per-order
`created_at` timestamps according to the injected timestamping policy and the
relevant product trading calendar. Trading-calendar open/close values may be
pandas boundary timestamps, but generated `Order` objects store only canonical
MXM timestamp scalars.

The current implementation supports one generation style:

- round target trades to the nearest executable block
- default block size = 1
- optional per-contract block-size overrides
- render one market order per non-zero implemented trade
- assign one canonical timestamp per order from the contract's trading calendar

All logic in this module is deterministic: given target trades, a session label,
and a policy configuration, the resulting implemented trades and orders are
deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from mxm.refdata.api.ref_data_api import (
    RefDataAPI,  # type: ignore[reportMissingTypeStubs]
)
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle
from mxm.v1.utils.date_utils import coerce_np_day
from mxm.v1.utils.pandas_timestamps import ts_ns_from_pd_timestamp
from mxm.v1.utils.timestamps import TSNSScalar, assert_not_nat, assert_ts_ns


class OrderType(str, Enum):
    """
    Supported internal MXM order types.

    Only MARKET is implemented in the first version.
    """

    MARKET = "market"


class OrderTimestampPolicy(str, Enum):
    """
    Policy for assigning `created_at` timestamps to generated orders.

    SESSION_OPEN:
        Stamp each generated order with the open timestamp of the
        relevant contract's product calendar for the given session.

    SESSION_CLOSE:
        Stamp each generated order with the close timestamp of the
        relevant contract's product calendar for the given session.
    """

    SESSION_OPEN = "session_open"
    SESSION_CLOSE = "session_close"


@dataclass(frozen=True, slots=True)
class Order:
    """
    Internal executable order instruction.

    `Order` is an internal MXM object. It therefore stores timestamps in the
    canonical MXM timestamp representation:

        np.datetime64[ns]

    The value is timezone-naive at the NumPy level and interpreted strictly as UTC
    by MXM policy. Boundary representations such as `pd.Timestamp`, ISO strings,
    broker timestamps, or database strings must be converted before constructing an
    `Order`.

    Parameters
    ----------
    contract_id:
        Contract identifier to trade.

    quantity:
        Signed integer order quantity in lots.

        Positive quantity indicates buy.
        Negative quantity indicates sell.

    order_type:
        Order type instruction.

    created_at:
        Canonical MXM timestamp scalar at which the order instruction was created.

        Required form:
            np.datetime64[ns]

        The value must not be NaT.

    order_id:
        Optional order identifier. This is intentionally optional in the current
        version because canonical append-only order identity belongs to a later
        accounting / audit design.
    """

    contract_id: str
    quantity: int
    order_type: OrderType
    created_at: TSNSScalar
    order_id: int | None = None

    def __post_init__(self) -> None:
        if self.quantity == 0:
            raise ValueError("Order.quantity must be non-zero.")

        object.__setattr__(
            self,
            "created_at",
            assert_not_nat(assert_ts_ns(self.created_at)),
        )

    @property
    def side(self) -> str:
        """
        Human-readable order side derived from signed quantity.
        """
        return "BUY" if self.quantity > 0 else "SELL"

    @property
    def abs_quantity(self) -> int:
        """
        Absolute lot quantity.
        """
        return abs(self.quantity)


@dataclass(frozen=True, slots=True)
class OrderGenerationResult:
    """
    Result of order generation from target trades.

    Parameters
    ----------
    implemented_trades:
        Executable integer-lot trades implied by the generation policy.

    orders:
        Order instructions rendered from the implemented trades.

    Notes
    -----
    The implementation friction introduced during order generation can
    later be derived as:

        target_trades - implemented_trades
    """

    implemented_trades: ContractBundle
    orders: list[Order]


@dataclass(frozen=True, slots=True)
class OrderGenerationPolicy:
    """
    Declarative policy controlling how target trades are transformed into
    implemented trades and orders.

    Parameters
    ----------
    default_min_block_size:
        Default minimum executable block size. Must be strictly positive.

    min_block_sizes:
        Optional per-contract block-size overrides, indexed by
        contract_id.

    default_order_type:
        Order type used when rendering executable orders.

    timestamp_policy:
        Policy used to assign `created_at` timestamps to generated
        orders.

    Notes
    -----
    This policy is intentionally declarative. It specifies how order
    generation should behave, while the OrderGenerator owns the actual
    generation method.

    The current implementation assumes block-rounded generation into
    market orders, with timestamp assignment from the relevant product
    trading calendar.
    """

    default_min_block_size: int = 1
    min_block_sizes: pd.Series | None = None
    default_order_type: OrderType = OrderType.MARKET
    timestamp_policy: OrderTimestampPolicy = OrderTimestampPolicy.SESSION_OPEN

    def __post_init__(self) -> None:
        if self.default_min_block_size <= 0:
            raise ValueError("default_min_block_size must be strictly positive.")

        if self.min_block_sizes is not None:
            if self.min_block_sizes.isna().any():
                raise ValueError("min_block_sizes must not contain missing values.")

            if not pd.api.types.is_numeric_dtype(self.min_block_sizes):
                raise TypeError("min_block_sizes must be numeric.")

            if (self.min_block_sizes <= 0).any():
                raise ValueError("min_block_sizes entries must be strictly positive.")


@dataclass(frozen=True, slots=True)
class OrderGenerator:
    """
    Generate executable orders from target trades according to an
    injected generation policy.

    The generator owns the active transformation:

        target_trades
            ↓
        implemented_trades
            ↓
        timestamped orders

    while the injected policy defines how this should be done.

    Parameters
    ----------
    policy:
        Declarative generation policy controlling block sizes, order
        rendering defaults, and timestamp assignment.

    ref_data_api:
        Reference-data API used to resolve contract_id -> product_id.

    calendar_service:
        Trading-calendar bridge used to resolve product calendars for
        timestamp assignment.
    """

    policy: OrderGenerationPolicy
    ref_data_api: RefDataAPI
    calendar_service: TradingCalendarService

    def generate_orders(
        self,
        target_trades: TargetContractBundle,
        session: np.datetime64,
    ) -> OrderGenerationResult:
        """
        Generate implemented trades and executable orders from target
        trades for a given session.

        Current behaviour
        -----------------
        - round target trades to the nearest executable block
        - half-way cases round away from zero
        - one non-zero implemented trade becomes one order
        - orders use the policy default order type
        - each order receives a `created_at` timestamp derived from the
          contract's product trading calendar and the policy's
          timestamping rule

        Parameters
        ----------
        target_trades:
            Ideal target trade quantities in target-space.

        session:
            Trading session label for which orders are being generated.

            Required semantic form:
                np.datetime64

        Returns
        -------
        OrderGenerationResult
            Implemented executable trades and rendered orders.
        """
        session_day = coerce_np_day(session)

        implemented_quantities: dict[str, int] = {}
        orders: list[Order] = []

        for contract_key, target_quantity in target_trades.quantities.items():
            contract_id = str(contract_key)

            block_size = self._resolve_block_size(contract_id)
            implemented_quantity = self._round_to_signed_block(
                quantity=float(target_quantity),
                block_size=block_size,
            )

            if implemented_quantity == 0:
                continue

            created_at = self._resolve_order_timestamp(
                contract_id=contract_id,
                session=session_day,
            )

            implemented_quantities[contract_id] = implemented_quantity
            orders.append(
                Order(
                    contract_id=contract_id,
                    quantity=implemented_quantity,
                    order_type=self.policy.default_order_type,
                    created_at=created_at,
                )
            )

        if implemented_quantities:
            implemented_trades = ContractBundle.from_dict(implemented_quantities)
        else:
            implemented_trades = ContractBundle.empty()

        return OrderGenerationResult(
            implemented_trades=implemented_trades,
            orders=orders,
        )

    def _resolve_order_timestamp(
        self,
        *,
        contract_id: str,
        session: np.datetime64,
    ) -> TSNSScalar:
        """
        Resolve the canonical `created_at` timestamp for one generated order.

        This is the explicit bridge from session-native target-trade intent to
        timestamped executable order instructions. Calendar open/close values are
        pandas boundary timestamps; generated orders store canonical MXM timestamps.
        """
        contract = self.ref_data_api.get_contract_by_id(contract_id)
        product_id = contract.product_id
        calendar = self.calendar_service.calendar_for_product(product_id)

        if self.policy.timestamp_policy == OrderTimestampPolicy.SESSION_OPEN:
            return ts_ns_from_pd_timestamp(calendar.session_open(session))

        if self.policy.timestamp_policy == OrderTimestampPolicy.SESSION_CLOSE:
            return ts_ns_from_pd_timestamp(calendar.session_close(session))

        raise ValueError(
            f"Unsupported OrderTimestampPolicy: {self.policy.timestamp_policy!r}"
        )

    def _resolve_block_size(self, contract_id: str) -> int:
        """
        Resolve executable block size for a contract.
        """
        if self.policy.min_block_sizes is None:
            return self.policy.default_min_block_size

        if contract_id not in self.policy.min_block_sizes.index:
            return self.policy.default_min_block_size

        raw_value = self.policy.min_block_sizes.loc[contract_id]
        block_size = int(raw_value)

        if block_size <= 0:
            raise ValueError(
                f"Resolved block size must be strictly positive for {contract_id!r}."
            )

        return block_size

    @staticmethod
    def _round_to_signed_block(quantity: float, block_size: int) -> int:
        """
        Round signed quantity to the nearest multiple of block_size, with
        half-way cases rounded away from zero.

        Examples for block size = 1:
            +0.49 -> 0
            +0.50 -> +1
            -0.49 -> 0
            -0.50 -> -1

        Examples for block size = 5:
            +2.4  -> 0
            +2.5  -> +5
            +7.4  -> +5
            +7.5  -> +10
        """
        scaled = quantity / block_size

        if scaled >= 0:
            rounded_units = int(np.floor(scaled + 0.5))
        else:
            rounded_units = int(np.ceil(scaled - 0.5))

        return rounded_units * block_size
