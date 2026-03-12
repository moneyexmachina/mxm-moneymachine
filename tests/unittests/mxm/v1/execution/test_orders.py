from datetime import datetime, timezone

import pandas as pd
import pandas.testing as pdt
import pytest

from mxm.v1.execution.contract_bundles import TargetContractBundle
from mxm.v1.execution.orders import (
    Order,
    OrderGenerationPolicy,
    OrderGenerator,
    OrderType,
)
from mxm.v1.utils.time_utils import to_utc_ts

CREATED_AT = to_utc_ts(datetime(2026, 3, 12, 10, 0, 0, tzinfo=timezone.utc))


def _order_tuples(
    orders: list[Order],
) -> list[tuple[str, int, OrderType, pd.Timestamp, int | None]]:
    return [
        (
            order.contract_id,
            order.quantity,
            order.order_type,
            order.created_at,
            order.order_id,
        )
        for order in orders
    ]


def test_order_rejects_zero_quantity() -> None:
    with pytest.raises(ValueError, match="must be non-zero"):
        Order(
            contract_id="corn_mar2026",
            quantity=0,
            order_type=OrderType.MARKET,
            created_at=CREATED_AT,
        )


def test_order_side_is_buy_for_positive_quantity() -> None:
    order = Order(
        contract_id="corn_mar2026",
        quantity=3,
        order_type=OrderType.MARKET,
        created_at=CREATED_AT,
    )

    assert order.side == "BUY"


def test_order_side_is_sell_for_negative_quantity() -> None:
    order = Order(
        contract_id="corn_mar2026",
        quantity=-3,
        order_type=OrderType.MARKET,
        created_at=CREATED_AT,
    )

    assert order.side == "SELL"


def test_order_abs_quantity_returns_absolute_value() -> None:
    order = Order(
        contract_id="corn_mar2026",
        quantity=-7,
        order_type=OrderType.MARKET,
        created_at=CREATED_AT,
    )

    assert order.abs_quantity == 7


def test_order_accepts_optional_order_id() -> None:
    order = Order(
        contract_id="corn_mar2026",
        quantity=1,
        order_type=OrderType.MARKET,
        created_at=CREATED_AT,
        order_id=42,
    )

    assert order.order_id == 42


def test_order_normalises_created_at_to_utc_timestamp() -> None:
    order = Order(
        contract_id="corn_mar2026",
        quantity=1,
        order_type=OrderType.MARKET,
        created_at="2026-03-12T10:00:00Z",
    )

    assert order.created_at == to_utc_ts("2026-03-12T10:00:00Z")


def test_order_generation_policy_accepts_default_configuration() -> None:
    policy = OrderGenerationPolicy()

    assert policy.default_min_block_size == 1
    assert policy.min_block_sizes is None
    assert policy.default_order_type == OrderType.MARKET


def test_order_generation_policy_rejects_non_positive_default_min_block_size() -> None:
    with pytest.raises(ValueError, match="strictly positive"):
        OrderGenerationPolicy(default_min_block_size=0)


def test_order_generation_policy_rejects_missing_min_block_sizes() -> None:
    min_block_sizes = pd.Series(
        [1, None],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
    )

    with pytest.raises(ValueError, match="must not contain missing values"):
        OrderGenerationPolicy(min_block_sizes=min_block_sizes)


def test_order_generation_policy_rejects_non_numeric_min_block_sizes() -> None:
    min_block_sizes = pd.Series(
        ["a", "b"],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="object",
    )

    with pytest.raises(TypeError, match="must be numeric"):
        OrderGenerationPolicy(min_block_sizes=min_block_sizes)


def test_order_generation_policy_rejects_non_positive_min_block_size_entries() -> None:
    min_block_sizes = pd.Series(
        [1, 0],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
    )

    with pytest.raises(ValueError, match="must be strictly positive"):
        OrderGenerationPolicy(min_block_sizes=min_block_sizes)


def test_generate_orders_from_empty_target_trades_returns_empty_result() -> None:
    generator = OrderGenerator(policy=OrderGenerationPolicy())
    target_trades = TargetContractBundle.empty()

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    expected = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))

    assert result.implemented_trades.is_empty()
    assert result.orders == []
    pdt.assert_series_equal(result.implemented_trades.quantities, expected)


def test_generate_orders_rounds_small_trades_to_zero_with_default_block_size() -> None:
    generator = OrderGenerator(policy=OrderGenerationPolicy())
    target_trades = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 0.49,
            "corn_may2026": -0.49,
        }
    )

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    expected = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))

    assert result.implemented_trades.is_empty()
    assert result.orders == []
    pdt.assert_series_equal(result.implemented_trades.quantities, expected)


