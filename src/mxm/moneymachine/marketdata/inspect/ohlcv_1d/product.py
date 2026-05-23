# TODO(mxm-v1):
# inspect/ohlcv_1d/product.py and inspect/statistics_1d/product.py now share
# the same higher-level inspection/reporting structure:
#
# - enumerate latest per-contract inspection state
# - aggregate product-level counters and drilldown lists
# - derive authoritative product roll-up status via precedence rules
# - project stable reporting summaries
#
# The remaining differences are primarily:
# - completeness semantics
# - contradiction/error semantics
# - dataset-specific status buckets
#
# After MVP publication and CI stabilization, extract a generic product-level
# inspection aggregation/reporting framework parameterized by:
# - contract inspection model
# - aggregation policy
# - roll-up precedence semantics
# - summary projection rules
#
# Keep dataset-specific completeness truth and contradiction semantics external
# to the shared framework.

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from mxm.moneymachine.marketdata.datasets.ohlcv_1d.attempts_store import (
    OHLCV1DAttemptsStore,
)
from mxm.moneymachine.marketdata.inspect.models import (
    AttemptStatus,
    ProductStatus,
)
from mxm.moneymachine.marketdata.inspect.ohlcv_1d.contracts import (
    list_contract_coverages_for_product,
)
from mxm.moneymachine.marketdata.inspect.ohlcv_1d.models import OHLCV1DContractCoverage
from mxm.moneymachine.utils.time_utils import parse_ts


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


def _empty_str_list() -> list[str]:
    return []


