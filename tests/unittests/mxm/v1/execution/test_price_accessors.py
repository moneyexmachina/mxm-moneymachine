from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mxm.v1.execution.price_accessors import (
    DailyMarkExecutionPriceAccessor,
    DailyStatsExecutionPriceAccessor,
    _ProductDailyMarkPriceLookup,
    _ProductDailyStatsPriceLookup,
)


class DummyContract:
    def __init__(self, product_id: str) -> None:
        self.product_id = product_id


class DummyRefDataAPI:
    def __init__(self, mapping: dict[str, DummyContract]) -> None:
        self._mapping = mapping

    def get_contract_by_id(self, contract_id: str) -> DummyContract | None:
        return self._mapping.get(contract_id)


def _valid_price_series() -> pd.Series:
    index = pd.MultiIndex.from_tuples(
        [
            ("corn_mar2026", pd.Timestamp("2026-03-10T00:00:00Z")),
            ("corn_may2026", pd.Timestamp("2026-03-10T00:00:00Z")),
        ],
        names=["contract_id", "trading_date"],
    )
    return pd.Series([101.5, 102.25], index=index, dtype="float64")


def _valid_daily_stats_frame(
    *,
    price_field: str = "settle",
    product_id: str = "corn",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trading_date": [
                pd.Timestamp("2026-03-10T00:00:00Z"),
                pd.Timestamp("2026-03-11T00:00:00Z"),
            ],
            "contract_id": ["corn_mar2026", "corn_mar2026"],
            "product_id": [product_id, product_id],
            price_field: [101.5, 103.25],
        }
    )


class DummyMXMBusinessCalendar:
    def __init__(
        self, calendar_id: str, label_to_session_id: dict[np.datetime64, int]
    ) -> None:
        self.calendar_id = calendar_id
        self._label_to_session_id = {
            np.datetime64(k, "D"): v for k, v in label_to_session_id.items()
        }

    def session_id_from_label(self, label: np.datetime64) -> int:
        key = np.datetime64(label, "D")
        if key not in self._label_to_session_id:
            raise ValueError(
                f"label {key} is not present in calendar {self.calendar_id!r}"
            )
        return self._label_to_session_id[key]


def _valid_daily_mark_series() -> pd.Series:
    index = pd.MultiIndex.from_tuples(
        [
            ("corn_mar2026", 10),
            ("corn_may2026", 10),
        ],
        names=["contract_id", "session_id"],
    )
    return pd.Series([101.5, 102.25], index=index, dtype="float64")


def _valid_daily_mark_frame(
    *,
    product_id: str = "corn",
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_id": [10, 11],
            "contract_id": ["corn_mar2026", "corn_mar2026"],
            "product_id": [product_id, product_id],
            "mark_px": [101.5, 103.25],
            "is_markable": [True, True],
        }
    )


def test_product_price_lookup_accepts_valid_multiindex_series() -> None:
    prices = _valid_price_series()

    lookup = _ProductDailyStatsPriceLookup(
        product_id="corn",
        price_field="settle",
        prices=prices,
    )

    assert lookup.product_id == "corn"
    assert lookup.price_field == "settle"


def test_product_price_lookup_rejects_non_multiindex_series() -> None:
    prices = pd.Series(
        [101.5, 102.25],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="float64",
    )

    with pytest.raises(ValueError, match="must have a MultiIndex"):
        _ProductDailyStatsPriceLookup(
            product_id="corn",
            price_field="settle",
            prices=prices,
        )


def test_product_price_lookup_rejects_wrong_index_names() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            ("corn_mar2026", pd.Timestamp("2026-03-10T00:00:00Z")),
        ],
        names=["bad_contract", "bad_day"],
    )
    prices = pd.Series([101.5], index=index, dtype="float64")

    with pytest.raises(ValueError, match="index names must be"):
        _ProductDailyStatsPriceLookup(
            product_id="corn",
            price_field="settle",
            prices=prices,
        )


def test_product_price_lookup_rejects_duplicate_keys() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            ("corn_mar2026", pd.Timestamp("2026-03-10T00:00:00Z")),
            ("corn_mar2026", pd.Timestamp("2026-03-10T00:00:00Z")),
        ],
        names=["contract_id", "trading_date"],
    )
    prices = pd.Series([101.5, 101.5], index=index, dtype="float64")

    with pytest.raises(ValueError, match="must not contain duplicate"):
        _ProductDailyStatsPriceLookup(
            product_id="corn",
            price_field="settle",
            prices=prices,
        )


