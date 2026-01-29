from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import pandas as pd

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import OHLCV1DAttemptsStore
from mxm.v1.marketdata.datasets.ohlcv_1d.coverage import ContractCoverage
from mxm.v1.marketdata.inspect.contracts import list_contract_coverages_for_product

ProductStatus = Literal["never_run", "done", "partial", "blocked", "error"]


@dataclass(frozen=True)
class ProductCoverageSummary:
    product_id: str

    # Status roll-up
    status: ProductStatus
    status_reason: str

    # Counts
    contracts_total: int
    contracts_complete: int
    contracts_incomplete: int
    contracts_empty_expected: int
    contracts_vendor_final: int
    contracts_unmapped: int
    contracts_error: int
    contracts_blocked_cost: int

    # Freshness-ish (from attempts; not live vendor staleness)
    last_run_ts_utc: pd.Timestamp | None
    last_mode: str | None

    # Convenience lists for drilldown
    incomplete_contract_keys: tuple[str, ...]
    error_contract_keys: tuple[str, ...]
    unmapped_contract_keys: tuple[str, ...]


@dataclass(frozen=True)
class ProductCoverageReport:
    summary: ProductCoverageSummary
    contracts: tuple[ContractCoverage, ...]


# -------------------------
# Public API
# -------------------------


def get_product_coverage_report(
    *, attempts: OHLCV1DAttemptsStore, product_id: str
) -> ProductCoverageReport:
    """
    Read-only coverage report for a product, based on the latest attempt per contract_key.
    """
    coverages = list_contract_coverages_for_product(
        attempts=attempts, product_id=product_id
    )

    if len(coverages) == 0:
        summary = ProductCoverageSummary(
            product_id=product_id,
            status="never_run",
            status_reason="no attempts recorded for product",
            contracts_total=0,
            contracts_complete=0,
            contracts_incomplete=0,
            contracts_empty_expected=0,
            contracts_vendor_final=0,
            contracts_unmapped=0,
            contracts_error=0,
            contracts_blocked_cost=0,
            last_run_ts_utc=None,
            last_mode=None,
            incomplete_contract_keys=(),
            error_contract_keys=(),
            unmapped_contract_keys=(),
        )
        return ProductCoverageReport(summary=summary, contracts=())

    # Aggregate counts
    total = len(coverages)
    complete = 0
    incomplete = 0
    empty_expected = 0
    vendor_final = 0
    unmapped = 0
    errors = 0
    blocked_cost = 0

    incomplete_keys: list[str] = []
    error_keys: list[str] = []
    unmapped_keys: list[str] = []

    last_run_ts: pd.Timestamp | None = None
    last_mode: str | None = None

    for c in coverages:
        la = c.last_attempt

        # latest run timestamp (max)
        if last_run_ts is None or la.run_ts_utc > last_run_ts:
            last_run_ts = la.run_ts_utc
            last_mode = la.mode

        # vendor_final and is_empty: prefer AttemptSummary if present
        is_empty = getattr(la, "is_empty", False)
        vf = getattr(la, "vendor_final", False)

        if is_empty:
            empty_expected += 1
        if vf:
            vendor_final += 1

        # status bucketing
        st = la.status

        if st == "unmapped":
            unmapped += 1
            unmapped_keys.append(c.contract_key)
            incomplete += 1
            incomplete_keys.append(c.contract_key)
            continue

        if st == "skipped_cost_cap":
            blocked_cost += 1
            incomplete += 1
            incomplete_keys.append(c.contract_key)
            continue

        if st in ("error",):
            errors += 1
            error_keys.append(c.contract_key)
            incomplete += 1
            incomplete_keys.append(c.contract_key)
            continue

        # For everything else, use window completeness as the canonical criterion
        if c.windows.complete:
            complete += 1
        else:
            incomplete += 1
            incomplete_keys.append(c.contract_key)

            # If the attempt says complete but windows are not, flag as error-like
            if st in ("complete",) and c.windows.complete is False:
                # treat as an error signal for summary purposes
                errors += 1
                error_keys.append(c.contract_key)

    # Roll-up status semantics
    if total == 0:
        status: ProductStatus = "never_run"
        reason = "no attempts recorded for product"
    elif complete == total:
        status = "done"
        reason = "all contracts complete"
    else:
        # If any hard errors or unmapped or cost blocks exist, pick strongest status
        if errors > 0:
            status = "error"
            reason = (
                "one or more contracts have error status or inconsistent completeness"
            )
        elif unmapped > 0:
            status = "blocked"
            reason = "one or more contracts unmapped"
        elif blocked_cost > 0:
            status = "blocked"
            reason = "one or more contracts blocked by cost cap"
        else:
            status = "partial"
            reason = "some contracts incomplete"

    summary = ProductCoverageSummary(
        product_id=product_id,
        status=status,
        status_reason=reason,
        contracts_total=total,
        contracts_complete=complete,
        contracts_incomplete=incomplete,
        contracts_empty_expected=empty_expected,
        contracts_vendor_final=vendor_final,
        contracts_unmapped=unmapped,
        contracts_error=errors,
        contracts_blocked_cost=blocked_cost,
        last_run_ts_utc=last_run_ts,
        last_mode=last_mode,
        incomplete_contract_keys=tuple(incomplete_keys),
        error_contract_keys=tuple(error_keys),
        unmapped_contract_keys=tuple(unmapped_keys),
    )

    # stable ordering (nice for reports)
    coverages_sorted = tuple(sorted(coverages, key=lambda x: x.contract_key))
    return ProductCoverageReport(summary=summary, contracts=coverages_sorted)
