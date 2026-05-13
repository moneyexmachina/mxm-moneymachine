from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.parquet.statistics_1d import (
    Statistics1DMetaDict,
    read_statistics_1d,
    read_statistics_1d_meta,
    write_statistics_1d,
)
from mxm.v1.utils.time_utils import parse_ts


@dataclass(frozen=True)
class StoreCoverageSnapshot:
    """
    Observed coverage snapshot in the local parquet store for a single instrument identity.

    - min_ts / max_ts are observed UTC timestamps (min/max of ts_event), not day-aligned.
    - content_sha256 is the semantic, order-invariant hash of canonicalised content.
    - artifact_sha256 is the sha256 of parquet bytes (integrity/debug).
    - exists indicates whether the statistics parquet file exists.
    """

    stats_path: Path
    exists: bool
    row_count: int
    min_ts: pd.Timestamp | None
    max_ts: pd.Timestamp | None

    meta_path: Path
    meta_exists: bool
    content_sha256: str | None = None
    artifact_sha256: str | None = None
    meta_origin: str | None = None


class Statistics1DStore:
    """
    Dataset-domain store for Databento `statistics` (rtype=24) events.
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

    def meta_path(self, *, dataset: str, publisher_id: int, instrument_id: int) -> Path:
        # Must match stores/parquet/statistics_1d.py naming.
        return self.stats_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        ).with_name("statistics.meta.json")

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
        stats_path = self.stats_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )
        meta_path = self.meta_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )

        if not stats_path.exists():
            return StoreCoverageSnapshot(
                stats_path=stats_path,
                exists=False,
                row_count=0,
                min_ts=None,
                max_ts=None,
                meta_path=meta_path,
                meta_exists=meta_path.exists(),
            )

        # Meta-first path (typed)
        try:
            meta: Statistics1DMetaDict | None = read_statistics_1d_meta(
                layout=self._layout,
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
            )
        except Exception:
            meta = None  # corrupt meta -> treat as missing for provenance purposes

        if meta is not None:
            row_count = int(meta["row_count"])
            min_ts_s = meta.get("min_ts_event")
            max_ts_s = meta.get("max_ts_event")

            return StoreCoverageSnapshot(
                stats_path=stats_path,
                exists=True,
                row_count=row_count,
                min_ts=parse_ts(min_ts_s) if min_ts_s else None,
                max_ts=parse_ts(max_ts_s) if max_ts_s else None,
                meta_path=meta_path,
                meta_exists=True,
                content_sha256=meta.get("content_sha256"),
                artifact_sha256=meta.get("artifact_sha256"),
                meta_origin=meta.get("meta_origin"),
            )

        # Fallback: parquet scan (coverage only)
        df = pd.read_parquet(stats_path)
        if df.empty:
            return StoreCoverageSnapshot(
                stats_path=stats_path,
                exists=True,
                row_count=0,
                min_ts=None,
                max_ts=None,
                meta_path=meta_path,
                meta_exists=False,
            )

        return StoreCoverageSnapshot(
            stats_path=stats_path,
            exists=True,
            row_count=len(df),
            min_ts=parse_ts(df["ts_event"].min()),
            max_ts=parse_ts(df["ts_event"].max()),
            meta_path=meta_path,
            meta_exists=False,
        )

    def delete(self, *, dataset: str, publisher_id: int, instrument_id: int) -> bool:
        """
        Identity-scoped destructive reset for local parquet + meta sidecar.
        Returns True if the parquet file existed and was deleted.
        """
        stats_path = self.stats_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )
        meta_path = self.meta_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        )

        existed = stats_path.exists()
        if existed:
            stats_path.unlink()

        # Best-effort: remove meta as well
        if meta_path.exists():
            meta_path.unlink()

        return existed
