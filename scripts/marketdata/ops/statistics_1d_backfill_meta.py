# scripts/marketdata/ops/statistics_1d_backfill_meta.py
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.parquet.statistics_1d import (
    ensure_statistics_1d_meta,
    read_statistics_1d_meta,
)


@dataclass
class Counters:
    scanned: int = 0
    created: int = 0
    ok: int = 0
    errors: int = 0


def _parse_identity_from_path(p: Path) -> tuple[str, int, int]:
    # .../by_instrument/dataset=GLBX.MDP3/publisher_id=1/instrument_id=4916/statistics.parquet
    parts = list(p.parts)
    ds = next(x for x in parts if x.startswith("dataset=")).split("=", 1)[1]
    pub = int(next(x for x in parts if x.startswith("publisher_id=")).split("=", 1)[1])
    inst = int(
        next(x for x in parts if x.startswith("instrument_id=")).split("=", 1)[1]
    )
    return ds, pub, inst


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="MXM root (layout.root)")
    ap.add_argument("--vendor", default="databento")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument(
        "--dataset", default=None, help="optional dataset filter (e.g. GLBX.MDP3)"
    )
    args = ap.parse_args()

    layout = MarketdataLayout(root=Path(args.root))

    base = layout.root / "marketdata" / args.vendor / "statistics" / "by_instrument"

    files = sorted(base.rglob("statistics.parquet"))
    if args.dataset:
        files = [p for p in files if f"dataset={args.dataset}" in p.parts]
    if args.limit is not None:
        files = files[: int(args.limit)]

    c = Counters()

    for p in files:
        c.scanned += 1
        try:
            dataset, publisher_id, instrument_id = _parse_identity_from_path(p)

            if args.dry_run:
                meta = read_statistics_1d_meta(
                    layout=layout,
                    dataset=dataset,
                    publisher_id=publisher_id,
                    instrument_id=instrument_id,
                )
                if meta is None:
                    c.created += 1
                    print(
                        f"[dry-run] would create meta: {dataset} {publisher_id} {instrument_id}"
                    )
                else:
                    c.ok += 1
                continue

            changed = ensure_statistics_1d_meta(
                layout=layout,
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
                force=bool(args.force),
            )
            if changed:
                c.created += 1
                print(
                    f"[write] meta created/updated: {dataset} {publisher_id} {instrument_id}"
                )
            else:
                c.ok += 1

        except Exception as e:
            c.errors += 1
            print(f"[error] {p}: {type(e).__name__}: {e}")

    print(
        f"scanned={c.scanned} created_or_updated={c.created} ok={c.ok} errors={c.errors}"
    )
    return 1 if c.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
