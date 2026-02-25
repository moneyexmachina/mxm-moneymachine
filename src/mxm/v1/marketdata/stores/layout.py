from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MarketdataLayout:
    """
    Filesystem layout for MXM V1 marketdata store.

    We keep this layout V1-local. It can be extracted later into mxm-marketdata.

    Layout principles (V1):
    - vendor-rooted namespaces (e.g. databento)
    - schema-scoped directories (e.g. ohlcv-1d, statistics)
    - per-instrument storage under `by_instrument/`
    - single Parquet file per instrument per schema (for MVP simplicity)
      (later: partition by date for large event streams)
    """

    root: Path

    def instrument_dir(
        self,
        *,
        dataset: str,
        publisher_id: int,
        instrument_id: int,
        schema_dir: str = "ohlcv-1d",
        vendor: str = "databento",
    ) -> Path:
        return (
            self.root
            / "marketdata"
            / vendor
            / schema_dir
            / "by_instrument"
            / f"dataset={dataset}"
            / f"publisher_id={publisher_id}"
            / f"instrument_id={instrument_id}"
        )

    # -------------------------
    # OHLCV-1D paths
    # -------------------------

    def bars_path(self, *, dataset: str, publisher_id: int, instrument_id: int) -> Path:
        return (
            self.instrument_dir(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
                schema_dir="ohlcv-1d",
            )
            / "bars.parquet"
        )

    def tmp_bars_path(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> Path:
        return (
            self.instrument_dir(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
                schema_dir="ohlcv-1d",
            )
            / "bars.tmp.parquet"
        )

    # -------------------------
    # Statistics paths
    # -------------------------

    def statistics_path(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> Path:
        return (
            self.instrument_dir(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
                schema_dir="statistics",
            )
            / "statistics.parquet"
        )

    def tmp_statistics_path(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> Path:
        return (
            self.instrument_dir(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
                schema_dir="statistics",
            )
            / "statistics.tmp.parquet"
        )

    # -------------------------
    # Daily-stats paths (derived)
    # -------------------------

    def daily_stats_path(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> Path:
        return (
            self.instrument_dir(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
                schema_dir="daily-stats",
            )
            / "daily_stats.parquet"
        )

    def tmp_daily_stats_path(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> Path:
        return (
            self.instrument_dir(
                dataset=dataset,
                publisher_id=publisher_id,
                instrument_id=instrument_id,
                schema_dir="daily-stats",
            )
            / "daily_stats.tmp.parquet"
        )

    # -------------------------
    # SQLite metadata DB
    # -------------------------

    def sqlite_db_path(self) -> Path:
        """
        Path to the single marketdata SQLite database.

        This DB is owned by marketdata (not vendor-specific) and stores metadata /
        event-like datasets (instrument definitions, mappings, watermarks, etc.).
        """
        return self.root / "marketdata" / "marketdata.sqlite3"