def test_product_price_lookup_rejects_missing_values() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            ("corn_mar2026", pd.Timestamp("2026-03-10T00:00:00Z")),
        ],
        names=["contract_id", "trading_date"],
    )
    prices = pd.Series([None], index=index, dtype="float64")

    with pytest.raises(ValueError, match="must not contain missing values"):
        _ProductDailyStatsPriceLookup(
            product_id="corn",
            price_field="settle",
            prices=prices,
        )


def test_product_price_lookup_rejects_non_numeric_values() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            ("corn_mar2026", pd.Timestamp("2026-03-10T00:00:00Z")),
        ],
        names=["contract_id", "trading_date"],
    )
    prices = pd.Series(["bad"], index=index, dtype="object")

    with pytest.raises(TypeError, match="must contain numeric values"):
        _ProductDailyStatsPriceLookup(
            product_id="corn",
            price_field="settle",
            prices=prices,
        )


def test_product_price_lookup_returns_price_for_existing_key() -> None:
    prices = _valid_price_series()
    lookup = _ProductDailyStatsPriceLookup(
        product_id="corn",
        price_field="settle",
        prices=prices,
    )

    result = lookup.get_price(
        contract_id="corn_mar2026",
        trading_date=pd.Timestamp("2026-03-10T00:00:00Z"),
    )

    assert result == 101.5


def test_product_price_lookup_raises_for_missing_key() -> None:
    prices = _valid_price_series()
    lookup = _ProductDailyStatsPriceLookup(
        product_id="corn",
        price_field="settle",
        prices=prices,
    )

    with pytest.raises(ValueError, match="Missing price"):
        lookup.get_price(
            contract_id="corn_mar2026",
            trading_date=pd.Timestamp("2026-03-11T00:00:00Z"),
        )


def test_daily_stats_accessor_returns_execution_price_for_valid_contract_and_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        assert product_id == "corn"
        return _valid_daily_stats_frame(price_field="settle", product_id="corn")

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    result = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=np.datetime64("2026-03-10"),
    )

    assert result == 101.5


def test_daily_stats_accessor_coerces_session_like_input_to_session_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return _valid_daily_stats_frame(price_field="settle", product_id=product_id)

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    result = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=pd.Timestamp("2026-03-10T23:59:59Z"),
    )

    assert result == 101.5


def test_daily_stats_accessor_uses_selected_price_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trading_date": [pd.Timestamp("2026-03-10T00:00:00Z")],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "settle": [101.5],
                "close": [102.75],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="close",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    result = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=np.datetime64("2026-03-10"),
    )

    assert result == 102.75


def test_daily_stats_accessor_loads_product_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        calls.append(product_id)
        return _valid_daily_stats_frame(price_field="settle", product_id=product_id)

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    first = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=np.datetime64("2026-03-10"),
    )
    second = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=np.datetime64("2026-03-11"),
    )

    assert first == 101.5
    assert second == 103.25
    assert calls == ["corn"]


def test_daily_stats_accessor_loads_different_products_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        calls.append(product_id)
        return pd.DataFrame(
            {
                "trading_date": [pd.Timestamp("2026-03-10T00:00:00Z")],
                "contract_id": [f"{product_id}_front"],
                "product_id": [product_id],
                "settle": [100.0 if product_id == "corn" else 200.0],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {
                "corn_front": DummyContract(product_id="corn"),
                "wheat_front": DummyContract(product_id="wheat"),
            }
        ),
    )

    corn_price = accessor.get_execution_price(
        contract_id="corn_front",
        session=np.datetime64("2026-03-10"),
    )
    wheat_price = accessor.get_execution_price(
        contract_id="wheat_front",
        session=np.datetime64("2026-03-10"),
    )

    assert corn_price == 100.0
    assert wheat_price == 200.0
    assert calls == ["corn", "wheat"]


