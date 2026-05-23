from __future__ import annotations

from dataclasses import dataclass

from mxm.moneymachine.marketdata.datasets.ohlcv_1d.coverage import (
    CoverageSurfaces,
    CoverageWindows,
)
from mxm.moneymachine.marketdata.inspect.models import AttemptSummary


@dataclass(frozen=True)
class OHLCV1DContractCoverage:
    product_id: str
    contract_id: str
    contract_key: str

    dataset: str | None
    publisher_id: int | None
    instrument_id: int | None
    raw_symbol: str | None

    surfaces: CoverageSurfaces
    windows: CoverageWindows

    last_attempt: AttemptSummary
