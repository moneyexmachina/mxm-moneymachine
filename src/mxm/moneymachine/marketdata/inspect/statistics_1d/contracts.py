"""
Inspection adapter for contract-level statistics_1d attempts.

This module is part of the *inspection* layer. It is intentionally read-only and
exists to project persisted attempt-ledger rows into inspection view models.

Normative constraints (MXM V1):
- MUST NOT read dataset payloads (no parquet reads).
- MUST NOT implement event-stream semantics (settlement selection, final tie-breaking, etc.).
- Status fields (status, status_detail, vendor_final, is_empty) are treated as authoritative
  facts from the attempts ledger and are never inferred.

Responsibilities:
- Query the attempts store for latest attempt rows per contract_key.
- Convert rows into inspection view models for operator drilldown.

Non-responsibilities:
- No completeness logic beyond persisted expected-window facts.
"""

from __future__ import annotations

from dataclasses import dataclass

from mxm.moneymachine.marketdata.datasets.statistics_1d.attempts_store import (
    Statistics1DAttemptRow,
    Statistics1DAttemptsStore,
)
from mxm.moneymachine.marketdata.inspect.models import AttemptStatus, AttemptSummary

# -------------------------
# View models (attempt-ledger shaped)
# -------------------------


@dataclass(frozen=True)
class Statistics1DSurfaces:
    """
    Persisted surfaces for the attempt row.

    All fields are ISO8601Z strings; semantics are defined by the statistics_1d dataset layer.
    """

    interest_start: str
    interest_end: str
    dataset_start: str
    dataset_end: str
    activation_floor: str | None
    expiration_ceiling: str | None


@dataclass(frozen=True)
class Statistics1DExpectedWindow:
    """
    Persisted expected window (intersection).

    expected_* are ISO8601Z strings, day-aligned, half-open [start,end).
    """

    expected_start: str
    expected_end: str
    is_empty: bool

    is_vendor_limited: bool
    is_lifecycle_limited: bool


@dataclass(frozen=True)
class Statistics1DStoredSnapshot:
    """
    Persisted stored coverage snapshot (before or after an attempt).

    stored_min/max are canonical strings (as persisted); meaning is dataset-specific.
    """

    stored_rows: int | None
    stored_min: str | None
    stored_max: str | None
    stats_path: str | None


@dataclass(frozen=True)
class Statistics1DContractAttempt:
    """
    Contract-level inspection view for statistics_1d.

    This is intentionally attempt-ledger shaped (not event-stream shaped).
    """

    # Identity
    product_id: str
    contract_id: str
    contract_key: str

    feed: str | None
    dataset: str | None
    publisher_id: int | None
    instrument_id: int | None
    raw_symbol: str | None

    # Persisted attempt semantics
    surfaces: Statistics1DSurfaces
    expected: Statistics1DExpectedWindow
    vendor_final: bool

    # Stored snapshots (facts)
    stored_before: Statistics1DStoredSnapshot
    stored_after: Statistics1DStoredSnapshot

    # Attempt summary (facts)
    last_attempt: AttemptSummary


# -------------------------
# Public API
# -------------------------


def get_contract_attempt_from_latest_attempt(
    *, attempts: Statistics1DAttemptsStore, contract_key: str
) -> Statistics1DContractAttempt | None:
    row = attempts.get_latest_attempt_for_contract_key(contract_key=contract_key)
    if row is None:
        return None
    return contract_attempt_from_attempt_row(row)


def list_contract_attempts_for_product(
    *, attempts: Statistics1DAttemptsStore, product_id: str
) -> list[Statistics1DContractAttempt]:
    rows = attempts.list_latest_attempts_for_product(product_id=product_id)
    return [contract_attempt_from_attempt_row(r) for r in rows]


# -------------------------
# Row -> model mapping
# -------------------------


def contract_attempt_from_attempt_row(
    row: Statistics1DAttemptRow,
) -> Statistics1DContractAttempt:
    # Identity
    product_id = row.product_id
    contract_id = row.contract_id
    contract_key = row.contract_key

    feed = row.feed
    dataset = row.dataset
    publisher_id = row.publisher_id
    instrument_id = row.instrument_id
    raw_symbol = row.raw_symbol

    # Persisted surfaces + expected window (facts)
    surfaces = Statistics1DSurfaces(
        interest_start=row.interest_start,
        interest_end=row.interest_end,
        dataset_start=row.dataset_start,
        dataset_end=row.dataset_end,
        activation_floor=row.activation_floor,
        expiration_ceiling=row.expiration_ceiling,
    )
    expected = Statistics1DExpectedWindow(
        expected_start=row.expected_start,
        expected_end=row.expected_end,
        is_empty=bool(row.is_empty),
        is_vendor_limited=bool(row.is_vendor_limited),
        is_lifecycle_limited=bool(row.is_lifecycle_limited),
    )

    # Stored snapshots (facts)
    stored_before = Statistics1DStoredSnapshot(
        stored_rows=row.stored_rows_before,
        stored_min=row.stored_min_before,
        stored_max=row.stored_max_before,
        stats_path=row.stats_path_before,
    )
    stored_after = Statistics1DStoredSnapshot(
        stored_rows=row.stored_rows_after,
        stored_min=row.stored_min_after,
        stored_max=row.stored_max_after,
        stats_path=row.stats_path_after,
    )

    # Attempt summary (facts)
    last_attempt = AttemptSummary(
        attempt_uid=row.attempt_uid,
        run_ts_utc=row.run_ts_utc,
        mode=row.mode,
        dry_run=bool(row.dry_run),
        status=AttemptStatus(row.status),
        status_detail=row.status_detail,
        cost_cap_usd=row.cost_cap_usd,
        cost_estimated_usd=row.cost_estimated_usd,
        cost_used_usd=row.cost_used_usd,
        cost_charged_usd=row.cost_charged_usd,
        error_type=row.error_type,
        error_message=row.error_message,
        is_empty=bool(row.is_empty),
        vendor_final=bool(row.vendor_final),
    )

    return Statistics1DContractAttempt(
        product_id=product_id,
        contract_id=contract_id,
        contract_key=contract_key,
        feed=feed,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        raw_symbol=raw_symbol,
        surfaces=surfaces,
        expected=expected,
        vendor_final=bool(row.vendor_final),
        stored_before=stored_before,
        stored_after=stored_after,
        last_attempt=last_attempt,
    )
