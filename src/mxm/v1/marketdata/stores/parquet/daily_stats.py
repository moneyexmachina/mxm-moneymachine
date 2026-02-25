from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pandas as pd

from mxm.v1.marketdata.schema.daily_stats import (
    coerce_daily_stats,
    hash_daily_stats_content,
    validate_daily_stats,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.utils.time_utils import to_utc_ts


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def write_daily_stats(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    df_new: pd.DataFrame,
    skip_if_unchanged: bool = True,
) -> dict[str, Any]:
    """
    Persist derived daily_stats surface for a single instrument.

    Semantics (derived dataset):
    - full overwrite (no merge)
    - canonical sort by session_date
    - atomic write (tmp then replace)
    - optional idempotency: if content hash unchanged, do not rewrite

    Returns metadata useful for orchestration/ledger:
      - wrote: bool
      - rows: int
      - session_start/session_end: pd.Timestamp | None (UTC midnight)
      - sha256: str
      - path: Path
    """
    out_path = layout.daily_stats_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    tmp_path = layout.tmp_daily_stats_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    _ensure_parent_dir(out_path)

    df_new = coerce_daily_stats(df_new, ensure_column_order=True)
    validate_daily_stats(df_new)

    sha_new = hash_daily_stats_content(df_new)

    if skip_if_unchanged and out_path.exists():
        df_old = pd.read_parquet(out_path)
        df_old = coerce_daily_stats(df_old, ensure_column_order=True)
        validate_daily_stats(df_old)

        sha_old = hash_daily_stats_content(df_old)
        if sha_old == sha_new:
            smin = to_utc_ts(df_old["session_date"].min()) if not df_old.empty else None
            smax = to_utc_ts(df_old["session_date"].max()) if not df_old.empty else None
            return {
                "wrote": False,
                "rows": int(len(df_old)),
                "session_start": smin,
                "session_end": smax,
                "sha256": sha_old,
                "path": out_path,
            }

    df_new.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, out_path)

    smin = to_utc_ts(df_new["session_date"].min()) if not df_new.empty else None
    smax = to_utc_ts(df_new["session_date"].max()) if not df_new.empty else None
    return {
        "wrote": True,
        "rows": int(len(df_new)),
        "session_start": smin,
        "session_end": smax,
        "sha256": sha_new,
        "path": out_path,
    }


def read_daily_stats(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Read derived daily_stats surface from the local store only.

    start/end are interpreted as [start, end) and applied on session_date.
    session_date is tz-aware UTC midnight timestamps.
    """
    path = layout.daily_stats_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    if not path.exists():
        raise FileNotFoundError(f"daily_stats not found: {path}")

    df = pd.read_parquet(path)
    df = coerce_daily_stats(df, ensure_column_order=True)
    validate_daily_stats(df)

    if start is not None:
        start = to_utc_ts(start).normalize()
        df = df[df["session_date"] >= start]

    if end is not None:
        end = to_utc_ts(end).normalize()
        df = df[df["session_date"] < end]

    return df.reset_index(drop=True)
