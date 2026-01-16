from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MarketdataLayout:
    """
    Filesystem layout for MXM V1 marketdata store.

    We keep this layout V1-local. It can be extracted later into mxm-marketdata.
    """

    root: Path

    def instrument_dir(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> Path:
        return (
            self.root
            / "marketdata"
            / "databento"
            / "ohlcv-1d"
            / "by_instrument"
            / f"dataset={dataset}"
            / f"publisher_id={publisher_id}"
            / f"instrument_id={instrument_id}"
        )

    def bars_path(self, *, dataset: str, publisher_id: int, instrument_id: int) -> Path:
        return (
            self.instrument_dir(
                dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
            )
            / "bars.parquet"
        )

    def tmp_bars_path(
        self, *, dataset: str, publisher_id: int, instrument_id: int
    ) -> Path:
        return (
            self.instrument_dir(
                dataset=dataset, publisher_id=publisher_id, instrument_id=instrument_id
            )
            / "bars.tmp.parquet"
        )
