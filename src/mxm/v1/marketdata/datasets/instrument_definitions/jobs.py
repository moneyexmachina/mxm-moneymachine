# mxm/v1/marketdata/datasets/instrument_definitions/jobs.py
#
# MXM V1 — Instrument definitions jobs.
#
# This module defines runtime-facing jobs for the `instrument_definitions` dataset.
#
# In the Session 35 architecture, a job is:
# - a named unit of work
# - executed in a single runtime
# - responsible for constructing the dependencies it needs
# - responsible for calling the underlying dataset operation
#
# This module therefore sits above:
# - `ingest.py`   → core dataset operation / domain logic
#
# and below:
# - CLI adapters  → user-facing command invocation
# - schedulers    → timed or event-driven execution
#
# Important:
# - This module does not parse CLI arguments.
# - This module does not implement cross-runtime orchestration.
# - This module does not own dataset semantics; it instantiates runtime dependencies
#   and invokes the canonical ingest function.

from __future__ import annotations

from pathlib import Path
from typing import Literal, cast

import databento as db
from mxm.dataio.registry import list_registered, register
from mxm_secrets import get_secret

from mxm.v1.marketdata.datasets.instrument_definitions.ingest import (
    InstrumentDefinitionsIngestReport,
    ingest_instrument_definitions,
)
from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.marketdata.types import InstrumentDefinitionsClient
from mxm.v1.marketdata.vendors.databento.timeseries import DatabentoTimeseriesFetcher

Mode = Literal["bootstrap", "update"]


def update_instrument_definitions_for_product(
    *,
    product_id: str,
    mode: Mode = "update",
    cost_cap_usd: float,
    window_days: int = 31,
    overlap: str = "1d",
    max_windows: int = 3,
    reset: bool = False,
    end: str | None = None,
    root: Path | None = None,
) -> InstrumentDefinitionsIngestReport:
    """
    Update instrument definitions for a single product.

    This job constructs the required runtime dependencies for the
    `instrument_definitions` dataset and then invokes the canonical ingest
    operation in `ingest.py`.

    Parameters
    ----------
    product_id:
        MXM product identifier, e.g. an ES-like product family.
    mode:
        Ingestion mode.
        - "bootstrap": fill from default start (or reset state) forward
        - "update": continue from watermark toward the requested end
    cost_cap_usd:
        Maximum permitted estimated vendor spend for this invocation.
    window_days:
        Size of each ingest window in days.
    overlap:
        Overlap applied when resuming from watermark.
    max_windows:
        Maximum number of windows to attempt in this invocation.
    reset:
        Whether to destructively reset feed-scoped stored state before ingest.
    end:
        Optional ISO8601Z end timestamp. If omitted, the ingest layer will use "now".
    root:
        Optional MXM storage root. Defaults to ``Path.home() / ".mxm"``.

    Returns
    -------
    InstrumentDefinitionsIngestReport
        Structured report returned by the underlying ingest operation.

    Notes
    -----
    This is a single-runtime atomic job. It is suitable for:
    - direct Python invocation
    - invocation via the unified MXM CLI
    - invocation by an external scheduler

    It is not responsible for:
    - CLI parsing
    - multi-job orchestration
    - scheduling policy
    """
    resolved_root = root if root is not None else (Path.home() / ".mxm")

    layout = MarketdataLayout(root=resolved_root)
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()

    store = InstrumentDefinitionsStore(backend=backend)

    api_key = get_secret("mxm/dev/databento/api-key")
    client = db.Historical(api_key)

    # Register DataIO adapter once per runtime if needed.
    if "databento" not in list_registered():
        register("databento", DatabentoTimeseriesFetcher(client=client))
    def_client = cast(InstrumentDefinitionsClient, client)
    return ingest_instrument_definitions(
        store=store,
        product_id=product_id,
        client=def_client,
        mode=mode,
        cost_cap_usd=float(cost_cap_usd),
        window_days=int(window_days),
        overlap=str(overlap),
        max_windows=int(max_windows),
        reset=bool(reset),
        end=end,
    )
