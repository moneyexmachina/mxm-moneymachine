#!/usr/bin/env python3
"""
MXM V1 — Proof 99
Product-level historical backfill orchestrator (ohlcv-1d) for one product_id.

This script must demonstrate:
1) deterministic definitions coverage ensure step
2) mapping rebuild + audit report
3) multi-contract ohlcv-1d ingest via instrument_id
4) canonical parquet persistence
5) rerun behavior: skips / unchanged, DataIO cache hits where applicable
6) final coverage report printed and interpretable

Run (example):
  poetry run python scripts/marketdata/99_backfill_product.py --product-id cme_emini_snp500_futures --cost-cap-usd 5.0

Notes:
- Backfill mode only.
- No batch download. Streaming timeseries ingestion only.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime
from typing import Any

# ---------------------------------------------------------------------------
# PATCHABLE IMPORTS
# ---------------------------------------------------------------------------
# Adjust these imports to match your repo's actual module structure.
#
# Expected orchestrator signature (proposed):
#   backfill_product_ohlcv_1d(
#       *, product_id: str, cost_cap_usd: float,
#       definition_lookback_years: int = 20,
#       dry_run: bool = False,
#   ) -> ProductBackfillReport
#
try:
    from mxm_marketdata.orchestrators.product_backfill import (
        backfill_product_ohlcv_1d,  # type: ignore
    )
except Exception as e:  # pragma: no cover
    raise ImportError(
        "Could not import orchestrator. Patch the import in scripts/marketdata/99_backfill_product.py.\n"
        f"Original error: {e}"
    )


# Optional: if you have a standard bootstrap function for logging/config/env.
# Comment out if not used.
def _bootstrap() -> None:
    """
    Lightweight, local bootstrap.
    Replace with your canonical bootstrap (logging, env banners, etc.) if desired.
    """
    # Example: ensure deterministic timestamps / timezone display if you have logs.
    os.environ.setdefault("TZ", "UTC")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _to_jsonable(obj: Any) -> Any:
    """
    Best-effort conversion for dataclasses / pydantic-like models / plain objects.
    Keeps the proof script robust as report structures evolve.
    """
    if obj is None:
        return None
    if is_dataclass(obj):
        return asdict(obj)
    if hasattr(obj, "model_dump"):  # pydantic v2
        return obj.model_dump()
    if hasattr(obj, "dict"):  # pydantic v1
        return obj.dict()
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, dict):
        return {k: _to_jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_to_jsonable(v) for v in obj]
    # Fallback: try repr
    return {"__repr__": repr(obj)}


def _print_report(report: Any, *, title: str) -> None:
    payload = {
        "title": title,
        "ts_utc": _utc_now_iso(),
        "report": _to_jsonable(report),
    }
    print("\n" + "=" * 88)
    print(title)
    print("=" * 88)
    print(json.dumps(payload, indent=2, sort_keys=False))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="99_backfill_product",
        description="MXM Proof 99: product-level historical backfill orchestrator (ohlcv-1d, streaming).",
    )
    p.add_argument(
        "--product-id",
        required=True,
        help="MXM product_id (e.g. cme_emini_snp500_futures).",
    )
    p.add_argument(
        "--cost-cap-usd",
        type=float,
        required=True,
        help="Hard cap on Databento cost for this run (USD).",
    )
    p.add_argument(
        "--definition-lookback-years",
        type=int,
        default=20,
        help="Bounded lookback for ensuring instrument definition coverage (default: 20).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not ingest bars; still performs mapping audit and completeness scans where possible.",
    )
    p.add_argument(
        "--no-rerun",
        action="store_true",
        help="Skip the second run. (Not recommended; Proof 99 expects rerun behavior.)",
    )
    return p.parse_args(argv)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    _bootstrap()

    print("\nMXM V1 — Proof 99: Product Backfill Orchestrator")
    print(f"[run] ts_utc={_utc_now_iso()}")
    print(f"[args] product_id={args.product_id}")
    print(f"[args] cost_cap_usd={args.cost_cap_usd}")
    print(f"[args] definition_lookback_years={args.definition_lookback_years}")
    print(f"[args] dry_run={bool(args.dry_run)}")

    # ---------------------------------------------------------------------
    # RUN 1 (cold)
    # ---------------------------------------------------------------------
    report1 = backfill_product_ohlcv_1d(
        product_id=args.product_id,
        cost_cap_usd=float(args.cost_cap_usd),
        definition_lookback_years=int(args.definition_lookback_years),
        dry_run=bool(args.dry_run),
    )
    _print_report(report1, title="RUN 1 — backfill_product_ohlcv_1d")

    # ---------------------------------------------------------------------
    # RUN 2 (warm) — proof of rerun safety and caching behavior
    # ---------------------------------------------------------------------
    if not args.no_rerun:
        print(
            "\n[rerun] starting second run to demonstrate idempotency / caching behavior..."
        )
        report2 = backfill_product_ohlcv_1d(
            product_id=args.product_id,
            cost_cap_usd=float(args.cost_cap_usd),
            definition_lookback_years=int(args.definition_lookback_years),
            dry_run=bool(args.dry_run),
        )
        _print_report(report2, title="RUN 2 — backfill_product_ohlcv_1d (rerun)")
    else:
        print(
            "\n[rerun] skipped (--no-rerun). Proof 99 normally expects a rerun demonstration."
        )

    print("\n[done] Proof 99 script completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
