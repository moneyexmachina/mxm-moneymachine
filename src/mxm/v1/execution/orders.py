from __future__ import annotations

"""
MXM V1 — Order generation.

This module defines the boundary between target-trade intent and
executable order instructions.

At the current stage of the execution design, the relevant
transformation is:

    target_trades
        ↓ order generation policy
    implemented_trades
        ↓ order rendering
    orders

Conceptually:

- target_trades are ideal desired changes in holdings and may be
  fractional
- implemented_trades are executable integer-lot trade quantities after
  application of an implementation policy such as block rounding
- orders are explicit executable instructions derived from the
  implemented trades

This module is intentionally focused on the portfolio-side
implementation of intent. It does not yet model execution quality,
partial fills, routing, or broker order lifecycle. Those concerns belong
later in the execution / routing layer.

The current implementation supports one generation style:

- round target trades to the nearest executable block
- default block size = 1
- optional per-contract block-size overrides
- render one market order per non-zero implemented trade

The gap between:

    target_trades
    implemented_trades

is not explicitly stored as its own object here, but can be derived
later for attribution purposes.

All logic in this module is deterministic:
given target trades and a policy configuration, the resulting
implemented trades and orders are deterministic.
"""

from dataclasses import dataclass
from enum import Enum

import numpy as np
import pandas as pd

from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle
from mxm.v1.utils.time_utils import UtcTimestampInput, to_utc_ts


class OrderType(str, Enum):
    """
    Supported internal MXM order types.

    Only MARKET is implemented in the first version.
    """

    MARKET = "market"


@dataclass(frozen=True, slots=True)
class Order:
    """
    Internal executable order instruction.

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
        Canonical UTC-normalised timestamp at which the order instruction
        was created by the portfolio-side order generation process.

    order_id:
        Optional order identifier. This is intentionally optional in the
        current version because canonical append-only order identity
        belongs to a later accounting / audit design.
    """

    contract_id: str
    quantity: int
    order_type: OrderType
    created_at: pd.Timestamp
    order_id: int | None = None

    def __post_init__(self) -> None:
        if self.quantity == 0:
            raise ValueError("Order.quantity must be non-zero.")
        object.__setattr__(self, "created_at", to_utc_ts(self.created_at))

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

    Notes
    -----
    This policy is intentionally declarative. It specifies how order
    generation should behave, while the OrderGenerator owns the actual
    generation method.

    The current implementation assumes block-rounded generation into
    market orders, but the policy object is intended to remain
    extensible as order-generation styles evolve.
    """

    default_min_block_size: int = 1
    min_block_sizes: pd.Series | None = None
    default_order_type: OrderType = OrderType.MARKET

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
        orders

    while the injected policy defines how this should be done.

    Parameters
    ----------
    policy:
        Declarative generation policy controlling block sizes and order
        rendering defaults.
    """

    policy: OrderGenerationPolicy

    def generate_orders(
        self,
        target_trades: TargetContractBundle,
        created_at: UtcTimestampInput,
    ) -> OrderGenerationResult:
        """
        Generate implemented trades and executable orders from target
        trades.

        Current behaviour
        -----------------
        - round target trades to the nearest executable block
        - half-way cases round away from zero
        - one non-zero implemented trade becomes one order
        - orders use the policy default order type

        Parameters
        ----------
        target_trades:
            Ideal target trade quantities in target-space.

        created_at:
            Timestamp assigned to the generated order instructions.

        Returns
        -------
        OrderGenerationResult
            Implemented executable trades and rendered orders.
        """
        implemented_quantities: dict[str, int] = {}
        orders: list[Order] = []
        created_at_utc = to_utc_ts(created_at)
        for contract_key, target_quantity in target_trades.quantities.items():
            contract_id = str(contract_key)

            block_size = self._resolve_block_size(contract_id)
            implemented_quantity = self._round_to_signed_block(
                quantity=float(target_quantity),
                block_size=block_size,
            )

            if implemented_quantity == 0:
                continue

            implemented_quantities[contract_id] = implemented_quantity
            orders.append(
                Order(
                    contract_id=contract_id,
                    quantity=implemented_quantity,
                    order_type=self.policy.default_order_type,
                    created_at=created_at_utc,
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
