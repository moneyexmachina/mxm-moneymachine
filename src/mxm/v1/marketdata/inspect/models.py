# mxm/v1/marketdata/inspect/models.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from mxm.v1.marketdata.datasets.ohlcv_1d.coverage import (
    CoverageSurfaces,
    CoverageWindows,
)
from mxm.v1.marketdata.time_utils import parse_ts

# -------------------------
# Attempt / status representation
# -------------------------


class AttemptStatus(str, Enum):
    unmapped = "unmapped"
    skipped_empty_expected_window = "skipped_empty_expected_window"
    complete = "complete"
    dry_run = "dry_run"
    skipped_cost_cap = "skipped_cost_cap"
    ingested = "ingested"
    incomplete = "incomplete"
    error = "error"  # not in your comment list, but observed in the sample row


@dataclass(frozen=True)
class AttemptSummary:
    attempt_uid: str
    run_ts_utc: str
    mode: str
    dry_run: bool

    status: str
    status_detail: str | None

    cost_cap_usd: float | None
    cost_estimated_usd: float | None
    cost_charged_usd: float | None
    cost_used_usd: float | None

    error_type: str | None
    error_message: str | None
    is_empty: bool
    vendor_final: bool

    @property
    def run_ts(self) -> pd.Timestamp:
        """
        Parsed timestamp view of run_ts_utc.

        Naming discipline:
          - *_ts_utc is a canonical string
          - *_ts is a pd.Timestamp
        """
        return parse_ts(self.run_ts_utc)


# -------------------------
# Contract / product coverage models
# -------------------------


@dataclass(frozen=True)
class ContractCoverage:
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


@dataclass(frozen=True)
class ProductCoverage:
    product_id: str
    contracts_total: int
    contracts_complete: int
    contracts_incomplete: int
    contracts_unmapped: int
    contracts_error: int
    contracts_empty_expected: int

    # Optional rollups
    stored_earliest: pd.Timestamp | None
    stored_latest: pd.Timestamp | None
    expected_earliest: pd.Timestamp | None
    expected_latest: pd.Timestamp | None

    last_run_ts_utc: pd.Timestamp | None

    @property
    def complete(self) -> bool:
        return (
            self.contracts_total > 0
            and self.contracts_incomplete == 0
            and self.contracts_unmapped == 0
            and self.contracts_error == 0
        )


@dataclass(frozen=True)
class SystemSummary:
    products_total: int
    products_never_run: int
    products_complete: int
    products_partial: int
    products_error_only: int
