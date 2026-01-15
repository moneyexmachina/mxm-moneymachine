from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from mxm.v1.marketdata.schema import coerce_ohlcv_1d, validate_ohlcv_1d
from mxm.v1.marketdata.store.layout import MarketdataLayout


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_daily_bars(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    df_new: pd.DataFrame,
) -> None:
    """
    Idempotently merge and persist daily bars for a single instrument key.

    Rules:
    - primary key: ts_event
    - deduplicate on ts_event (keep last)
    - sort by ts_event ascending
    - atomic write (tmp file then os.replace)
    """
    # Coerce + validate incoming frame (loudly)
    df_new = coerce_ohlcv_1d(
        df_new, dataset=dataset, schema="ohlcv-1d", ensure_column_order=True
    )

    bars_path = layout.bars_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    tmp_path = layout.tmp_bars_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    _ensure_parent_dir(bars_path)

    if bars_path.exists():
        df_old = pd.read_parquet(bars_path)
        # Ensure old is still valid; catches drift/corruption early
        df_old = coerce_ohlcv_1d(
            df_old, dataset=dataset, schema="ohlcv-1d", ensure_column_order=True
        )
        df_all = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_all = df_new.copy()

    # Deduplicate on ts_event, keep last (latest write wins)
    df_all = df_all.drop_duplicates(subset=["ts_event"], keep="last")

    # Sort to keep file stable and query-friendly
    df_all = df_all.sort_values("ts_event").reset_index(drop=True)

    # Final validation before persist
    validate_ohlcv_1d(df_all)

    # Atomic write
    df_all.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, bars_path)


def read_daily_bars(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Read daily bars from the local store only.

    start/end are interpreted as [start, end), consistent with Databento usage.
    """
    bars_path = layout.bars_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    if not bars_path.exists():
        raise FileNotFoundError(f"bars not found: {bars_path}")

    df = pd.read_parquet(bars_path)
    df = coerce_ohlcv_1d(
        df, dataset=dataset, schema="ohlcv-1d", ensure_column_order=True
    )

    if start is not None:
        start = (
            pd.Timestamp(start, tz="UTC")
            if pd.Timestamp(start).tzinfo is None
            else pd.Timestamp(start).tz_convert("UTC")
        )
        df = df[df["ts_event"] >= start]

    if end is not None:
        end = (
            pd.Timestamp(end, tz="UTC")
            if pd.Timestamp(end).tzinfo is None
            else pd.Timestamp(end).tz_convert("UTC")
        )
        df = df[df["ts_event"] < end]

    return df.reset_index(drop=True)