def test_generate_orders_rounds_positive_half_away_from_zero() -> None:
    generator = OrderGenerator(policy=OrderGenerationPolicy())
    target_trades = TargetContractBundle.from_dict(
        {
            "a": 0.50,
            "b": 1.50,
        }
    )

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    expected = pd.Series(
        [1, 2],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.implemented_trades.quantities, expected)
    assert _order_tuples(result.orders) == [
        ("a", 1, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
        ("b", 2, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
    ]


def test_generate_orders_rounds_negative_half_away_from_zero() -> None:
    generator = OrderGenerator(policy=OrderGenerationPolicy())
    target_trades = TargetContractBundle.from_dict(
        {
            "a": -0.50,
            "b": -1.50,
        }
    )

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    expected = pd.Series(
        [-1, -2],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.implemented_trades.quantities, expected)
    assert _order_tuples(result.orders) == [
        ("a", -1, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
        ("b", -2, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
    ]


def test_generate_orders_uses_default_block_size_when_no_override_exists() -> None:
    policy = OrderGenerationPolicy(default_min_block_size=5)
    generator = OrderGenerator(policy=policy)
    target_trades = TargetContractBundle.from_dict({"corn_mar2026": 7.4})

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    expected = pd.Series(
        [5],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.implemented_trades.quantities, expected)
    assert _order_tuples(result.orders) == [
        ("corn_mar2026", 5, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
    ]


def test_generate_orders_uses_per_contract_block_size_override() -> None:
    min_block_sizes = pd.Series(
        [5],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )
    policy = OrderGenerationPolicy(
        default_min_block_size=1,
        min_block_sizes=min_block_sizes,
    )
    generator = OrderGenerator(policy=policy)
    target_trades = TargetContractBundle.from_dict({"corn_mar2026": 7.5})

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    expected = pd.Series(
        [10],
        index=pd.Index(["corn_mar2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.implemented_trades.quantities, expected)
    assert _order_tuples(result.orders) == [
        ("corn_mar2026", 10, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
    ]


def test_generate_orders_handles_mixed_contract_block_sizes() -> None:
    min_block_sizes = pd.Series(
        [5, 2],
        index=pd.Index(["corn_mar2026", "wheat_jul2026"], name="contract_id"),
        dtype="int64",
    )
    policy = OrderGenerationPolicy(
        default_min_block_size=1,
        min_block_sizes=min_block_sizes,
    )
    generator = OrderGenerator(policy=policy)
    target_trades = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 7.4,
            "soy_nov2026": 1.6,
            "wheat_jul2026": -3.0,
        }
    )

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    expected = pd.Series(
        [5, 2, -4],
        index=pd.Index(
            ["corn_mar2026", "soy_nov2026", "wheat_jul2026"],
            name="contract_id",
        ),
        dtype="int64",
    )

    pdt.assert_series_equal(result.implemented_trades.quantities, expected)
    assert _order_tuples(result.orders) == [
        ("corn_mar2026", 5, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
        ("soy_nov2026", 2, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
        ("wheat_jul2026", -4, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
    ]


def test_generate_orders_returns_market_orders_by_default() -> None:
    generator = OrderGenerator(policy=OrderGenerationPolicy())
    target_trades = TargetContractBundle.from_dict({"corn_mar2026": 1.0})

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    assert len(result.orders) == 1
    assert result.orders[0].order_type == OrderType.MARKET


def test_generate_orders_assigns_created_at_to_all_orders() -> None:
    generator = OrderGenerator(policy=OrderGenerationPolicy())
    target_trades = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 1.0,
            "corn_may2026": -2.0,
        }
    )

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at="2026-03-12T10:00:00Z",
    )

    expected_created_at = to_utc_ts("2026-03-12T10:00:00Z")
    assert all(order.created_at == expected_created_at for order in result.orders)


def test_generate_orders_returns_orders_consistent_with_implemented_trades() -> None:
    generator = OrderGenerator(policy=OrderGenerationPolicy())
    target_trades = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 2.0,
            "corn_may2026": -1.0,
            "wheat_jul2026": 0.49,
        }
    )

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    expected_trades = pd.Series(
        [2, -1],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.implemented_trades.quantities, expected_trades)
    assert _order_tuples(result.orders) == [
        ("corn_mar2026", 2, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
        ("corn_may2026", -1, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
    ]


def test_generate_orders_drops_zero_implemented_trades() -> None:
    generator = OrderGenerator(policy=OrderGenerationPolicy())
    target_trades = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 0.49,
            "corn_may2026": 0.50,
        }
    )

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    expected = pd.Series(
        [1],
        index=pd.Index(["corn_may2026"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.implemented_trades.quantities, expected)
    assert _order_tuples(result.orders) == [
        ("corn_may2026", 1, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
    ]


def test_generate_orders_returns_deterministic_contract_order() -> None:
    generator = OrderGenerator(policy=OrderGenerationPolicy())
    target_trades = TargetContractBundle.from_dict(
        {
            "wheat_jul2026": 2.0,
            "corn_mar2026": 1.0,
            "soy_nov2026": -3.0,
        }
    )

    result = generator.generate_orders(
        target_trades=target_trades,
        created_at=CREATED_AT,
    )

    assert _order_tuples(result.orders) == [
        ("corn_mar2026", 1, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
        ("soy_nov2026", -3, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
        ("wheat_jul2026", 2, OrderType.MARKET, to_utc_ts(CREATED_AT), None),
    ]
