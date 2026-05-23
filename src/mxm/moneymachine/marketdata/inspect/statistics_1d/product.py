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

from collections.abc import Iterable
from dataclasses import dataclass, field

import pandas as pd

from mxm.moneymachine.marketdata.datasets.statistics_1d.attempts_store import (
    Statistics1DAttemptsStore,
)
from mxm.moneymachine.marketdata.inspect.models import AttemptStatus, ProductStatus
from mxm.moneymachine.marketdata.inspect.statistics_1d.contracts import (
    Statistics1DContractAttempt,
    list_contract_attempts_for_product,
)
from mxm.moneymachine.utils.time_utils import parse_ts


@dataclass(frozen=True)
class ProductAttemptsSummary:
    product_id: str

    # Status roll-up
    status: ProductStatus
    status_reason: str

    # Counts
    contracts_total: int
    contracts_ok_terminal: int
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
    blocked_cost_contract_keys: tuple[str, ...]
    empty_expected_contract_keys: tuple[str, ...]

    @property
    def last_run_ts(self) -> pd.Timestamp | None:
        return parse_ts(self.last_run_ts_utc) if self.last_run_ts_utc else None


@dataclass(frozen=True)
class ProductAttemptsReport:
    summary: ProductAttemptsSummary
    contracts: tuple[Statistics1DContractAttempt, ...]


def _is_blocked(st: AttemptStatus) -> bool:
    return st in (AttemptStatus.unmapped, AttemptStatus.skipped_cost_cap)


def _is_error(st: AttemptStatus) -> bool:
    return st == AttemptStatus.error


def _is_incomplete(st: AttemptStatus) -> bool:
    # Conservative: treat explicit 'incomplete' as non-terminal.
    return st == AttemptStatus.incomplete


def _is_ok_terminal(st: AttemptStatus) -> bool:
    """
    Attempt statuses that indicate the orchestrator reached a terminal conclusion
    without error/block.
    """
    if _is_error(st) or _is_blocked(st):
        return False
    # Treat everything else as "ok terminal", including:
    # complete, ingested, skipped_empty_expected_window, dry_run, etc.
    return True


def _empty_str_list() -> list[str]:
    return []


@dataclass
class ProductAttemptsAggregation:
    contracts_total: int = 0
    contracts_ok_terminal: int = 0
    contracts_incomplete: int = 0
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
    blocked_cost_contract_keys: list[str] = field(default_factory=_empty_str_list)
    empty_expected_contract_keys: list[str] = field(default_factory=_empty_str_list)


def compute_product_status(
    contract_attempts: Iterable[Statistics1DContractAttempt],
) -> ProductStatus:
    """
    Authoritative statistics_1d product status precedence (MVP):

      1) never_run if no attempts exist
      2) error if any contract has status=error
      3) blocked if any contract is unmapped or cost-blocked and no errors
      4) done if all contracts are ok-terminal AND none are incomplete
      5) partial otherwise

    Notes:
    - We intentionally do NOT use any event-stream completeness semantics here.
    - 'incomplete' is treated as meaningfully non-terminal for MVP.
      If you decide later that statistics can be "done" despite incomplete statuses,
      change the 'done' condition accordingly.
    """
    attempts = list(contract_attempts)
    if len(attempts) == 0:
        return ProductStatus.never_run

    any_error = False
    any_blocked = False
    any_incomplete = False
    all_ok_terminal = True

    for ca in attempts:
        st = ca.last_attempt.status

        if _is_error(st):
            any_error = True
        if _is_blocked(st):
            any_blocked = True
        if _is_incomplete(st):
            any_incomplete = True
        if not _is_ok_terminal(st):
            all_ok_terminal = False

    if any_error:
        return ProductStatus.error
    if any_blocked:
        return ProductStatus.blocked

    # Conservative done criterion
    if all_ok_terminal and not any_incomplete:
        return ProductStatus.done

    return ProductStatus.partial


# -------------------------
# Public API
# -------------------------


def get_product_attempts_report(
    *, attempts: Statistics1DAttemptsStore, product_id: str
) -> ProductAttemptsReport:
    """
    Read-only attempts report for a product, based on the latest attempt per contract_key.
    """
    contract_attempts = list_contract_attempts_for_product(
        attempts=attempts,
        product_id=product_id,
    )

    if len(contract_attempts) == 0:
        return _empty_product_attempts_report(product_id)

    aggregation = _aggregate_product_attempts(contract_attempts)
    status = compute_product_status(contract_attempts)
    summary = _build_product_attempts_summary(
        product_id=product_id,
        status=status,
        status_reason=_product_status_reason(status),
        aggregation=aggregation,
    )

    return ProductAttemptsReport(
        summary=summary,
        contracts=_sort_contract_attempts(contract_attempts),
    )


