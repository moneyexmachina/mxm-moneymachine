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
    p.add_argument(
        "--contract-id",
        action="append",
        default=None,
        help="Optional explicit contract_id to restrict rebuild to. Repeatable.",
    )

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
        "--force-reset",
        action="store_true",
        help="Delete local daily_stats parquet+meta for identities touched before rebuilding.",
    )
    p.add_argument(
        "--allow-fallback-provenance",
        action="store_true",
        help=(
            "Allow daily_stats derivation even if statistics_1d meta is missing. "
            "In this mode, downstream source_content_sha256 will be null and strict provenance is not guaranteed."
        ),
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

    contract_ids: set[str] | None
    if args.contract_id is None:
        contract_ids = None
    else:
        contract_ids = set(args.contract_id)

    require_source_meta = not bool(args.allow_fallback_provenance)

    print("\nMXM V1 — ops: daily_stats")
    print(f"[run] ts_utc={now_iso}")
    print(f"[args] product_id={args.product_id}")
    print(f"[args] mode={args.mode}")
    print(f"[args] max_contracts={args.max_contracts}")
    print(f"[args] contract_ids={contract_ids if contract_ids is not None else 'ALL'}")
    print(f"[args] dataset_range_start={args.dataset_range_start}")
    print(f"[args] dataset_range_end={args.dataset_range_end}")
    print(f"[args] dry_run={bool(args.dry_run)}")
    print(f"[args] force_reset={bool(args.force_reset)}")
    print(f"[args] require_source_meta={require_source_meta}")
    print(f"[args] root={root}")
    print(f"[db]   sqlite={layout.sqlite_db_path()}")
    if args.allow_fallback_provenance:
        print("[warn] allow_fallback_provenance=True — strict provenance disabled")

    report = derive_daily_stats_for_product(
        backend=backend,
        product_id=args.product_id,
        mode=args.mode,
        stats_store=stats_store,
        daily_store=daily_store,
        dataset_range_start=args.dataset_range_start,
        dataset_range_end=args.dataset_range_end,
        max_contracts=(None if args.max_contracts is None else int(args.max_contracts)),
        contract_ids=contract_ids,
        dry_run=bool(args.dry_run),
        force_reset=bool(args.force_reset),
        require_source_meta=require_source_meta,
    )

    payload = {
        "ts_utc": now_iso,
        "args": vars(args),
        "report": _to_jsonable(report),
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