@dataclass
class ProductCoverageAggregation:
    contracts_total: int = 0
    contracts_complete: int = 0
    contracts_empty_expected: int = 0
    contracts_vendor_final: int = 0
    contracts_unmapped: int = 0
    contracts_error: int = 0
    contracts_blocked_cost: int = 0

    last_run_ts: pd.Timestamp | None = None
    last_run_ts_utc: str | None = None
    last_mode: str | None = None

    incomplete_contract_keys: list[str] = field(default_factory=_empty_str_list)
    error_contract_keys: list[str] = field(default_factory=_empty_str_list)
    unmapped_contract_keys: list[str] = field(default_factory=_empty_str_list)

    @property
    def contracts_incomplete(self) -> int:
        return self.contracts_total - self.contracts_complete


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
    """
    coverages = list_contract_coverages_for_product(
        attempts=attempts,
        product_id=product_id,
    )

    if len(coverages) == 0:
        return _empty_product_coverage_report(product_id)

    aggregation = _aggregate_product_coverages(coverages)
    status = compute_product_status(coverages)

    summary = _build_product_coverage_summary(
        product_id=product_id,
        status=status,
        status_reason=_product_coverage_status_reason(status),
        aggregation=aggregation,
    )

    return ProductCoverageReport(
        summary=summary,
        contracts=_sort_contract_coverages(coverages),
    )


def _empty_product_coverage_report(product_id: str) -> ProductCoverageReport:
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


def _aggregate_product_coverages(
    coverages: list[OHLCV1DContractCoverage],
) -> ProductCoverageAggregation:
    aggregation = ProductCoverageAggregation(contracts_total=len(coverages))

    for coverage in coverages:
        _aggregate_contract_coverage(
            aggregation=aggregation,
            coverage=coverage,
        )

    return aggregation


def _aggregate_contract_coverage(
    *,
    aggregation: ProductCoverageAggregation,
    coverage: OHLCV1DContractCoverage,
) -> None:
    _aggregate_latest_run_metadata(
        aggregation=aggregation,
        coverage=coverage,
    )
    _aggregate_descriptors(
        aggregation=aggregation,
        coverage=coverage,
    )
    _aggregate_completeness(
        aggregation=aggregation,
        coverage=coverage,
    )
    _aggregate_blockers_and_errors(
        aggregation=aggregation,
        coverage=coverage,
    )


def _aggregate_latest_run_metadata(
    *,
    aggregation: ProductCoverageAggregation,
    coverage: OHLCV1DContractCoverage,
) -> None:
    last_attempt = coverage.last_attempt

    if (
        aggregation.last_run_ts is not None
        and last_attempt.run_ts <= aggregation.last_run_ts
    ):
        return

    aggregation.last_run_ts = last_attempt.run_ts
    aggregation.last_run_ts_utc = last_attempt.run_ts_utc
    aggregation.last_mode = last_attempt.mode


def _aggregate_descriptors(
    *,
    aggregation: ProductCoverageAggregation,
    coverage: OHLCV1DContractCoverage,
) -> None:
    last_attempt = coverage.last_attempt

    if last_attempt.is_empty:
        aggregation.contracts_empty_expected += 1

    if last_attempt.vendor_final:
        aggregation.contracts_vendor_final += 1


def _aggregate_completeness(
    *,
    aggregation: ProductCoverageAggregation,
    coverage: OHLCV1DContractCoverage,
) -> None:
    if bool(coverage.windows.complete):
        aggregation.contracts_complete += 1
        return

    aggregation.incomplete_contract_keys.append(coverage.contract_key)


def _aggregate_blockers_and_errors(
    *,
    aggregation: ProductCoverageAggregation,
    coverage: OHLCV1DContractCoverage,
) -> None:
    last_attempt = coverage.last_attempt
    status = last_attempt.status

    if status == AttemptStatus.unmapped:
        aggregation.contracts_unmapped += 1
        aggregation.unmapped_contract_keys.append(coverage.contract_key)

    if status == AttemptStatus.skipped_cost_cap:
        aggregation.contracts_blocked_cost += 1

    if _coverage_has_error_signal(coverage):
        aggregation.contracts_error += 1
        aggregation.error_contract_keys.append(coverage.contract_key)


def _coverage_has_error_signal(coverage: OHLCV1DContractCoverage) -> bool:
    last_attempt = coverage.last_attempt

    contradiction_complete = (
        last_attempt.status == AttemptStatus.complete
        and not bool(coverage.windows.complete)
        and not last_attempt.vendor_final
    )

    return last_attempt.status == AttemptStatus.error or contradiction_complete


def _product_coverage_status_reason(status: ProductStatus) -> str:
    if status == ProductStatus.never_run:
        return "no attempts recorded for product"

    if status == ProductStatus.done:
        return "all contracts windows.complete and no blockers/errors"

    if status == ProductStatus.error:
        return "one or more contracts error or contradictory completeness"

    if status == ProductStatus.blocked:
        return "one or more contracts blocked (unmapped or cost cap) and no errors"

    return "some contracts incomplete and no blockers/errors"


def _build_product_coverage_summary(
    *,
    product_id: str,
    status: ProductStatus,
    status_reason: str,
    aggregation: ProductCoverageAggregation,
) -> ProductCoverageSummary:
    return ProductCoverageSummary(
        product_id=product_id,
        status=status,
        status_reason=status_reason,
        contracts_total=aggregation.contracts_total,
        contracts_complete=aggregation.contracts_complete,
        contracts_incomplete=aggregation.contracts_incomplete,
        contracts_empty_expected=aggregation.contracts_empty_expected,
        contracts_vendor_final=aggregation.contracts_vendor_final,
        contracts_unmapped=aggregation.contracts_unmapped,
        contracts_error=aggregation.contracts_error,
        contracts_blocked_cost=aggregation.contracts_blocked_cost,
        last_run_ts_utc=aggregation.last_run_ts_utc,
        last_mode=aggregation.last_mode,
        incomplete_contract_keys=tuple(aggregation.incomplete_contract_keys),
        error_contract_keys=tuple(aggregation.error_contract_keys),
        unmapped_contract_keys=tuple(aggregation.unmapped_contract_keys),
    )


def _sort_contract_coverages(
    coverages: list[OHLCV1DContractCoverage],
) -> tuple[OHLCV1DContractCoverage, ...]:
    return tuple(sorted(coverages, key=lambda x: x.contract_key))
