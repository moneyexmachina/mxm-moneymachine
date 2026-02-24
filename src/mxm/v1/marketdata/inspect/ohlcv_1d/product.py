from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import OHLCV1DAttemptsStore
from mxm.v1.marketdata.inspect.models import (
    AttemptStatus,
    ProductStatus,
)
from mxm.v1.marketdata.inspect.ohlcv_1d.contracts import (
    list_contract_coverages_for_product,
)
from mxm.v1.marketdata.inspect.ohlcv_1d.models import OHLCV1DContractCoverage
from mxm.v1.utils.time_utils import parse_ts


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
    last_run_ts_utc: str | None
    last_mode: str | None

    # Convenience lists for drilldown
    incomplete_contract_keys: tuple[str, ...]
    error_contract_keys: tuple[str, ...]
    unmapped_contract_keys: tuple[str, ...]

    @property
    def last_run_ts(self) -> pd.Timestamp | None:
        """
        Parsed timestamp view of last_run_ts_utc.

        Naming discipline:
          - *_ts_utc is a canonical string
          - *_ts is a pd.Timestamp
        """
        return parse_ts(self.last_run_ts_utc) if self.last_run_ts_utc else None


@dataclass(frozen=True)
class ProductCoverageReport:
    summary: ProductCoverageSummary
    contracts: tuple[OHLCV1DContractCoverage, ...]


def compute_product_status(contracts: list[OHLCV1DContractCoverage]) -> ProductStatus:
    """
    Authoritative product status precedence (normative semantics):

      1) never_run if no attempts exist
      2) done if all contracts windows.complete AND none are unmapped/cost-blocked/error
      3) error if any contract error OR contradiction (attempt says 'complete' but windows incomplete w/o vendor_final)
      4) blocked if any unmapped or cost-blocked and no errors
      5) partial otherwise
    """
    if len(contracts) == 0:
        return ProductStatus.never_run

    any_error = False
    any_blocked = False
    all_complete = True

    for cc in contracts:
        w_complete = bool(cc.windows.complete)
        st = cc.last_attempt.status

        contradiction_complete = (
            st == AttemptStatus.complete
            and not w_complete
            and not cc.last_attempt.vendor_final
        )

        if st == AttemptStatus.error or contradiction_complete:
            any_error = True

        if st in (AttemptStatus.unmapped, AttemptStatus.skipped_cost_cap):
            any_blocked = True

        if not w_complete:
            all_complete = False

    if all_complete and not any_error and not any_blocked:
        return ProductStatus.done
    if any_error:
        return ProductStatus.error
    if any_blocked:
        return ProductStatus.blocked
    return ProductStatus.partial


# -------------------------
# Public API
# -------------------------


def get_product_coverage_report(
    *, attempts: OHLCV1DAttemptsStore, product_id: str
) -> ProductCoverageReport:
    """
    Read-only coverage report for a product, based on the latest attempt per contract_key.

    Normative discipline:
    - Completeness truth comes ONLY from c.windows.complete.
    - Attempt status is a persisted fact used for blocker/error bucketing.
    - status_detail is never used for bucketing.
    """
    coverages = list_contract_coverages_for_product(
        attempts=attempts, product_id=product_id
    )

    if len(coverages) == 0:
        summary = ProductCoverageSummary(
            product_id=product_id,
            status=ProductStatus.never_run,
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

    # -------------------------
    # Aggregate counts + drilldowns
    # -------------------------
    total = len(coverages)

    contracts_complete = 0
    contracts_empty_expected = 0
    contracts_vendor_final = 0
    contracts_unmapped = 0
    contracts_error = 0
    contracts_blocked_cost = 0

    incomplete_keys: list[str] = []
    error_keys: list[str] = []
    unmapped_keys: list[str] = []

    last_run_ts: pd.Timestamp | None = None
    last_run_ts_utc: str | None = None
    last_mode: str | None = None

    for c in coverages:
        la = c.last_attempt

        # Latest run timestamp (max)
        rt = la.run_ts
        if last_run_ts is None or rt > last_run_ts:
            last_run_ts = rt
            last_run_ts_utc = la.run_ts_utc
            last_mode = la.mode

        # Descriptors
        if la.is_empty:
            contracts_empty_expected += 1
        if la.vendor_final:
            contracts_vendor_final += 1

        # Canonical truth
        is_complete = bool(c.windows.complete)
        if is_complete:
            contracts_complete += 1
        else:
            incomplete_keys.append(c.contract_key)

        # Blockers / error signals (facts + contradictions)
        st = la.status

        if st == AttemptStatus.unmapped:
            contracts_unmapped += 1
            unmapped_keys.append(c.contract_key)

        if st == AttemptStatus.skipped_cost_cap:
            contracts_blocked_cost += 1

        contradiction_complete = (
            st == AttemptStatus.complete and (not is_complete) and (not la.vendor_final)
        )
        if st == AttemptStatus.error or contradiction_complete:
            contracts_error += 1
            error_keys.append(c.contract_key)

    contracts_incomplete = total - contracts_complete

    # -------------------------
    # Roll-up status (authoritative precedence)
    # -------------------------
    status = compute_product_status(coverages)

    # Stable reason strings (avoid smuggling new semantics)
    if status == ProductStatus.never_run:
        reason = "no attempts recorded for product"
    elif status == ProductStatus.done:
        reason = "all contracts windows.complete and no blockers/errors"
    elif status == ProductStatus.error:
        reason = "one or more contracts error or contradictory completeness"
    elif status == ProductStatus.blocked:
        reason = "one or more contracts blocked (unmapped or cost cap) and no errors"
    else:
        reason = "some contracts incomplete and no blockers/errors"

    summary = ProductCoverageSummary(
        product_id=product_id,
        status=status,
        status_reason=reason,
        contracts_total=total,
        contracts_complete=contracts_complete,
        contracts_incomplete=contracts_incomplete,
        contracts_empty_expected=contracts_empty_expected,
        contracts_vendor_final=contracts_vendor_final,
        contracts_unmapped=contracts_unmapped,
        contracts_error=contracts_error,
        contracts_blocked_cost=contracts_blocked_cost,
        last_run_ts_utc=last_run_ts_utc,
        last_mode=last_mode,
        incomplete_contract_keys=tuple(incomplete_keys),
        error_contract_keys=tuple(error_keys),
        unmapped_contract_keys=tuple(unmapped_keys),
    )

    # Stable ordering (nice for reports)
    coverages_sorted = tuple(sorted(coverages, key=lambda x: x.contract_key))
    return ProductCoverageReport(summary=summary, contracts=coverages_sorted)