def test_daily_stats_accessor_raises_for_unknown_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return _valid_daily_stats_frame(price_field="settle", product_id=product_id)

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI({}),
    )

    with pytest.raises(ValueError, match="Unknown contract_id"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_stats_accessor_raises_for_empty_daily_stats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame()

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="No daily_stats rows available"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_stats_accessor_raises_for_missing_required_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trading_date": [pd.Timestamp("2026-03-10T00:00:00Z")],
                "product_id": [product_id],
                "settle": [101.5],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="missing required columns"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_stats_accessor_raises_for_missing_price_field_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trading_date": [pd.Timestamp("2026-03-10T00:00:00Z")],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "close": [101.5],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="missing required columns"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_stats_accessor_raises_for_null_contract_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trading_date": [pd.Timestamp("2026-03-10T00:00:00Z")],
                "contract_id": [None],
                "product_id": [product_id],
                "settle": [101.5],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="contains null contract_id"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_stats_accessor_raises_for_null_trading_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trading_date": [pd.NaT],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "settle": [101.5],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="contains null trading_date"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_stats_accessor_raises_when_price_field_has_no_non_null_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trading_date": [pd.Timestamp("2026-03-10T00:00:00Z")],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "settle": [None],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="has no non-null values"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_stats_accessor_filters_null_price_rows_and_uses_non_null_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trading_date": [
                    pd.Timestamp("2026-03-10T00:00:00Z"),
                    pd.Timestamp("2026-03-11T00:00:00Z"),
                ],
                "contract_id": ["corn_mar2026", "corn_mar2026"],
                "product_id": [product_id, product_id],
                "settle": [None, 103.25],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    result = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=np.datetime64("2026-03-11"),
    )

    assert result == 103.25


