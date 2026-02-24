# mxm/v1/marketdata/inspect/models.py
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from mxm.v1.utils.time_utils import parse_ts

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

    status: AttemptStatus
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


class ProductStatus(str, Enum):
    never_run = "never_run"
    done = "done"
    partial = "partial"
    blocked = "blocked"
    error = "error"
