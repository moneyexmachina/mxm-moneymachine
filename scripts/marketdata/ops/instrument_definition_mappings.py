#!/usr/bin/env python3
"""
MXM V1 — Operational: instrument_definition_mappings (per product_id)

Purpose:
- Build / update the derived dataset instrument_definition_mappings for one product_id.
- This orchestrator is vendor-call-free and will NOT ingest instrument_definitions.
  It gates on upstream readiness and fails fast if definitions are not sufficient.

Example:
  poetry run python scripts/marketdata/ops/instrument_definition_mappings.py \
    --product-id cme_emini_snp500_futures \
    --mode bootstrap \
    --reset

Notes:
- Run scripts/marketdata/ops/instrument_definitions.py first (bootstrap/update)
  to populate instrument_definition_events/current/watermarks.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from mxm.moneymachine.marketdata.datasets.instrument_definition_mappings.build import (
    rebuild_instrument_definition_mappings,
)
from mxm.moneymachine.marketdata.datasets.instrument_definition_mappings.store import (
    InstrumentDefinitionMappingsStore,
)
from mxm.moneymachine.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout
from mxm.moneymachine.marketdata.stores.sqlite.backend import SQLiteBackend
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
        prog="instrument_definition_mappings",
        description="Operational orchestrator for instrument_definition_mappings (per product_id).",
    )
    p.add_argument("--product-id", required=True)
    p.add_argument(
        "--mode",
        choices=["bootstrap", "update"],
        default="update",
        help="bootstrap: first-time build (often after reset); update: safe rerun / incremental append-only.",
    )
    p.add_argument(
        "--reset",
        action="store_true",
        help="Delete product-scoped mapping rows before rebuilding.",
    )
    p.add_argument(
        "--root",
        type=str,
        default=None,
        help="Marketdata root directory (default: ~/.mxm).",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    root = Path(args.root).expanduser() if args.root else (Path.home() / ".mxm")
    now_iso = utc_now_run_ts()
    # ---- SQLite store wiring ----
    layout = MarketdataLayout(root=root)
    backend = SQLiteBackend(layout=layout)

    defs_store = InstrumentDefinitionsStore(backend=backend)
    mappings_store = InstrumentDefinitionMappingsStore(backend=backend)

    print("\nMXM V1 — ops: instrument_definition_mappings")
    print(f"[run] ts_utc={now_iso}")
    print(f"[args] product_id={args.product_id}")
    print(f"[args] mode={args.mode}")
    print(f"[args] reset={bool(args.reset)}")
    print(f"[args] root={root!s}")
    print(f"[db]   sqlite={backend.db_path()}")

    report = rebuild_instrument_definition_mappings(
        defs_store=defs_store,
        mappings_store=mappings_store,
        product_id=args.product_id,
        mode=args.mode,
        reset=bool(args.reset),
    )

    payload = {
        "ts_utc": now_iso,
        "args": vars(args),
        "report": _to_jsonable(report),
    }
    print(json.dumps(payload, indent=2, sort_keys=False))


if __name__ == "__main__":
    main()
