from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import databento as db
from mxm_secrets import get_secret

from mxm.dataio.registry import list_registered, register
from mxm.v1.marketdata.datasets.daily_stats.store import DailyStatsStore
from mxm.v1.marketdata.datasets.instrument_definition_mappings.store import (
    InstrumentDefinitionMappingsStore,
)
from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.store import OHLCV1DStore
from mxm.v1.marketdata.datasets.statistics_1d.store import Statistics1DStore
from mxm.v1.marketdata.orchestrators.product_marketdata import (
    ProductMarketDataStores,
    ingest_product_marketdata,
)
from mxm.v1.marketdata.orchestrators.product_marketdata_attempts_store import (
    ProductMarketdataAttemptsStore,
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
        prog="product_marketdata",
        description="Product-level marketdata meta-orchestrator (definitions -> mappings -> ohlcv_1d).",
    )
    p.add_argument("--product-id", required=True)
    p.add_argument(
        "--mode",
        choices=["bootstrap", "update"],
        default="update",
        help="bootstrap: first-time/full run; update: incremental run.",
    )
    p.add_argument("--cost-cap-usd", type=float, required=True)

    # Scope controls (passed through; per-stage support varies)
    p.add_argument("--max-contracts", type=int, default=None)
    p.add_argument("--max-windows", type=int, default=None)

    # Flags
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--reset", action="store_true")
    p.add_argument(
        "--force-reset",
        action="store_true",
        help="Delete local parquet+meta for identities touched before rebuilding.",
    )

    # Storage root
    p.add_argument("--root", type=str, default=None)
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    now_iso = utc_now_run_ts()
    root = Path(args.root) if args.root else (Path.home() / ".mxm")
    layout = MarketdataLayout(root=root)
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()

    # ---- Databento client ----
    api_key = get_secret("mxm/dev/databento/api-key")
    client = db.Historical(api_key)

    # ---- Register DataIO adapter once ----
    if "databento" not in list_registered():
        register("databento", DatabentoTimeseriesFetcher(client=client))
    print("[dataio] registered adapter 'databento'")

    # ---- Stores ----
    defs_store = InstrumentDefinitionsStore(backend=backend)
    idmap_store = InstrumentDefinitionMappingsStore(backend=backend)
    ohlcv_store = OHLCV1DStore(layout=layout)
    product_attempts = ProductMarketdataAttemptsStore(backend=backend)
    stats_store = Statistics1DStore(layout=layout)
    daily_stats_store = DailyStatsStore(layout=layout)
    stores = ProductMarketDataStores(
        backend=backend,
        product_attempts=product_attempts,
        instrument_definitions_store=defs_store,
        instrument_definition_mappings_store=idmap_store,
        ohlcv_1d_store=ohlcv_store,
        statistics_1d_store=stats_store,
        daily_stats_store=daily_stats_store,
    )

    print("\nMXM V1 — ops: product_marketdata")
    print(f"[run] ts_utc={now_iso}")
    print(f"[args] product_id={args.product_id}")
    print(f"[args] mode={args.mode}")
    print(f"[args] cost_cap_usd={args.cost_cap_usd}")
    print(f"[args] max_contracts={args.max_contracts}")
    print(f"[args] max_windows={args.max_windows}")
    print(f"[args] dry_run={bool(args.dry_run)}")
    print(f"[args] reset={bool(args.reset)}")
    print(f"[args] force_reset={bool(args.force_reset)}")
    print(f"[args] root={root}")
    print(f"[db]   sqlite={layout.sqlite_db_path()}")

    report = ingest_product_marketdata(
        product_id=args.product_id,
        mode=args.mode,
        cost_cap_usd=float(args.cost_cap_usd),
        stores=stores,
        client=client,
        dry_run=bool(args.dry_run),
        reset=bool(args.reset),
        force_reset=bool(args.force_reset),
        max_windows=(None if args.max_windows is None else int(args.max_windows)),
        max_contracts=(None if args.max_contracts is None else int(args.max_contracts)),
        run_ts_utc=now_iso,
    )

    payload = {
        "ts_utc": now_iso,
        "args": vars(args),
        "report": _to_jsonable(report),
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
