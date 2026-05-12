# mxm/v1/marketdata/inspect/dispatch.py
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

DatasetName = Literal["ohlcv_1d", "statistics_1d"]
LevelName = Literal["contract", "product", "system", "instrument"]
StoreKind = Literal["attempts", "store"]  # store = parquet/data store


@dataclass(frozen=True)
class InspectRoute:
    dataset: DatasetName
    level: LevelName
    store_kind: StoreKind
    fn: Callable[..., Any]  # pure function returning a model/dict
    description: str


def get_routes() -> dict[tuple[str, str], InspectRoute]:
    # Import inside to avoid import cycles at module import time.
    from mxm.v1.marketdata.inspect.ohlcv_1d.contracts import (
        get_contract_coverage_from_latest_attempt,
    )
    from mxm.v1.marketdata.inspect.ohlcv_1d.product import (
        get_product_coverage_report,
    )
    from mxm.v1.marketdata.inspect.ohlcv_1d.system import (
        get_system_coverage_report,
    )
    from mxm.v1.marketdata.inspect.statistics_1d.contracts import (
        get_contract_attempt_from_latest_attempt,
    )
    from mxm.v1.marketdata.inspect.statistics_1d.instrument import (
        inspect_statistics_1d_instrument,
    )
    from mxm.v1.marketdata.inspect.statistics_1d.product import (
        get_product_attempts_report,
    )
    from mxm.v1.marketdata.inspect.statistics_1d.system import (
        get_system_attempts_report,
    )

    return {
        ("ohlcv_1d", "contract"): InspectRoute(
            dataset="ohlcv_1d",
            level="contract",
            store_kind="attempts",
            fn=get_contract_coverage_from_latest_attempt,
            description="Inspect OHLCV-1D contract coverage from latest attempt",
        ),
        ("ohlcv_1d", "product"): InspectRoute(
            dataset="ohlcv_1d",
            level="product",
            store_kind="attempts",
            fn=get_product_coverage_report,
            description="Inspect OHLCV-1D product coverage from latest attempts",
        ),
        ("ohlcv_1d", "system"): InspectRoute(
            dataset="ohlcv_1d",
            level="system",
            store_kind="attempts",
            fn=get_system_coverage_report,
            description="Inspect OHLCV-1D system coverage from latest attempts",
        ),
        ("statistics_1d", "contract"): InspectRoute(
            dataset="statistics_1d",
            level="contract",
            store_kind="attempts",
            fn=get_contract_attempt_from_latest_attempt,
            description="Inspect statistics_1d contract attempts from latest attempt",
        ),
        ("statistics_1d", "product"): InspectRoute(
            dataset="statistics_1d",
            level="product",
            store_kind="attempts",
            fn=get_product_attempts_report,
            description="Inspect statistics_1d product attempts from latest attempts",
        ),
        ("statistics_1d", "system"): InspectRoute(
            dataset="statistics_1d",
            level="system",
            store_kind="attempts",
            fn=get_system_attempts_report,
            description="Inspect statistics_1d system attempts rollup",
        ),
        ("statistics_1d", "instrument"): InspectRoute(
            dataset="statistics_1d",
            level="instrument",
            store_kind="store",
            fn=inspect_statistics_1d_instrument,
            description="Inspect statistics_1d event stream for one instrument (parquet read)",
        ),
    }
