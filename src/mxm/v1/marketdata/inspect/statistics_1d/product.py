# mxm/v1/marketdata/inspect/statistics_1d/product.py
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from mxm.v1.marketdata.datasets.statistics_1d.attempts_store import (
    Statistics1DAttemptsStore,
)
from mxm.v1.marketdata.inspect.models import AttemptStatus, ProductStatus
from mxm.v1.marketdata.inspect.statistics_1d.contracts import (
    Statistics1DContractAttempt,
    list_contract_attempts_for_product,
)
from mxm.v1.utils.time_utils import parse_ts


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

    Normative discipline:
    - Only attempt-ledger facts are used.
    - No event-stream reads.
    - status_detail is not used for bucketing.
    """
    contract_attempts = list_contract_attempts_for_product(
        attempts=attempts, product_id=product_id
    )

    if len(contract_attempts) == 0:
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

    # -------------------------
    # Aggregate counts + drilldowns
    # -------------------------
    total = len(contract_attempts)

    c_ok_terminal = 0
    c_incomplete = 0
    c_empty_expected = 0
    c_vendor_final = 0
    c_unmapped = 0
    c_error = 0
    c_blocked_cost = 0

    incomplete_keys: list[str] = []
    error_keys: list[str] = []
    unmapped_keys: list[str] = []
    blocked_cost_keys: list[str] = []
    empty_expected_keys: list[str] = []

    last_run_ts: pd.Timestamp | None = None
    last_run_ts_utc: str | None = None
    last_mode: str | None = None

    for ca in contract_attempts:
        la = ca.last_attempt
        st = la.status

        # Latest run timestamp (max)
        rt = la.run_ts
        if last_run_ts is None or rt > last_run_ts:
            last_run_ts = rt
            last_run_ts_utc = la.run_ts_utc
            last_mode = la.mode

        # Persisted descriptors
        if la.is_empty:
            c_empty_expected += 1
            empty_expected_keys.append(ca.contract_key)
        if la.vendor_final:
            c_vendor_final += 1

        # Status buckets
        if _is_ok_terminal(st):
            c_ok_terminal += 1

        if _is_incomplete(st):
            c_incomplete += 1
            incomplete_keys.append(ca.contract_key)

        if st == AttemptStatus.unmapped:
            c_unmapped += 1
            unmapped_keys.append(ca.contract_key)

        if st == AttemptStatus.skipped_cost_cap:
            c_blocked_cost += 1
            blocked_cost_keys.append(ca.contract_key)

        if _is_error(st):
            c_error += 1
            error_keys.append(ca.contract_key)

    # -------------------------
    # Roll-up status (authoritative precedence)
    # -------------------------
    status = compute_product_status(contract_attempts)

    if status == ProductStatus.never_run:
        reason = "no attempts recorded for product"
    elif status == ProductStatus.done:
        reason = "all contracts terminal with no incomplete, blockers, or errors"
    elif status == ProductStatus.error:
        reason = "one or more contracts error"
    elif status == ProductStatus.blocked:
        reason = "one or more contracts blocked (unmapped or cost cap) and no errors"
    else:
        reason = "some contracts non-terminal (e.g. incomplete) and no blockers/errors"

    summary = ProductAttemptsSummary(
        product_id=product_id,
        status=status,
        status_reason=reason,
        contracts_total=total,
        contracts_ok_terminal=c_ok_terminal,
        contracts_incomplete=c_incomplete,
        contracts_empty_expected=c_empty_expected,
        contracts_vendor_final=c_vendor_final,
        contracts_unmapped=c_unmapped,
        contracts_error=c_error,
        contracts_blocked_cost=c_blocked_cost,
        last_run_ts_utc=last_run_ts_utc,
        last_mode=last_mode,
        incomplete_contract_keys=tuple(incomplete_keys),
        error_contract_keys=tuple(error_keys),
        unmapped_contract_keys=tuple(unmapped_keys),
        blocked_cost_contract_keys=tuple(blocked_cost_keys),
        empty_expected_contract_keys=tuple(empty_expected_keys),
    )

    # Stable ordering (nice for reports)
    contracts_sorted = tuple(sorted(contract_attempts, key=lambda x: x.contract_key))
    return ProductAttemptsReport(summary=summary, contracts=contracts_sorted)
