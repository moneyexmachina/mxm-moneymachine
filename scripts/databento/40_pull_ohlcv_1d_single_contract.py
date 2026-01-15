"""
Proof 4 — Minimal daily OHLCV pull (one explicit contract)

Goal:
- Pull ~10 days of daily bars for a single, explicit futures contract (ESZ5)
  from GLBX.MDP3 using schema ohlcv-1d.
- Inspect returned dataframe shape, columns, dtypes, timestamp semantics,
  and identity fields.
- Keep the script small, deterministic, and paste-friendly for databento_notes.md.

Non-goals:
- No symbol discovery / refdata enumeration.
- No persistence or ingestion architecture.
- No backfills beyond the tiny sample window.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone

import databento as db
from mxm_secrets import get_secret

API_KEY_SECRET = "mxm/dev/databento/api-key"

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1d"
STYPE_IN = "raw_symbol"

SYMBOL = "ESH6"

# Use the same window that you cost-gated in Proof 3.
START_DATE = "2026-01-03"
END_DATE = "2026-01-13"  # exclusive per Databento conventions for most endpoints


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    api_key = get_secret(API_KEY_SECRET)
    client = db.Historical(api_key)

    # --- Pull daily bars ---
    try:
        ts = client.timeseries.get_range(
            dataset=DATASET,
            schema=SCHEMA,
            start=START_DATE,
            end=END_DATE,
            symbols=SYMBOL,
            stype_in=STYPE_IN,
        )
    except Exception as e:
        print(f"ERROR: timeseries.get_range failed: {e}", file=sys.stderr)
        return 1

    # Convert to DataFrame using Databento client helper
    try:
        df = ts.to_df()
    except Exception as e:
        print(f"ERROR: failed to convert result to DataFrame: {e}", file=sys.stderr)
        return 1

    # --- Basic inspections ---
    cols = list(df.columns)
    dtypes = {c: str(t) for c, t in df.dtypes.items()}

    # ts_event may be either a column or the index depending on client behaviour.
    idx_name = getattr(df.index, "name", None)
    idx_type = str(getattr(df.index, "dtype", type(df.index)))

    # Row count and time bounds
    row_count = int(len(df))
    min_ts = None
    max_ts = None
    if row_count > 0:
        # Try index first
        try:
            min_ts = str(df.index.min())
            max_ts = str(df.index.max())
        except Exception:
            min_ts = None
            max_ts = None

        # If ts_event exists as a column, also compute its min/max
        if "ts_event" in df.columns:
            try:
                min_ts = f"{min_ts} | ts_event(min)={df['ts_event'].min()}"
                max_ts = f"{max_ts} | ts_event(max)={df['ts_event'].max()}"
            except Exception:
                pass

    # Identify candidate identity fields present
    identity_fields = [
        c for c in ["publisher_id", "instrument_id", "symbol"] if c in df.columns
    ]

    # --- Output block ---
    print("=" * 80)
    print("MXM V1 — Databento Proof 4: Pull ohlcv-1d for one contract")
    print("=" * 80)
    print(f"Timestamp (UTC): {_utc_now_iso()}")
    print(f"Dataset:         {DATASET}")
    print(f"Schema:          {SCHEMA}")
    print(f"Symbol:          {SYMBOL} (stype_in={STYPE_IN})")
    print(f"Window:          {START_DATE} -> {END_DATE} (end is exclusive)")
    print("-" * 80)
    print(f"Rows returned:   {row_count}")
    print(f"Index:           name={idx_name!r} dtype={idx_type}")
    print(f"Time bounds:     min={min_ts} max={max_ts}")
    print("-" * 80)
    print("Columns:")
    print(json.dumps(cols, indent=2))
    print("-" * 80)
    print("Dtypes:")
    print(json.dumps(dtypes, indent=2, sort_keys=True))
    print("-" * 80)
    print(f"Identity fields present: {identity_fields}")
    if identity_fields and row_count > 0:
        sample_identity = {}
        for f in identity_fields:
            try:
                # show unique values (capped) for sanity
                uniq = df[f].unique()
                sample_identity[f] = [str(x) for x in uniq[:10]]
            except Exception:
                sample_identity[f] = ["<unavailable>"]
        print("Identity field sample (unique values, capped):")
        print(json.dumps(sample_identity, indent=2, sort_keys=True))
        print("-" * 80)

    print("Head (first 10 rows):")
    # Print a small head, but avoid dumping huge floats if present
    try:
        print(df.head(10).to_string())
    except Exception:
        print(df.head(10))

    print("=" * 80)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
