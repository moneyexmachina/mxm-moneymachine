from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout
from mxm.moneymachine.marketdata.stores.parquet.daily_stats import (
    read_daily_stats,
    read_daily_stats_meta,
    write_daily_stats,
)
from mxm.moneymachine.utils.time_utils import to_utc_ts


@dataclass(frozen=True)
class StoreCoverageSnapshot:
    """
    Observed coverage snapshot in the local parquet store for a single instrument identity.

    - min_ts / max_ts are observed UTC-midnight timestamps (min/max of session_date).
    - content_sha256 is the semantic, order-invariant hash of canonicalised content.
    - artifact_sha256 is the sha256 of parquet bytes (integrity/debug).
    - exists indicates whether the daily_stats parquet file exists.
    """

    stats_path: Path
    exists: bool
    row_count: int
    min_ts: pd.Timestamp | None
    max_ts: pd.Timestamp | None

    meta_path: Path | None = None
    content_sha256: str | None = None
    artifact_sha256: str | None = None
    source_content_sha256: str | None = None


class DailyStatsStore:
    """
    Dataset-domain store for derived `daily_stats` surfaces.

    Responsibilities:
    - Provide stable local persistence operations (delegating to stores/parquet/daily_stats.py)
    - Provide local coverage introspection (min/max/rowcount) and fingerprints for gating

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

    def meta_path(self, *, dataset: str, publisher_id: int, instrument_id: int) -> Path:
        # Must match stores/parquet/daily_stats.py naming.
        return self.stats_path(
            dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
        ).with_name("daily_stats.meta.json")

    def write(
        self,
        *,
        dataset: str,
        publisher_id: int,
        instrument_id: int,
        df_new: pd.DataFrame,
        source_content_sha256: str | None = None,
        skip_if_unchanged: bool = True,
    ) -> dict[str, object]:
        return write_daily_stats(
            layout=self._layout,
            dataset=dataset,
            publisher_id=publisher_id,
            instrument_id=instrument_id,
            df_new=df_new,
            source_content_sha256=source_content_sha256,
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

    def read_meta(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> dict[str, object] | None:
        m = read_daily_stats_meta(
            layout=self._layout,
            dataset=dataset,
            publisher_id=publisher_id,
            instrument_id=instrument_id,
        )
        if m is None:
            return None
        return m  # type: ignore[return-value]

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
                meta_path=meta_path if meta_path.exists() else None,
            )

        # Meta-first path (fast, preferred)
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text(encoding="utf-8"))

                row_count = int(meta["row_count"])
                min_s = meta.get("min_session_date")
                max_s = meta.get("max_session_date")

                # stored as day timestamps; parse via to_utc_ts and normalize
                min_ts = to_utc_ts(min_s).normalize() if min_s else None
                max_ts = to_utc_ts(max_s).normalize() if max_s else None

                return StoreCoverageSnapshot(
                    stats_path=stats_path,
                    exists=True,
                    row_count=row_count,
                    min_ts=min_ts,
                    max_ts=max_ts,
                    meta_path=meta_path,
                    content_sha256=meta.get("content_sha256"),
                    artifact_sha256=meta.get("artifact_sha256"),
                    source_content_sha256=meta.get("source_content_sha256"),
                )
            except Exception:
                # Corrupt/partial meta -> fall back to parquet scan
                pass

        # Fallback: read parquet (MVP acceptable) and compute min/max/rowcount only.
        df = pd.read_parquet(stats_path)
        if df.empty:
            return StoreCoverageSnapshot(
                stats_path=stats_path,
                exists=True,
                row_count=0,
                min_ts=None,
                max_ts=None,
                meta_path=meta_path if meta_path.exists() else None,
            )

        ts_min = to_utc_ts(df["session_date"].min()).normalize()
        ts_max = to_utc_ts(df["session_date"].max()).normalize()

        return StoreCoverageSnapshot(
            stats_path=stats_path,
            exists=True,
            row_count=len(df),
            min_ts=ts_min,
            max_ts=ts_max,
            meta_path=meta_path if meta_path.exists() else None,
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

        # Best-effort meta removal
        if meta_path.exists():
            meta_path.unlink()

        return existed
