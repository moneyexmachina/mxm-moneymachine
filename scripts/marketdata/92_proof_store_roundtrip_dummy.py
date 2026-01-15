"""
scripts/marketdata/92_proof_store_roundtrip_dummy.py

Proof script for Session 4 — Step 2 (Parquet store).

This script validates that the marketdata Parquet store can:
- write a canonical ohlcv-1d dataframe
- read it back
- perform an idempotent merge-write (no duplicate ts_event rows)
- preserve basic schema invariants

It uses a dummy dataframe (no Databento dependency).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from mxm.v1.marketdata.schema import coerce_ohlcv_1d, validate_ohlcv_1d
from mxm.v1.marketdata.store.layout import MarketdataLayout
from mxm.v1.marketdata.store.parquet_store import read_daily_bars, write_daily_bars


def _make_dummy_df(
    *,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    raw_symbol: str,
    dates_utc: list[str],
) -> pd.DataFrame:
    """
    Create a minimal dummy ohlcv-1d dataframe.
    dates_utc must be ISO date strings; each becomes 00:00:00Z.
    """
    ts = pd.to_datetime(dates_utc, utc=True)
    df = pd.DataFrame(
        {
            "ts_event": ts,
            "open": [100.0 + i for i in range(len(ts))],
            "high": [101.0 + i for i in range(len(ts))],
            "low": [99.0 + i for i in range(len(ts))],
            "close": [100.5 + i for i in range(len(ts))],
            "volume": [1000 + 10 * i for i in range(len(ts))],
            "dataset": dataset,
            "schema": "ohlcv-1d",
            "publisher_id": publisher_id,
            "instrument_id": instrument_id,
            "raw_symbol": raw_symbol,
        }
    )
    return coerce_ohlcv_1d(
        df, dataset=dataset, schema="ohlcv-1d", ensure_column_order=True
    )


def main() -> None:
    # Fixed dummy identity (does not need to match a real Databento instrument)
    dataset = "GLBX.MDP3"
    publisher_id = 1
    instrument_id = 99999999
    raw_symbol = "DUMMY"

    # Store root: ~/.mxm (Session 4 decision)
    mxm_root = Path.home() / ".mxm"
    layout = MarketdataLayout(root=mxm_root)

    bars_path = layout.bars_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    if bars_path.exists():
        print(f"[warn] Removing existing dummy store file: {bars_path}")
        bars_path.unlink()

    print("[step] Create dummy df (3 rows)")
    df1 = _make_dummy_df(
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        raw_symbol=raw_symbol,
        dates_utc=["2026-01-03", "2026-01-04", "2026-01-05"],
    )
    validate_ohlcv_1d(df1)

    print("[step] Write dummy df (first write)")
    write_daily_bars(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        df_new=df1,
    )
    assert bars_path.exists(), f"bars file was not created: {bars_path}"

    print("[step] Read back df")
    df_read_1 = read_daily_bars(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
    )
    validate_ohlcv_1d(df_read_1)
    assert len(df_read_1) == 3, (
        f"expected 3 rows after first write, got {len(df_read_1)}"
    )

    print("[step] Write overlapping dummy df (2 rows, one overlap)")
    df2 = _make_dummy_df(
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        raw_symbol=raw_symbol,
        dates_utc=["2026-01-05", "2026-01-06"],
    )
    write_daily_bars(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        df_new=df2,
    )

    print("[step] Read back df again and confirm dedup")
    df_read_2 = read_daily_bars(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
    )
    validate_ohlcv_1d(df_read_2)

    expected_dates = pd.to_datetime(
        ["2026-01-03", "2026-01-04", "2026-01-05", "2026-01-06"], utc=True
    )
    assert len(df_read_2) == 4, (
        f"expected 4 unique rows after merge, got {len(df_read_2)}"
    )
    assert (df_read_2["ts_event"].to_numpy() == expected_dates.to_numpy()).all(), (
        "ts_event ordering/values mismatch"
    )

    print("[ok] Store round-trip proof passed.")
    print(f"[info] Stored at: {bars_path}")
    print("[info] Head:")
    print(df_read_2.head(3).to_string(index=False))
    print("[info] Tail:")
    print(df_read_2.tail(3).to_string(index=False))


if __name__ == "__main__":
    main()
