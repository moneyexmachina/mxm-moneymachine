from __future__ import annotations

import argparse
from pathlib import Path

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import OHLCV1DAttemptsStore
from mxm.v1.marketdata.inspect.system import get_system_coverage_report
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend


def main() -> int:
    p = argparse.ArgumentParser(
        description="MXM V1: inspect system coverage (read-only)"
    )
    p.add_argument("--root", default=None, help="MXM root directory (default: ~/.mxm)")
    p.add_argument("--limit", type=int, default=200, help="max products to print")
    args = p.parse_args()

    root = Path(args.root) if args.root else (Path.home() / ".mxm")
    layout = MarketdataLayout(root=root)
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()

    attempts = OHLCV1DAttemptsStore(backend=backend)

    report = get_system_coverage_report(attempts=attempts)
    if not report.products:
        print("[inspect] no attempts recorded")
        return 0

    print(f"products: {len(report.products)}   contracts: {report.contracts_total}")
    print()
    print(
        "product_id | status | total | complete | incomplete | unmapped | cost_blocked | errors | last_run | mode"
    )

    for i, r in enumerate(report.products):
        if i >= args.limit:
            break
        last_run = r.last_run_ts_utc.isoformat() if r.last_run_ts_utc else ""
        mode = r.last_mode or ""
        print(
            f"{r.product_id} | {r.status} | {r.contracts_total} | {r.contracts_complete} | "
            f"{r.contracts_incomplete} | {r.contracts_unmapped} | {r.contracts_blocked_cost} | "
            f"{r.contracts_error} | {last_run} | {mode}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
