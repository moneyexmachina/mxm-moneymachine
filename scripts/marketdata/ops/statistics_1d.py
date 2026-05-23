from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import databento as db
from mxm_secrets import get_secret

from mxm.dataio.registry import list_registered, register
from mxm.moneymachine.marketdata.datasets.statistics_1d.store import Statistics1DStore
from mxm.moneymachine.marketdata.orchestrators.statistics_1d import (
    ingest_statistics_1d_for_product,
)
from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout
from mxm.moneymachine.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.moneymachine.marketdata.vendors.databento.timeseries import (
    DatabentoTimeseriesFetcher,
)
from mxm.moneymachine.utils.time_utils import utc_now_run_ts


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
        prog="statistics_1d",
        description="Operational orchestrator for statistics-1d (per product_id).",
    )
    p.add_argument("--product-id", required=True)
    p.add_argument(
        "--mode",
        choices=["bootstrap", "update"],
        default="update",
        help="bootstrap: attempt full contract lifecycle windows; update: only recent/live contracts (conservative).",
    )
    p.add_argument(
        "--contract-id",
        action="append",
        default=None,
        help="Optional explicit contract_id to restrict ingest to. Repeatable.",
    )
    p.add_argument("--cost-cap-usd", type=float, required=True)
    p.add_argument("--max-contracts", type=int, default=None)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument(
        "--force-reset",
        action="store_true",
        help="Delete local statistics_1d parquet and bypass cache before ingesting (identity-scoped).",
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
    else:
        print("[dataio] adapter 'databento' already registered")

    store = Statistics1DStore(layout=layout)
    contract_ids: set[str] | None
    if args.contract_id is None:
        contract_ids = None
    else:
        contract_ids = set(args.contract_id)
    print("\nMXM V1 — ops: statistics_1d")
    print(f"[run] ts_utc={now_iso}")
    print(f"[args] product_id={args.product_id}")
    print(f"[args] mode={args.mode}")
    # Contract filter (explicit + visible)
    if getattr(args, "contract_id", None):
        print(f"[args] contract_ids={contract_ids}")
    else:
        print("[args] contract_ids=ALL")

    print(f"[args] cost_cap_usd={args.cost_cap_usd}")
    print(f"[args] dry_run={bool(args.dry_run)}")
    print(f"[args] force_reset={bool(args.force_reset)}")
    print(f"[args] root={root}")
    print(f"[db]   sqlite={layout.sqlite_db_path()}")

    report = ingest_statistics_1d_for_product(
        backend=backend,
        store=store,
        product_id=args.product_id,
        mode=args.mode,
        cost_cap_usd=float(args.cost_cap_usd),
        client=client,
        max_contracts=(None if args.max_contracts is None else int(args.max_contracts)),
        contract_ids=contract_ids,
        dry_run=bool(args.dry_run),
        force_reset=bool(args.force_reset),
    )

    payload = {
        "ts_utc": now_iso,
        "args": vars(args),
        "report": _to_jsonable(report),
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
