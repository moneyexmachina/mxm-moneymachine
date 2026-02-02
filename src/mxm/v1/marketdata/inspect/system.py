# mxm/v1/marketdata/inspect/system.py
from __future__ import annotations

"""
System-level inspection rollups for OHLCV-1D coverage.

This module is part of the *inspection* layer. It is intentionally read-only and
exists to aggregate contract-level inspection models into a simple system-wide
report.

Normative constraints (MXM V1):
- This module MUST NOT implement coverage or completeness logic.
  Contract coverage semantics are defined in:
      mxm.v1.marketdata.datasets.ohlcv_1d.coverage
- This module MUST NOT perform ad-hoc timestamp manipulation.
  Persisted timestamp facts are stored as canonical ISO8601Z strings (e.g. *_ts_utc),
  and typed views (e.g. *_ts) are obtained only via explicit parse_ts at the model edge.
- Status fields (status, status_detail, vendor_final, is_empty) are treated as
  authoritative facts from the attempts ledger and are never inferred.

Design notes:
- Product ordering in the returned report is stable by product_id (sorted).
- Within a product, we preserve the store-provided ordering of latest attempts.
- Incomplete count is derived as total - complete with an invariant check to detect
  classification drift.

This report is "freshness-ish": last_run_ts reflects the most recent attempt recorded
per product, not live vendor staleness.
"""

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import (
    OHLCV1DAttemptRow,
    OHLCV1DAttemptsStore,
)
from mxm.v1.marketdata.inspect.contracts import contract_coverage_from_attempt_row
from mxm.v1.marketdata.inspect.models import ContractCoverage
from mxm.v1.marketdata.time_utils import parse_ts

SystemProductStatus = Literal["done", "partial", "blocked", "error"]


@dataclass(frozen=True)
class SystemProductRow:
    product_id: str

    status: SystemProductStatus
    status_reason: str

    contracts_total: int
    contracts_complete: int
    contracts_incomplete: int
    contracts_unmapped: int
    contracts_blocked_cost: int
    contracts_error: int

    last_run_ts_utc: str | None
    last_mode: str | None

    @property
    def last_run_ts(self) -> pd.Timestamp | None:
        """
        Parsed timestamp view of last_run_ts_utc.

        Naming discipline:
          - *_ts_utc is a canonical string
          - *_ts is a pd.Timestamp
        """
        return (
            parse_ts(self.last_run_ts_utc) if self.last_run_ts_utc is not None else None
        )


@dataclass(frozen=True)
class SystemCoverageReport:
    products: tuple[SystemProductRow, ...]
    contracts_total: int


def get_system_coverage_report(
    *, attempts: OHLCV1DAttemptsStore
) -> SystemCoverageReport:
    """
    System-wide read-only rollup across the latest attempt per contract_key.
    """
    rows = attempts.list_latest_attempts_all_contracts()
    if not rows:
        return SystemCoverageReport(products=(), contracts_total=0)

    by_product: dict[str, list[OHLCV1DAttemptRow]] = {}
    for r in rows:
        by_product.setdefault(r.product_id, []).append(r)

    product_rows: list[SystemProductRow] = []

    for product_id, attempt_rows in by_product.items():
        covs: list[ContractCoverage] = [
            contract_coverage_from_attempt_row(r) for r in attempt_rows
        ]

        total = len(covs)
        complete = 0
        unmapped = 0
        blocked_cost = 0
        errors = 0

        last_run_ts: pd.Timestamp | None = None
        last_run_ts_utc: str | None = None
        last_mode: str | None = None

        # We preserve row ordering; this loop is deterministic given the store result.
        for c in covs:
            la = c.last_attempt

            # Latest run timestamp (max)
            run_ts = la.run_ts
            if last_run_ts is None or run_ts > last_run_ts:
                last_run_ts = run_ts
                last_run_ts_utc = la.run_ts_utc
                last_mode = la.mode

            st = la.status

            # Blockers / hard errors come from the attempts ledger (facts), not coverage semantics.
            if st == "unmapped":
                unmapped += 1
                continue

            if st == "skipped_cost_cap":
                blocked_cost += 1
                continue

            if st == "error":
                errors += 1
                continue

            # Canonical completeness is window containment at the contract level.
            if c.windows.complete:
                complete += 1
            else:
                # If orchestrator claims complete but windows disagree, treat as an error signal.
                if st == "complete":
                    errors += 1

        # Derived counts + invariant check (guards against future drift)
        incomplete = total - complete
        # We do not keep explicit key lists in the system rollup, so we only verify arithmetic sanity.
        if incomplete < 0 or complete < 0 or complete > total:
            raise RuntimeError(
                f"inconsistent counts for product_id={product_id!r}: "
                f"total={total} complete={complete} incomplete={incomplete}"
            )

        # Roll-up status semantics
        if (
            total > 0
            and complete == total
            and errors == 0
            and unmapped == 0
            and blocked_cost == 0
        ):
            status: SystemProductStatus = "done"
            reason = "all contracts complete"
        else:
            if errors > 0:
                status = "error"
                reason = "one or more contracts in error or inconsistent completeness"
            elif unmapped > 0:
                status = "blocked"
                reason = "one or more contracts unmapped"
            elif blocked_cost > 0:
                status = "blocked"
                reason = "one or more contracts blocked by cost cap"
            else:
                status = "partial"
                reason = "some contracts incomplete"

        product_rows.append(
            SystemProductRow(
                product_id=product_id,
                status=status,
                status_reason=reason,
                contracts_total=total,
                contracts_complete=complete,
                contracts_incomplete=incomplete,
                contracts_unmapped=unmapped,
                contracts_blocked_cost=blocked_cost,
                contracts_error=errors,
                last_run_ts_utc=last_run_ts_utc,
                last_mode=last_mode,
            )
        )

    product_rows_sorted = tuple(sorted(product_rows, key=lambda r: r.product_id))
    return SystemCoverageReport(products=product_rows_sorted, contracts_total=len(rows))
