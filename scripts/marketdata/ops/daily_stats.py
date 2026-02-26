# scripts/marketdata/ops/daily_stats.py
from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from mxm.v1.marketdata.datasets.daily_stats.store import DailyStatsStore
from mxm.v1.marketdata.datasets.statistics_1d.store import Statistics1DStore
from mxm.v1.marketdata.orchestrators.daily_stats import derive_daily_stats_for_product
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
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
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    return {"__repr__": repr(obj)}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="daily_stats",
        description="Operational orchestrator for derived daily_stats (per product_id).",
    )
    p.add_argument("--product-id", required=True)
    p.add_argument(
        "--mode",
        choices=["bootstrap", "update"],
        default="update",
        help="bootstrap: attempt full contract lifecycle windows; update: only recent/live contracts (conservative).",
    )

    # Optional run scoping
    p.add_argument("--max-contracts", type=int, default=None)

    # Optional dataset-range override (mostly for offline/testing)
    p.add_argument(
        "--dataset-range-start",
        type=str,
        default=None,
        help="Optional ISO timestamp string for dataset-range start (passed through to orchestrator).",
    )
    p.add_argument(
        "--dataset-range-end",
        type=str,
        default=None,
        help="Optional ISO timestamp string for dataset-range end (passed through to orchestrator).",
    )

    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not write daily_stats parquet/meta; report what would be built/skipped.",
    )
    p.add_argument(
        "--reset-local",
        action="store_true",
        help="Delete local daily_stats parquet+meta for identities touched before rebuilding.",
    )

    # Keep this knob because your wrapper currently prints it and you likely want it;
    # it is NOT consumed by derive_daily_stats_for_product per the signature you pasted.
    p.add_argument(
        "--require-source-meta",
        action="store_true",
        help="(Currently unused by derive_daily_stats_for_product) Fail if statistics_1d meta missing.",
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

    stats_store = Statistics1DStore(layout=layout)
    daily_store = DailyStatsStore(layout=layout)

    print("\nMXM V1 — ops: daily_stats")
    print(f"[run] ts_utc={now_iso}")
    print(f"[args] product_id={args.product_id}")
    print(f"[args] mode={args.mode}")
    print(f"[args] max_contracts={args.max_contracts}")
    print(f"[args] dataset_range_start={args.dataset_range_start}")
    print(f"[args] dataset_range_end={args.dataset_range_end}")
    print(f"[args] dry_run={bool(args.dry_run)}")
    print(f"[args] reset_local={bool(args.reset_local)}")
    print(f"[args] require_source_meta={bool(args.require_source_meta)}")
    print(f"[args] root={root}")
    print(f"[db]   sqlite={layout.sqlite_db_path()}")

    report = derive_daily_stats_for_product(
        backend=backend,
        product_id=args.product_id,
        mode=args.mode,
        stats_store=stats_store,
        daily_store=daily_store,
        dataset_range_start=args.dataset_range_start,
        dataset_range_end=args.dataset_range_end,
        # session_date_of left as orchestrator default (_default_session_date_of)
        max_contracts=(None if args.max_contracts is None else int(args.max_contracts)),
        dry_run=bool(args.dry_run),
        reset_local=bool(args.reset_local),
        require_source_meta=bool(args.require_source_meta),
    )

    payload = {
        "ts_utc": now_iso,
        "args": vars(args),
        "report": _to_jsonable(report),
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
