from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.parquet.daily_stats import (
    read_daily_stats,
    write_daily_stats,
)
from mxm.v1.utils.time_utils import to_utc_ts


@dataclass(frozen=True)
class StoreCoverageSnapshot:
    """
    Observed coverage snapshot in the local parquet store for a single instrument identity.

    - min_ts / max_ts are observed UTC-midnight timestamps (min/max of session_date).
    - exists indicates whether the daily_stats parquet file exists.
    """

    stats_path: Path
    exists: bool
    row_count: int
    min_ts: Optional[pd.Timestamp]
    max_ts: Optional[pd.Timestamp]


class DailyStatsStore:
    """
    Dataset-domain store for derived `daily_stats` surfaces.

    Responsibilities:
    - Provide stable local persistence operations (delegating to stores/parquet/daily_stats.py)
    - Provide local coverage introspection (min/max/rowcount) for orchestration gates

    Non-responsibilities:
    - No calendar logic
    - No selection logic
    - No vendor logic
    """

    def __init__(self, *, layout: MarketdataLayout) -> None:
        self._layout = layout

    # -------------------------
    # Local persistence API
    # -------------------------

    def stats_path(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> Path:
        return self._layout.daily_stats_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )

    def write(
        self,
        *,
        dataset: str,
        publisher_id: int,
        instrument_id: int,
        df_new: pd.DataFrame,
        skip_if_unchanged: bool = True,
    ) -> dict[str, object]:
        return write_daily_stats(
            layout=self._layout,
            dataset=dataset,
            publisher_id=publisher_id,
            instrument_id=instrument_id,
            df_new=df_new,
            skip_if_unchanged=skip_if_unchanged,
        )

    def read(
        self,
        *,
        dataset: str,
        publisher_id: int,
        instrument_id: int,
        start: pd.Timestamp | None = None,
        end: pd.Timestamp | None = None,
    ) -> pd.DataFrame:
        return read_daily_stats(
            layout=self._layout,
            dataset=dataset,
            publisher_id=publisher_id,
            instrument_id=instrument_id,
            start=start,
            end=end,
        )

    # -------------------------
    # Coverage / introspection
    # -------------------------

    def scan_coverage(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> StoreCoverageSnapshot:
        path = self.stats_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )

        if not path.exists():
            return StoreCoverageSnapshot(
                stats_path=path,
                exists=False,
                row_count=0,
                min_ts=None,
                max_ts=None,
            )

        df = pd.read_parquet(path)
        if df.empty:
            return StoreCoverageSnapshot(
                stats_path=path,
                exists=True,
                row_count=0,
                min_ts=None,
                max_ts=None,
            )

        ts_min = to_utc_ts(df["session_date"].min()).normalize()
        ts_max = to_utc_ts(df["session_date"].max()).normalize()

        return StoreCoverageSnapshot(
            stats_path=path,
            exists=True,
            row_count=int(len(df)),
            min_ts=ts_min,
            max_ts=ts_max,
        )

    def delete(self, *, dataset: str, publisher_id: int, instrument_id: int) -> bool:
        """
        Identity-scoped destructive reset for local parquet only.
        Returns True if a file existed and was deleted.
        """
        path = self.stats_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )
        if not path.exists():
            return False
        path.unlink()
        return True
