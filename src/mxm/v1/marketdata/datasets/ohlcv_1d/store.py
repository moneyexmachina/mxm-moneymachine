from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.parquet.daily_bars import (
    read_daily_bars,
    write_daily_bars,
)


@dataclass(frozen=True)
class CoverageWindow:
    """
    Observed coverage in local parquet store for a single instrument identity.

    min_ts/max_ts are dates (UTC) derived from ts_event.
    None indicates no stored data.
    """

    bars_path: Path
    exists: bool
    row_count: int
    min_ts: Optional[pd.Timestamp]
    max_ts: Optional[pd.Timestamp]


class OHLCV1DStore:
    """
    Dataset-domain store for ohlcv-1d.

    Responsibilities:
    - Provide stable local persistence operations (delegating to daily_bars.py)
    - Provide local coverage introspection (min/max/rowcount) for orchestration gates

    Non-responsibilities:
    - No vendor logic
    - No mapping logic
    - No contract lifecycle semantics
    """

    def __init__(self, *, layout: MarketdataLayout) -> None:
        self._layout = layout

    # -------------------------
    # Local persistence API
    # -------------------------

    def bars_path(self, *, dataset: str, publisher_id: int, instrument_id: int) -> Path:
        return self._layout.bars_path(
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
        write_daily_bars(
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
        return read_daily_bars(
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
    ) -> CoverageWindow:
        path = self.bars_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )

        if not path.exists():
            return CoverageWindow(
                bars_path=path,
                exists=False,
                row_count=0,
                min_ts=None,
                max_ts=None,
            )

        # This reads the parquet; acceptable at MVP scale. If it becomes a bottleneck,
        # we can later add a lightweight metadata sidecar (out of scope now).
        df = pd.read_parquet(path)

        if df.empty:
            return CoverageWindow(
                bars_path=path,
                exists=True,
                row_count=0,
                min_ts=None,
                max_ts=None,
            )

        # ts_event is expected to be present and UTC-normalised by schema coercion.
        ts_min = pd.Timestamp(df["ts_event"].min())
        ts_max = pd.Timestamp(df["ts_event"].max())

        # Ensure UTC tz-awareness for stable comparisons
        ts_min = (
            ts_min.tz_localize("UTC")
            if ts_min.tzinfo is None
            else ts_min.tz_convert("UTC")
        )
        ts_max = (
            ts_max.tz_localize("UTC")
            if ts_max.tzinfo is None
            else ts_max.tz_convert("UTC")
        )

        return CoverageWindow(
            bars_path=path,
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
        path = self.bars_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )
        if not path.exists():
            return False
        path.unlink()
        return True
