# src/mxm/v1/marketdata/stores/parquet/statistics_1d.py
from __future__ import annotations

import os
from pathlib import Path

import pandas as pd

from mxm.v1.marketdata.schema.statistics_1d import (
    coerce_statistics_1d,
    validate_statistics_1d,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.time_utils import to_utc_ts


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


# Stable *event* identity key for statistics (rtype=24).
# NOTE: we intentionally do NOT use ts_ref here because it is nullable (NaT) for session stats.
_STAT_EVENT_KEY = ["instrument_id", "stat_type", "ts_event", "sequence"]


def write_statistics_1d(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    df_new: pd.DataFrame,
) -> None:
    """
    Idempotently merge and persist statistics events for a single instrument key.

    Statistics is an event stream:
    - multiple messages for the same trading session/statistic are expected
      (e.g. preliminary -> final settlements)
    - ts_ref is nullable for session stats and must not be used for event identity

    Rules:
    - event key: (instrument_id, stat_type, ts_event, sequence)
      (prevents uncontrolled duplication across reruns)
    - deduplicate on event key (keep last; latest write wins)
    - stable sort by (ts_event, stat_type, sequence)
    - atomic write (tmp file then os.replace)
    """
    # Coerce + validate incoming frame (loudly)
    df_new = coerce_statistics_1d(
        df_new, dataset=dataset, schema="statistics", ensure_column_order=True
    )

    stats_path = layout.statistics_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    tmp_path = layout.tmp_statistics_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    _ensure_parent_dir(stats_path)

    if stats_path.exists():
        df_old = pd.read_parquet(stats_path)
        # Ensure old is still valid; catches drift/corruption early
        df_old = coerce_statistics_1d(
            df_old, dataset=dataset, schema="statistics", ensure_column_order=True
        )
        df_all = pd.concat([df_old, df_new], ignore_index=True)
    else:
        df_all = df_new.copy()

    # Deduplicate on stable event identity key
    df_all = df_all.drop_duplicates(subset=_STAT_EVENT_KEY, keep="last")

    # Sort to keep file stable and query-friendly
    # Primary time axis for an event stream is ts_event (not ts_ref).
    df_all = df_all.sort_values(["ts_event", "stat_type", "sequence"]).reset_index(
        drop=True
    )

    # Final validation before persist
    validate_statistics_1d(df_all)

    # Atomic write
    df_all.to_parquet(tmp_path, index=False)
    os.replace(tmp_path, stats_path)


def read_statistics_1d(
    *,
    layout: MarketdataLayout,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Read statistics events from the local store only.

    start/end are interpreted as [start, end), and are applied on `ts_event`
    (the event timestamp).
    """
    stats_path = layout.statistics_path(
        dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
    )
    if not stats_path.exists():
        raise FileNotFoundError(f"statistics not found: {stats_path}")

    df = pd.read_parquet(stats_path)
    df = coerce_statistics_1d(
        df, dataset=dataset, schema="statistics", ensure_column_order=True
    )

    if start is not None:
        start = to_utc_ts(start)
        df = df[df["ts_event"] >= start]

    if end is not None:
        end = to_utc_ts(end)
        df = df[df["ts_event"] < end]

    return df.reset_index(drop=True)
