"""
System-level inspection rollups for statistics_1d attempts.

This module is part of the *inspection* layer. It is intentionally read-only and
exists to aggregate product-level inspection models into a simple system-wide
report.

Normative constraints (MXM V1):
- MUST NOT read dataset payloads (no parquet reads).
- MUST NOT implement event-stream semantics (settlement selection, final tie-breaking, etc.).
- Product status semantics MUST be delegated to inspect/statistics_1d/product.py.

Design notes:
- Product ordering in the returned report is stable by product_id (sorted).
- This report is "freshness-ish": last_run_ts reflects the most recent attempt recorded
  per product, not live vendor staleness.
"""

from __future__ import annotations

# mxm/v1/marketdata/inspect/statistics_1d/system.py
from dataclasses import dataclass

import pandas as pd

from mxm.v1.marketdata.datasets.statistics_1d.attempts_store import (
    Statistics1DAttemptsStore,
)
from mxm.v1.marketdata.inspect.models import ProductStatus
from mxm.v1.marketdata.inspect.statistics_1d.product import get_product_attempts_report
from mxm.v1.utils.time_utils import parse_ts


@dataclass(frozen=True)
class SystemProductRow:
    product_id: str

    status: ProductStatus
    status_reason: str

    contracts_total: int
    contracts_ok_terminal: int
    contracts_incomplete: int
    contracts_empty_expected: int
    contracts_vendor_final: int
    contracts_unmapped: int
    contracts_blocked_cost: int
    contracts_error: int

    last_run_ts_utc: str | None
    last_mode: str | None

    @property
    def last_run_ts(self) -> pd.Timestamp | None:
        return parse_ts(self.last_run_ts_utc) if self.last_run_ts_utc else None


@dataclass(frozen=True)
class SystemSummary:
    products_total: int
    products_never_run: int
    products_done: int
    products_partial: int
    products_blocked: int
    products_error: int

    contracts_total: int
    contracts_ok_terminal: int
    contracts_incomplete: int
    contracts_unmapped: int
    contracts_blocked_cost: int
    contracts_error: int


@dataclass(frozen=True)
class SystemAttemptsReport:
    summary: SystemSummary
    products: tuple[SystemProductRow, ...]


def get_system_attempts_report(
    *, attempts: Statistics1DAttemptsStore
) -> SystemAttemptsReport:
    """
    System-wide read-only rollup across products.

    Single semantic authority:
    - Per-product status and counts are delegated to get_product_attempts_report().
    """
    product_ids = attempts.list_products_with_attempts()
    if not product_ids:
        summary = SystemSummary(
            products_total=0,
            products_never_run=0,
            products_done=0,
            products_partial=0,
            products_blocked=0,
            products_error=0,
            contracts_total=0,
            contracts_ok_terminal=0,
            contracts_incomplete=0,
            contracts_unmapped=0,
            contracts_blocked_cost=0,
            contracts_error=0,
        )
        return SystemAttemptsReport(summary=summary, products=())

    rows: list[SystemProductRow] = []

    # system aggregates (contracts)
    c_total = 0
    c_ok_terminal = 0
    c_incomplete = 0
    c_unmapped = 0
    c_blocked_cost = 0
    c_error = 0

    # system aggregates (products)
    p_never = 0
    p_done = 0
    p_partial = 0
    p_blocked = 0
    p_error = 0

    for pid in sorted(product_ids):
        pr = get_product_attempts_report(attempts=attempts, product_id=pid)
        s = pr.summary

        rows.append(
            SystemProductRow(
                product_id=pid,
                status=s.status,
                status_reason=s.status_reason,
                contracts_total=s.contracts_total,
                contracts_ok_terminal=s.contracts_ok_terminal,
                contracts_incomplete=s.contracts_incomplete,
                contracts_empty_expected=s.contracts_empty_expected,
                contracts_vendor_final=s.contracts_vendor_final,
                contracts_unmapped=s.contracts_unmapped,
                contracts_blocked_cost=s.contracts_blocked_cost,
                contracts_error=s.contracts_error,
                last_run_ts_utc=s.last_run_ts_utc,
                last_mode=s.last_mode,
            )
        )

        # contract totals
        c_total += int(s.contracts_total)
        c_ok_terminal += int(s.contracts_ok_terminal)
        c_incomplete += int(s.contracts_incomplete)
        c_unmapped += int(s.contracts_unmapped)
        c_blocked_cost += int(s.contracts_blocked_cost)
        c_error += int(s.contracts_error)

        # product distribution
        if s.status == ProductStatus.never_run:
            p_never += 1
        elif s.status == ProductStatus.done:
            p_done += 1
        elif s.status == ProductStatus.partial:
            p_partial += 1
        elif s.status == ProductStatus.blocked:
            p_blocked += 1
        elif s.status == ProductStatus.error:
            p_error += 1
        else:
            raise RuntimeError(
                f"unhandled ProductStatus={s.status!r} for product_id={pid!r}"
            )

    summary = SystemSummary(
        products_total=len(rows),
        products_never_run=p_never,
        products_done=p_done,
        products_partial=p_partial,
        products_blocked=p_blocked,
        products_error=p_error,
        contracts_total=c_total,
        contracts_ok_terminal=c_ok_terminal,
        contracts_incomplete=c_incomplete,
        contracts_unmapped=c_unmapped,
        contracts_blocked_cost=c_blocked_cost,
        contracts_error=c_error,
    )

    return SystemAttemptsReport(summary=summary, products=tuple(rows))
