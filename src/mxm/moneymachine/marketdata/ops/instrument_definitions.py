from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import databento as db

from mxm.dataio.registry import list_registered, register
from mxm.moneymachine.marketdata.datasets.instrument_definitions.ingest import (
    InstrumentDefinitionsIngestReport,
    Mode,
    ingest_instrument_definitions,
)
from mxm.moneymachine.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout
from mxm.moneymachine.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.moneymachine.marketdata.vendors.databento.timeseries import (
    DatabentoTimeseriesFetcher,
)
from mxm.moneymachine.runtime.execution_context import ExecutionContext
from mxm.secrets import get_secret


@dataclass(frozen=True, slots=True)
class InstrumentDefinitionsRunRequest:
    product_id: str
    mode: Mode = "update"
    reset: bool = False
    cost_cap_usd: float = 1.0
    window_days: int = 31
    max_windows: int = 3
    overlap: str = "1d"
    end: str | None = None
    root: Path | None = None
    databento_api_key_secret_path: str = "mxm/dev/databento/api-key"


def run_instrument_definitions(
    *,
    request: InstrumentDefinitionsRunRequest,
    execution_context: ExecutionContext,
) -> InstrumentDefinitionsIngestReport:
    _ = execution_context

    api_key = get_secret(request.databento_api_key_secret_path)
    client = db.Historical(api_key)

    if "databento" not in list_registered():
        register("databento", DatabentoTimeseriesFetcher(client=client))
    layout = (
        MarketdataLayout.from_root(request.root)
        if request.root is not None
        else MarketdataLayout.from_default_root()
    )
    backend = SQLiteBackend(layout=layout)
    store = InstrumentDefinitionsStore(backend=backend)

    return ingest_instrument_definitions(
        store=store,
        product_id=request.product_id,
        client=client,
        mode=request.mode,
        cost_cap_usd=request.cost_cap_usd,
        window_days=request.window_days,
        overlap=request.overlap,
        max_windows=request.max_windows,
        reset=request.reset,
        end=request.end,
    )
