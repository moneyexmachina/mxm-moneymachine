# scripts/marketdata/ops/marketdata_inspect.py
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mxm.v1.marketdata.inspect.dispatch import get_routes
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend


def _build_backend(root: Path) -> SQLiteBackend:
    layout = MarketdataLayout(root=root)
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()
    return backend


def _build_attempts_store(dataset: str, backend: SQLiteBackend) -> Any:
    if dataset == "ohlcv_1d":
        from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import (
            OHLCV1DAttemptsStore,
        )

        return OHLCV1DAttemptsStore(backend=backend)
    if dataset == "statistics_1d":
        from mxm.v1.marketdata.datasets.statistics_1d.attempts_store import (
            Statistics1DAttemptsStore,
        )

        return Statistics1DAttemptsStore(backend=backend)
    raise ValueError(f"unknown dataset={dataset!r} for attempts store")


def _build_data_store(dataset: str, root: Path) -> Any:
    # Prefer constructing stores from layout/root directly (no sqlite).
    # Adjust to your actual store constructor(s).
    if dataset == "statistics_1d":
        from mxm.v1.marketdata.datasets.statistics_1d.store import (
            Statistics1DStore,  # adjust import
        )

        layout = MarketdataLayout(root=root)
        return Statistics1DStore(layout=layout)
    raise ValueError(f"no data store defined for dataset={dataset!r}")


def _as_jsonable(obj: Any) -> Any:
    # Dataclasses -> dict, enums -> value, timestamps -> isoformat, etc.
    # Keep minimal: callers can request --json for structured output.
    try:
        from dataclasses import asdict, is_dataclass

        if is_dataclass(obj):
            return asdict(obj)
    except Exception:
        pass
    # fallback: best-effort
    if hasattr(obj, "to_dict"):
        return obj.to_dict()
    return obj


def main() -> int:
    routes = get_routes()

    p = argparse.ArgumentParser(description="MXM: inspect marketdata (read-only)")
    p.add_argument("--root", default=None, help="MXM root directory (default: ~/.mxm)")
    p.add_argument(
        "--json", action="store_true", help="emit JSON instead of human summary"
    )

    sub = p.add_subparsers(dest="dataset", required=True)

    # ohlcv_1d
    p_ohlcv = sub.add_parser("ohlcv_1d")
    sub_ohlcv = p_ohlcv.add_subparsers(dest="level", required=True)

    c = sub_ohlcv.add_parser("contract")
    c.add_argument("--contract-key", required=True)

    pr = sub_ohlcv.add_parser("product")
    pr.add_argument("--product-id", required=True)

    sub_ohlcv.add_parser("system")

    # statistics_1d
    p_stats = sub.add_parser("statistics_1d")
    sub_stats = p_stats.add_subparsers(dest="level", required=True)

    c = sub_stats.add_parser("contract")
    c.add_argument("--contract-key", required=True)

    pr = sub_stats.add_parser("product")
    pr.add_argument("--product-id", required=True)

    sub_stats.add_parser("system")

    ins = sub_stats.add_parser("instrument")
    ins.add_argument("--publisher-id", type=int, required=True)
    ins.add_argument("--instrument-id", type=int, required=True)
    ins.add_argument(
        "--vendor-dataset",
        dest="vendor_dataset",
        default=None,
        help="vendor dataset name (e.g. GLBX.MDP3) used in parquet partitioning",
    )
    ins.add_argument("--start", default=None)
    ins.add_argument("--end", default=None)
    ins.add_argument("--sample-n", type=int, default=5)

    args = p.parse_args()

    root = Path(args.root) if args.root else (Path.home() / ".mxm")

    # argparse naming collision: args.dataset is the chosen subparser name.
    dataset_key = args.dataset  # subparser
    level = args.level

    route = routes.get((dataset_key, level))
    if route is None:
        raise RuntimeError(
            f"no dispatch route for dataset={dataset_key!r} level={level!r}"
        )

    backend = _build_backend(root=root)

    if route.store_kind == "attempts":
        store = _build_attempts_store(dataset_key, backend=backend)
        if level == "contract":
            result = route.fn(attempts=store, contract_key=args.contract_key)
        elif level == "product":
            result = route.fn(attempts=store, product_id=args.product_id)
        elif level == "system":
            result = route.fn(attempts=store)
        else:
            raise RuntimeError(f"unexpected level={level!r} for attempts store")
    else:
        store = _build_data_store(dataset_key, root=root)
        # only stats instrument currently
        result = route.fn(
            store=store,
            dataset=args.vendor_dataset,
            publisher_id=args.publisher_id,
            instrument_id=args.instrument_id,
            start=args.start,
            end=args.end,
            sample_n=args.sample_n,
        )

    if result is None:
        print("[inspect] no result (e.g. no attempts found)")
        return 1

    if args.json:
        print(json.dumps(_as_jsonable(result), indent=2, default=str))
        return 0

    # Human summaries (minimal; you can add richer format per dataset/level later)
    print(f"[inspect] dataset={dataset_key} level={level}")
    print(json.dumps(_as_jsonable(result), indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
