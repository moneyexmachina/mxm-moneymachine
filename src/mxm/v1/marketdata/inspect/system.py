# mxm/v1/marketdata/inspect/system.py
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

import pandas as pd

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import OHLCV1DAttemptsStore
from mxm.v1.marketdata.datasets.ohlcv_1d.coverage import ContractCoverage
from mxm.v1.marketdata.inspect.contracts import contract_coverage_from_attempt_row

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

    last_run_ts_utc: pd.Timestamp | None
    last_mode: str | None


@dataclass(frozen=True)
class SystemCoverageReport:
    products: tuple[SystemProductRow, ...]
    contracts_total: int


def get_system_coverage_report(
    *, attempts: OHLCV1DAttemptsStore
) -> SystemCoverageReport:
    """
    System-wide read-only rollup across latest attempt per contract_key.
    """
    rows = attempts.list_latest_attempts_all_contracts()
    if not rows:
        return SystemCoverageReport(products=(), contracts_total=0)

    by_product = defaultdict(list)
    for r in rows:
        by_product[r.product_id].append(r)

    product_rows: list[SystemProductRow] = []

    for product_id, attempt_rows in by_product.items():
        covs: list[ContractCoverage] = [
            contract_coverage_from_attempt_row(r) for r in attempt_rows
        ]

        total = len(covs)
        complete = 0
        incomplete = 0
        unmapped = 0
        blocked_cost = 0
        errors = 0

        last_run_ts: pd.Timestamp | None = None
        last_mode: str | None = None

        for c in covs:
            la = c.last_attempt
            if last_run_ts is None or la.run_ts_utc > last_run_ts:
                last_run_ts = la.run_ts_utc
                last_mode = la.mode

            st = la.status
            if st == "unmapped":
                unmapped += 1
                incomplete += 1
                continue
            if st == "skipped_cost_cap":
                blocked_cost += 1
                incomplete += 1
                continue
            if st == "error":
                errors += 1
                incomplete += 1
                continue

            if c.windows.complete:
                complete += 1
            else:
                incomplete += 1
                # If orchestrator says "complete" but windows disagree, treat as error signal
                if st == "complete":
                    errors += 1

        # roll-up status
        if (
            complete == total
            and total > 0
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
                last_run_ts_utc=last_run_ts,
                last_mode=last_mode,
            )
        )

    product_rows_sorted = tuple(sorted(product_rows, key=lambda r: r.product_id))
    return SystemCoverageReport(products=product_rows_sorted, contracts_total=len(rows))
