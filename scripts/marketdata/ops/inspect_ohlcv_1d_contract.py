from __future__ import annotations

import argparse
from pathlib import Path

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import OHLCV1DAttemptsStore
from mxm.v1.marketdata.inspect.ohlcv_1d.contracts import (
    get_contract_coverage_from_latest_attempt,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend


def main() -> int:
    p = argparse.ArgumentParser(
        description="MXM: inspect OHLC-1D contract coverage (read-only)"
    )
    p.add_argument("--root", default=None, help="MXM root directory (default: ~/.mxm)")
    p.add_argument(
        "--contract-key", required=True, help="e.g. cme_emini_snp500_futures:2010-06"
    )
    args = p.parse_args()

    root = Path(args.root) if args.root else (Path.home() / ".mxm")
    layout = MarketdataLayout(root=root)
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()

    attempts = OHLCV1DAttemptsStore(backend=backend)

    cov = get_contract_coverage_from_latest_attempt(
        attempts=attempts, contract_key=args.contract_key
    )
    if cov is None:
        print(f"[inspect] no attempts found for contract_key={args.contract_key!r}")
        return 1

    s = cov.surfaces
    w = cov.windows
    la = cov.last_attempt

    print(f"contract_key: {cov.contract_key}")
    print(
        f"dataset:      {cov.dataset} publisher_id={cov.publisher_id} instrument_id={cov.instrument_id} raw_symbol={cov.raw_symbol}"
    )
    print()
    print(
        f"last_attempt: ts={la.run_ts_utc} mode={la.mode} status={la.status} detail={la.status_detail}"
    )
    print(
        f"attempt:      is_empty={getattr(la, 'is_empty', None)} vendor_final={getattr(la, 'vendor_final', None)}"
    )
    if la.error_type or la.error_message:
        print(f"error:        {la.error_type}: {la.error_message}")
    print()
    print(
        f"interest:     [{s.interest.start.isoformat()} .. {s.interest.end.isoformat()})"
    )
    print(
        f"dataset_rng:  [{s.dataset.start.isoformat()} .. {s.dataset.end.isoformat()})"
    )
    if s.lifecycle is None:
        print("lifecycle:    (none)")
    else:
        print(
            f"lifecycle:    [{s.lifecycle.start.isoformat()} .. {s.lifecycle.end.isoformat()})"
        )
    if w.available is None:
        print("available:    (none / empty intersection)")
    else:
        print(
            f"available:    [{w.available.start.isoformat()} .. {w.available.end.isoformat()})"
        )
    print(
        f"expected:     [{w.expected.start.isoformat()} .. {w.expected.end.isoformat()}) days={w.expected.days}"
    )
    print()
    print(f"stored_rows:  {w.row_count}")
    if w.stored_observed is None:
        print("stored_obs:   (none)")
        print("stored_win:   (none)")
    else:
        print(
            f"stored_obs:   [{w.stored_observed.min_ts.isoformat()} .. {w.stored_observed.max_ts.isoformat()}]"
        )
        if w.stored_window is None:
            print("stored_win:   (none)")
        else:
            print(
                f"stored_win:   [{w.stored_window.start.isoformat()} .. {w.stored_window.end.isoformat()})"
            )
    print()
    print(f"complete:     {w.complete}")
    print(f"derived_vendor_final: {la.vendor_final}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