def _empty_product_attempts_report(product_id: str) -> ProductAttemptsReport:
    summary = ProductAttemptsSummary(
        product_id=product_id,
        status=ProductStatus.never_run,
        status_reason="no attempts recorded for product",
        contracts_total=0,
        contracts_ok_terminal=0,
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
        blocked_cost_contract_keys=(),
        empty_expected_contract_keys=(),
    )
    return ProductAttemptsReport(summary=summary, contracts=())


def _aggregate_product_attempts(
    contract_attempts: list[Statistics1DContractAttempt],
) -> ProductAttemptsAggregation:
    aggregation = ProductAttemptsAggregation(contracts_total=len(contract_attempts))

    for contract_attempt in contract_attempts:
        _aggregate_contract_attempt(
            aggregation=aggregation,
            contract_attempt=contract_attempt,
        )

    return aggregation


def _aggregate_contract_attempt(
    *,
    aggregation: ProductAttemptsAggregation,
    contract_attempt: Statistics1DContractAttempt,
) -> None:
    last_attempt = contract_attempt.last_attempt
    status = last_attempt.status

    _aggregate_latest_run_metadata(
        aggregation=aggregation,
        contract_attempt=contract_attempt,
    )
    _aggregate_persisted_descriptors(
        aggregation=aggregation,
        contract_attempt=contract_attempt,
    )
    _aggregate_status_buckets(
        aggregation=aggregation,
        contract_attempt=contract_attempt,
        status=status,
    )


def _aggregate_latest_run_metadata(
    *,
    aggregation: ProductAttemptsAggregation,
    contract_attempt: Statistics1DContractAttempt,
) -> None:
    last_attempt = contract_attempt.last_attempt

    if (
        aggregation.last_run_ts is not None
        and last_attempt.run_ts <= aggregation.last_run_ts
    ):
        return

    aggregation.last_run_ts = last_attempt.run_ts
    aggregation.last_run_ts_utc = last_attempt.run_ts_utc
    aggregation.last_mode = last_attempt.mode


def _aggregate_persisted_descriptors(
    *,
    aggregation: ProductAttemptsAggregation,
    contract_attempt: Statistics1DContractAttempt,
) -> None:
    last_attempt = contract_attempt.last_attempt

    if last_attempt.is_empty:
        aggregation.contracts_empty_expected += 1
        aggregation.empty_expected_contract_keys.append(contract_attempt.contract_key)

    if last_attempt.vendor_final:
        aggregation.contracts_vendor_final += 1


def _aggregate_status_buckets(
    *,
    aggregation: ProductAttemptsAggregation,
    contract_attempt: Statistics1DContractAttempt,
    status: AttemptStatus,
) -> None:
    if _is_ok_terminal(status):
        aggregation.contracts_ok_terminal += 1

    if _is_incomplete(status):
        aggregation.contracts_incomplete += 1
        aggregation.incomplete_contract_keys.append(contract_attempt.contract_key)

    if status == AttemptStatus.unmapped:
        aggregation.contracts_unmapped += 1
        aggregation.unmapped_contract_keys.append(contract_attempt.contract_key)

    if status == AttemptStatus.skipped_cost_cap:
        aggregation.contracts_blocked_cost += 1
        aggregation.blocked_cost_contract_keys.append(contract_attempt.contract_key)

    if _is_error(status):
        aggregation.contracts_error += 1
        aggregation.error_contract_keys.append(contract_attempt.contract_key)


def _product_status_reason(status: ProductStatus) -> str:
    if status == ProductStatus.never_run:
        return "no attempts recorded for product"

    if status == ProductStatus.done:
        return "all contracts terminal with no incomplete, blockers, or errors"

    if status == ProductStatus.error:
        return "one or more contracts error"

    if status == ProductStatus.blocked:
        return "one or more contracts blocked (unmapped or cost cap) and no errors"

    return "some contracts non-terminal (e.g. incomplete) and no blockers/errors"


def _build_product_attempts_summary(
    *,
    product_id: str,
    status: ProductStatus,
    status_reason: str,
    aggregation: ProductAttemptsAggregation,
) -> ProductAttemptsSummary:
    return ProductAttemptsSummary(
        product_id=product_id,
        status=status,
        status_reason=status_reason,
        contracts_total=aggregation.contracts_total,
        contracts_ok_terminal=aggregation.contracts_ok_terminal,
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
        blocked_cost_contract_keys=tuple(aggregation.blocked_cost_contract_keys),
        empty_expected_contract_keys=tuple(aggregation.empty_expected_contract_keys),
    )


def _sort_contract_attempts(
    contract_attempts: list[Statistics1DContractAttempt],
) -> tuple[Statistics1DContractAttempt, ...]:
    return tuple(sorted(contract_attempts, key=lambda x: x.contract_key))
