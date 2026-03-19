from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import databento as db
from mxm.dataio.registry import list_registered, register
from mxm_secrets import get_secret

from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.orchestrators.instrument_definitions import (
    ingest_instrument_definitions,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.marketdata.vendors.databento.timeseries import DatabentoTimeseriesFetcher
from mxm.v1.utils.time_utils import utc_now_run_ts


def _to_jsonable(obj: Any) -> Any:
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    return {"__repr__": repr(obj)}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="instrument_definitions",
        description="Operational orchestrator for instrument definitions (per product_id).",
    )
    p.add_argument("--product-id", required=True)
    p.add_argument(
        "--mode",
        choices=["bootstrap", "update"],
        default="update",
        help="bootstrap: forward fill from default start (if watermark absent); update: from watermark to now.",
    )
    p.add_argument(
        "--reset", action="store_true", help="Delete feed-scoped state and start fresh."
    )
    p.add_argument("--cost-cap-usd", type=float, required=True)
    p.add_argument("--window-days", type=int, default=31)
    p.add_argument("--max-windows", type=int, default=3)
    p.add_argument("--overlap", type=str, default="1d")
    p.add_argument(
        "--end", type=str, default=None, help="ISO8601Z end time; default is now."
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    # ---- Databento client ----
    api_key = get_secret("mxm/dev/databento/api-key")
    client = db.Historical(api_key)

    # ---- Register DataIO adapter once ----
    if "databento" not in list_registered():
        register("databento", DatabentoTimeseriesFetcher(client=client))
    print("[dataio] registered adapter 'databento'")

    # ---- SQLite store wiring ----
    layout = MarketdataLayout(root=Path.home() / ".mxm")
    backend = SQLiteBackend(layout=layout)
    store = InstrumentDefinitionsStore(backend=backend)

    report = ingest_instrument_definitions(
        store=store,
        product_id=args.product_id,
        client=client,
        mode=args.mode,
        cost_cap_usd=float(args.cost_cap_usd),
        window_days=int(args.window_days),
        overlap=str(args.overlap),
        max_windows=int(args.max_windows),
        reset=bool(args.reset),
        end=args.end,
    )

    payload = {
        "ts_utc": utc_now_run_ts(),
        "args": vars(args),
        "report": _to_jsonable(report),
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
