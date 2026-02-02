from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import OHLCV1DAttemptsStore
from mxm.v1.marketdata.inspect.product import get_product_coverage_report
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend


def main() -> int:
    p = argparse.ArgumentParser(
        description="MXM V1: inspect product coverage (read-only)"
    )
    p.add_argument("--root", default=None, help="MXM root directory (default: ~/.mxm)")
    p.add_argument("--product-id", required=True, help="e.g. cme_emini_snp500_futures")
    p.add_argument(
        "--show-incomplete", action="store_true", help="print incomplete contract keys"
    )
    p.add_argument(
        "--limit", type=int, default=50, help="limit for printed contract keys"
    )
    args = p.parse_args()

    root = Path(args.root) if args.root else (Path.home() / ".mxm")
    layout = MarketdataLayout(root=root)
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()

    attempts = OHLCV1DAttemptsStore(backend=backend)

    report = get_product_coverage_report(attempts=attempts, product_id=args.product_id)
    s = report.summary

    status_counts = Counter([c.last_attempt.status for c in report.contracts])
    print()
    print("status_counts:")
    for k in sorted(status_counts.keys()):
        print(f"  {k}: {status_counts[k]}")
    print(f"product_id:   {s.product_id}")
    print(f"status:       {s.status} ({s.status_reason})")
    print(
        f"last_run:     {s.last_run_ts_utc if s.last_run_ts_utc else None} mode={s.last_mode}"
    )
    print()
    print(
        f"contracts:    total={s.contracts_total} complete={s.contracts_complete} incomplete={s.contracts_incomplete}"
    )
    print(
        f"breakdown:    empty_expected={s.contracts_empty_expected} vendor_final={s.contracts_vendor_final} unmapped={s.contracts_unmapped} cost_blocked={s.contracts_blocked_cost} errors={s.contracts_error}"
    )

    if args.show_incomplete:
        keys = list(s.incomplete_contract_keys)[: args.limit]
        print()
        print(
            f"incomplete_keys (first {len(keys)} of {len(s.incomplete_contract_keys)}):"
        )
        for k in keys:
            print(f"  - {k}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
