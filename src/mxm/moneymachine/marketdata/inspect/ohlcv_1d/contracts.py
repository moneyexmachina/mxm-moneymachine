"""
Inspection adapter for contract-level OHLCV-1D coverage.

This module is part of the *inspection* layer. It is intentionally read-only and
exists to project persisted attempt-ledger rows into inspection view models.

Normative constraints (mxm-moneymachine):
- This module MUST NOT implement coverage or completeness logic.
  All coverage semantics are defined in:
      mxm.moneymachine.marketdata.datasets.ohlcv_1d.coverage
- This module MUST NOT perform its own timestamp / day-boundary manipulation.
  Time normalization is delegated to the dataset semantic layer and/or stores.
- Status fields (status, status_detail, vendor_final, is_empty) are treated as
  authoritative facts from the attempts ledger and are never inferred.

Responsibilities:
- Query the attempts store for the latest attempt rows per contract.
- Convert each row into a ContractCoverage view model by delegating coverage
  construction to coverage.coverage_from_attempt_row.

Non-responsibilities:
- No I/O beyond the attempts store read API.
- No re-derivation of expected/available/stored windows.
- No policy decisions (retry, bootstrap/update, cost gating, etc.).
"""

from __future__ import annotations

from mxm.moneymachine.marketdata.datasets.ohlcv_1d.attempts_store import (
    OHLCV1DAttemptRow,
    OHLCV1DAttemptsStore,
)
from mxm.moneymachine.marketdata.datasets.ohlcv_1d.coverage import (
    coverage_from_attempt_row,
)
from mxm.moneymachine.marketdata.inspect.models import (
    AttemptStatus,
    AttemptSummary,
)
from mxm.moneymachine.marketdata.inspect.ohlcv_1d.models import OHLCV1DContractCoverage

# -------------------------
# Public API
# -------------------------


def get_contract_coverage_from_latest_attempt(
    *, attempts: OHLCV1DAttemptsStore, contract_key: str
) -> OHLCV1DContractCoverage | None:
    row = attempts.get_latest_attempt_for_contract_key(contract_key=contract_key)
    if row is None:
        return None
    return contract_coverage_from_attempt_row(row)


def list_contract_coverages_for_product(
    *, attempts: OHLCV1DAttemptsStore, product_id: str
) -> list[OHLCV1DContractCoverage]:
    rows = attempts.list_latest_attempts_for_product(product_id=product_id)
    return [contract_coverage_from_attempt_row(r) for r in rows]


# -------------------------
# Row -> model mapping
# -------------------------


def contract_coverage_from_attempt_row(
    row: OHLCV1DAttemptRow,
) -> OHLCV1DContractCoverage:
    """
    Project a persisted attempt row into the inspection ContractCoverage model.

    All coverage semantics (surfaces/windows/completeness) are delegated to the
    canonical builder in coverage.py.
    """
    # Identity
    product_id = row.product_id
    contract_id = row.contract_id
    contract_key = row.contract_key

    dataset = row.dataset  # preserve None if missing; do not coerce to ""
    publisher_id = row.publisher_id
    instrument_id = row.instrument_id
    raw_symbol = row.raw_symbol

    # Canonical coverage semantics (no reinvention here)
    surfaces, windows = coverage_from_attempt_row(row)

    # Attempt summary (pure representation; no inference)
    last_attempt = AttemptSummary(
        attempt_uid=row.attempt_uid,
        run_ts_utc=row.run_ts_utc,
        mode=row.mode,
        dry_run=bool(row.dry_run),
        status=AttemptStatus(row.status),
        status_detail=row.status_detail,
        cost_cap_usd=getattr(row, "cost_cap_usd", None),
        cost_estimated_usd=getattr(row, "cost_estimated_usd", None),
        cost_charged_usd=getattr(row, "cost_charged_usd", None),
        cost_used_usd=getattr(row, "cost_used_usd", None),
        error_type=row.error_type,
        error_message=row.error_message,
        is_empty=row.is_empty,
        vendor_final=row.vendor_final,
    )

    return OHLCV1DContractCoverage(
        product_id=product_id,
        contract_id=contract_id,
        contract_key=contract_key,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        raw_symbol=raw_symbol,
        surfaces=surfaces,
        windows=windows,
        last_attempt=last_attempt,
    )
