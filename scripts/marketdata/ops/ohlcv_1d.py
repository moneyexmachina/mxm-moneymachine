from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import databento as db
from mxm_secrets import get_secret

from mxm.dataio.registry import list_registered, register
from mxm.v1.marketdata.datasets.ohlcv_1d.store import OHLCV1DStore
from mxm.v1.marketdata.orchestrators.ohlcv_1d import ingest_ohlcv_1d_for_product
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
        prog="ohlcv_1d",
        description="Operational orchestrator for ohlcv-1d (per product_id).",
    )
    p.add_argument("--product-id", required=True)
    p.add_argument(
        "--mode",
        choices=["bootstrap", "update"],
        default="update",
        help="bootstrap: attempt full contract lifecycle windows; update: only recent/live contracts (conservative).",
    )
    p.add_argument("--cost-cap-usd", type=float, required=True)
    p.add_argument("--max-contracts", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--reset-local",
        action="store_true",
        help="Delete local parquet for identities touched (identity-scoped) before ingesting.",
    )
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

    store = OHLCV1DStore(layout=layout)

    print("\nMXM V1 — ops: ohlcv_1d")
    print(f"[run] ts_utc={now_iso}")
    print(f"[args] product_id={args.product_id}")
    print(f"[args] mode={args.mode}")
    print(f"[args] cost_cap_usd={args.cost_cap_usd}")
    print(f"[args] dry_run={bool(args.dry_run)}")
    print(f"[args] reset_local={bool(args.reset_local)}")
    print(f"[args] root={root}")
    print(f"[db]   sqlite={layout.sqlite_db_path()}")

    report = ingest_ohlcv_1d_for_product(
        backend=backend,
        store=store,
        product_id=args.product_id,
        mode=args.mode,
        cost_cap_usd=float(args.cost_cap_usd),
        client=client,
        max_contracts=(None if args.max_contracts is None else int(args.max_contracts)),
        dry_run=bool(args.dry_run),
        reset_local=bool(args.reset_local),
    )

    payload = {
        "ts_utc": now_iso,
        "args": vars(args),
        "report": _to_jsonable(report),
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
