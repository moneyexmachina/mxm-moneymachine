# src/mxm/v1/marketdata/datasets/statistics_1d/store.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.parquet.statistics_1d import (
    read_statistics_1d,
    write_statistics_1d,
)
from mxm.v1.utils.time_utils import to_utc_ts


@dataclass(frozen=True)
class StoreCoverageSnapshot:
    """
    Observed coverage snapshot in the local parquet store for a single instrument identity.

    - min_ts / max_ts are observed UTC timestamps (min/max of ts_event), not day-aligned.
    - exists indicates whether the statistics parquet file exists.
    """

    stats_path: Path
    exists: bool
    row_count: int
    min_ts: Optional[pd.Timestamp]
    max_ts: Optional[pd.Timestamp]


class Statistics1DStore:
    """
    Dataset-domain store for Databento `statistics` (rtype=24) events.

    Responsibilities:
    - Provide stable local persistence operations (delegating to stores/parquet/statistics_1d.py)
    - Provide local coverage introspection (min/max/rowcount) for orchestration gates

    Non-responsibilities:
    - No vendor logic
    - No mapping logic
    - No contract lifecycle semantics
    - No daily canonicalization (final-vs-prelim selection is a derived view concern)
    """

    def __init__(self, *, layout: MarketdataLayout) -> None:
        self._layout = layout

    # -------------------------
    # Local persistence API
    # -------------------------

    def stats_path(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> Path:
        return self._layout.statistics_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )

    def write(
        self,
        *,
        dataset: str,
        publisher_id: int,
        instrument_id: int,
        df_new: pd.DataFrame,
    ) -> None:
        write_statistics_1d(
            layout=self._layout,
            dataset=dataset,
            publisher_id=publisher_id,
            instrument_id=instrument_id,
            df_new=df_new,
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
        return read_statistics_1d(
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

        # This reads the parquet; acceptable at MVP scale. If it becomes a bottleneck,
        # we can later add a lightweight metadata sidecar (out of scope now).
        df = pd.read_parquet(path)

        if df.empty:
            return StoreCoverageSnapshot(
                stats_path=path,
                exists=True,
                row_count=0,
                min_ts=None,
                max_ts=None,
            )

        # ts_event is expected to be present and already schema-coerced.
        ts_min = to_utc_ts(df["ts_event"].min())
        ts_max = to_utc_ts(df["ts_event"].max())

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