def test_daily_stats_accessor_raises_for_non_numeric_price_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trading_date": [pd.Timestamp("2026-03-10T00:00:00Z")],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "settle": ["bad"],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(TypeError, match="non-numeric values"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_stats_accessor_raises_for_non_tz_aware_trading_date(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "trading_date": [pd.Timestamp("2026-03-10")],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "settle": [101.5],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(TypeError, match="trading_date must be tz-aware"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_stats_accessor_raises_for_missing_contract_day_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_stats_product(
        *,
        product_id: str,
        root: object | None = None,
        start: object | None = None,
        end: object | None = None,
    ) -> pd.DataFrame:
        return _valid_daily_stats_frame(price_field="settle", product_id=product_id)

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_stats_product",
        fake_read_daily_stats_product,
    )

    accessor = DailyStatsExecutionPriceAccessor(
        price_field="settle",
        ref_data_api=DummyRefDataAPI(
            {"corn_may2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="Missing execution price"):
        accessor.get_execution_price(
            contract_id="corn_may2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_product_price_lookup_accepts_valid_multiindex_series() -> None:
    prices = _valid_daily_mark_series()

    lookup = _ProductDailyMarkPriceLookup(
        product_id="corn",
        calendar_id="mxm_corn_2026",
        prices=prices,
    )

    assert lookup.product_id == "corn"
    assert lookup.calendar_id == "mxm_corn_2026"


def test_daily_mark_product_price_lookup_returns_price_for_existing_key() -> None:
    prices = _valid_daily_mark_series()
    lookup = _ProductDailyMarkPriceLookup(
        product_id="corn",
        calendar_id="mxm_corn_2026",
        prices=prices,
    )

    result = lookup.get_price(contract_id="corn_mar2026", session_id=10)

    assert result == 101.5


def test_daily_mark_product_price_lookup_raises_for_missing_key() -> None:
    prices = _valid_daily_mark_series()
    lookup = _ProductDailyMarkPriceLookup(
        product_id="corn",
        calendar_id="mxm_corn_2026",
        prices=prices,
    )

    with pytest.raises(ValueError, match="Missing price"):
        lookup.get_price(contract_id="corn_mar2026", session_id=11)


def test_daily_mark_accessor_returns_execution_price_for_valid_contract_and_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        assert calendar_id == "mxm_corn_2026"
        assert product_id == "corn"
        return _valid_daily_mark_frame(product_id="corn")

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {
                np.datetime64("2026-03-10"): 10,
                np.datetime64("2026-03-11"): 11,
            },
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    result = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=np.datetime64("2026-03-10"),
    )

    assert result == 101.5


def test_daily_mark_accessor_coerces_session_like_input_to_session_day(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return _valid_daily_mark_frame(product_id=product_id)

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {
                np.datetime64("2026-03-10"): 10,
                np.datetime64("2026-03-11"): 11,
            },
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    result = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=pd.Timestamp("2026-03-10T23:59:59Z"),
    )

    assert result == 101.5


def test_daily_mark_accessor_loads_product_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        calls.append(product_id)
        return _valid_daily_mark_frame(product_id=product_id)

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {
                np.datetime64("2026-03-10"): 10,
                np.datetime64("2026-03-11"): 11,
            },
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    first = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=np.datetime64("2026-03-10"),
    )
    second = accessor.get_execution_price(
        contract_id="corn_mar2026",
        session=np.datetime64("2026-03-11"),
    )

    assert first == 101.5
    assert second == 103.25
    assert calls == ["corn"]


def test_daily_mark_accessor_loads_different_products_separately(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        calls.append(product_id)
        return pd.DataFrame(
            {
                "session_id": [10],
                "contract_id": [f"{product_id}_front"],
                "product_id": [product_id],
                "mark_px": [100.0 if product_id == "corn" else 200.0],
                "is_markable": [True],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_crops_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI(
            {
                "corn_front": DummyContract(product_id="corn"),
                "wheat_front": DummyContract(product_id="wheat"),
            }
        ),
    )

    corn_price = accessor.get_execution_price(
        contract_id="corn_front",
        session=np.datetime64("2026-03-10"),
    )
    wheat_price = accessor.get_execution_price(
        contract_id="wheat_front",
        session=np.datetime64("2026-03-10"),
    )

    assert corn_price == 100.0
    assert wheat_price == 200.0
    assert calls == ["corn", "wheat"]


def test_daily_mark_accessor_raises_for_unknown_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return _valid_daily_mark_frame(product_id=product_id)

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI({}),
    )

    with pytest.raises(ValueError, match="Unknown contract_id"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_accessor_raises_for_empty_daily_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame()

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="No daily_mark rows available"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_accessor_raises_for_missing_required_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "session_id": [10],
                "product_id": [product_id],
                "mark_px": [101.5],
                "is_markable": [True],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="missing required columns"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_accessor_raises_for_null_contract_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "session_id": [10],
                "contract_id": [None],
                "product_id": [product_id],
                "mark_px": [101.5],
                "is_markable": [True],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="contains null contract_id"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_accessor_raises_for_null_session_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "session_id": [None],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "mark_px": [101.5],
                "is_markable": [True],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="contains null session_id"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_accessor_raises_when_no_markable_rows_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "session_id": [10],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "mark_px": [101.5],
                "is_markable": [False],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="has no markable rows"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_accessor_raises_for_null_mark_px_in_markable_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "session_id": [10],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "mark_px": [None],
                "is_markable": [True],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="contains null mark_px"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_accessor_raises_for_non_numeric_mark_px(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "session_id": [10],
                "contract_id": ["corn_mar2026"],
                "product_id": [product_id],
                "mark_px": ["bad"],
                "is_markable": [True],
            }
        )

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(TypeError, match="non-numeric values in mark_px"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_accessor_raises_when_session_label_not_in_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return _valid_daily_mark_frame(product_id=product_id)

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-11"): 11},
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_mar2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="is not present in calendar"):
        accessor.get_execution_price(
            contract_id="corn_mar2026",
            session=np.datetime64("2026-03-10"),
        )


def test_daily_mark_accessor_raises_for_missing_contract_session_price(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_read_daily_mark_product(
        *,
        calendar_id: str,
        product_id: str,
        root: object | None = None,
        start_session_id: int | None = None,
        end_session_id: int | None = None,
    ) -> pd.DataFrame:
        return _valid_daily_mark_frame(product_id=product_id)

    monkeypatch.setattr(
        "mxm.v1.execution.price_accessors.read_daily_mark_product",
        fake_read_daily_mark_product,
    )

    accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=DummyMXMBusinessCalendar(
            "mxm_corn_2026",
            {np.datetime64("2026-03-10"): 10},
        ),
        ref_data_api=DummyRefDataAPI(
            {"corn_may2026": DummyContract(product_id="corn")}
        ),
    )

    with pytest.raises(ValueError, match="Missing execution price"):
        accessor.get_execution_price(
            contract_id="corn_may2026",
            session=np.datetime64("2026-03-10"),
        )
