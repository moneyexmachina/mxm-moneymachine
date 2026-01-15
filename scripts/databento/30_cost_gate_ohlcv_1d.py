"""
Proof 3 — Cost gate (metadata.get_cost) for daily OHLCV request.

Goal:
- Compute the expected $ cost for pulling ohlcv-1d bars for one (or a few) candidate symbols
  over a short date window.
- Do not pull data.
- Produce output that can be pasted into docs/week1/databento_notes.md.

Notes:
- This uses metadata.get_cost, not timeseries.get_range.
- If a symbol is invalid/unresolvable, Databento may raise an error; we log and continue.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import databento as db
from mxm_secrets import get_secret

API_KEY_SECRET = "mxm/dev/databento/api-key"

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1d"
STYPE_IN = "raw_symbol"

# Candidate outright contract symbols (edit this list manually for now).
# We are intentionally skipping automated discovery (Proof 2).
CANDIDATE_SYMBOLS = [
    "ESZ5",
    "ESH6",
    "CLG6",
    "CLH6",
]

# Cost-gate window (keep it tiny).
# We also clamp to the entitled dataset end date automatically.
WINDOW_DAYS = 10


@dataclass(frozen=True)
class CostRequest:
    dataset: str
    schema: str
    stype_in: str
    symbol: str
    start: date
    end: date


def _parse_iso_date(s: str) -> date:
    # e.g. '2026-01-13T03:58:33.117285000Z'
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def main() -> int:
    api_key = get_secret(API_KEY_SECRET)
    client = db.Historical(api_key)

    # Clamp the request window to the entitled dataset range.
    ds_range = client.metadata.get_dataset_range(DATASET)
    ds_end_date = _parse_iso_date(ds_range["end"])

    # For daily bars, your entitlement shows ohlcv-1d end at 2026-01-13T00:00:00Z.
    # Using ds_end_date as the max date boundary is conservative and avoids 422 errors.
    end = ds_end_date
    start = end - timedelta(days=WINDOW_DAYS)

    requests: list[CostRequest] = [
        CostRequest(DATASET, SCHEMA, STYPE_IN, sym, start, end)
        for sym in CANDIDATE_SYMBOLS
    ]

    results = []

    for req in requests:
        try:
            cost = client.metadata.get_cost(
                dataset=req.dataset,
                start=req.start,
                end=req.end,
                symbols=req.symbol,
                schema=req.schema,
                stype_in=req.stype_in,
            )
            results.append(
                {
                    "symbol": req.symbol,
                    "start": str(req.start),
                    "end": str(req.end),
                    "schema": req.schema,
                    "stype_in": req.stype_in,
                    "cost_usd": cost,
                    "status": "ok",
                }
            )
        except Exception as e:
            results.append(
                {
                    "symbol": req.symbol,
                    "start": str(req.start),
                    "end": str(req.end),
                    "schema": req.schema,
                    "stype_in": req.stype_in,
                    "cost_usd": None,
                    "status": "error",
                    "error": str(e),
                }
            )

    # Print a stable, pasteable block
    print("=" * 80)
    print("MXM V1 — Databento Proof 3: Cost gate for ohlcv-1d")
    print("=" * 80)
    print(f"Dataset: {DATASET}")
    print(f"Schema:  {SCHEMA}")
    print(f"Window:  {start} -> {end}  (clamped to entitlement end)")
    print(f"Symbols: {CANDIDATE_SYMBOLS}")
    print("-" * 80)
    print(json.dumps(results, indent=2, sort_keys=True))
    print("=" * 80)

    # Return non-zero if all failed
    ok_count = sum(1 for r in results if r["status"] == "ok")
    return 0 if ok_count > 0 else 3


if __name__ == "__main__":
    raise SystemExit(main())
