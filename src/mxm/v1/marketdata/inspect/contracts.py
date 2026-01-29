# mxm/v1/marketdata/inspect/contracts.py
from __future__ import annotations

import pandas as pd

from mxm.v1.marketdata.datasets.ohlcv_1d.attempts_store import (
    OHLCV1DAttemptRow,
    OHLCV1DAttemptsStore,
)
from mxm.v1.marketdata.inspect.models import (
    AttemptSummary,
    ContractCoverage,
    CoverageSurfaces,
    CoverageWindows,
    DayRange,
    ObservedRange,
)
from mxm.v1.marketdata.time_utils import ensure_midnight_utc, parse_ts

# -------------------------
# Public API
# -------------------------


def get_latest_attempt_for_contract_key(
    *, attempts: OHLCV1DAttemptsStore, contract_key: str
) -> OHLCV1DAttemptRow | None:
    return attempts.get_latest_attempt_for_contract_key(contract_key=contract_key)


def list_latest_attempts_for_product(
    *, attempts: OHLCV1DAttemptsStore, product_id: str
) -> list[OHLCV1DAttemptRow]:
    return attempts.list_latest_attempts_for_product(product_id=product_id)


def get_contract_coverage_from_latest_attempt(
    *, attempts: OHLCV1DAttemptsStore, contract_key: str
) -> ContractCoverage | None:
    row = get_latest_attempt_for_contract_key(
        attempts=attempts, contract_key=contract_key
    )
    if row is None:
        return None
    return contract_coverage_from_attempt_row(row)


def list_contract_coverages_for_product(
    *, attempts: OHLCV1DAttemptsStore, product_id: str
) -> list[ContractCoverage]:
    rows = list_latest_attempts_for_product(attempts=attempts, product_id=product_id)
    return [contract_coverage_from_attempt_row(r) for r in rows]


# -------------------------
# Row -> model mapping
# -------------------------


def contract_coverage_from_attempt_row(row: OHLCV1DAttemptRow) -> ContractCoverage:
    # Identity
    product_id = row.product_id
    contract_id = row.contract_id
    contract_key = row.contract_key

    dataset = row.dataset or ""
    publisher_id = row.publisher_id
    instrument_id = row.instrument_id
    raw_symbol = row.raw_symbol

    # Surfaces (all day-aligned UTC-midnight, half-open)
    interest = DayRange(
        start=_parse_day_ts(row.interest_start),
        end=_parse_day_ts(row.interest_end),
    )
    dataset_range = DayRange(
        start=_parse_day_ts(row.dataset_start),
        end=_parse_day_ts(row.dataset_end),
    )

    lifecycle: DayRange | None = None
    if row.activation_floor is not None and row.expiration_ceiling is not None:
        a = _parse_day_ts(row.activation_floor)
        e = _parse_day_ts(row.expiration_ceiling)
        if a < e:
            lifecycle = DayRange(start=a, end=e)

    surfaces = CoverageSurfaces(
        interest=interest,
        dataset=dataset_range,
        lifecycle=lifecycle,
    )

    # Available is dataset ∩ lifecycle if lifecycle known, else dataset
    available = (
        dataset_range if lifecycle is None else dataset_range.intersection(lifecycle)
    )

    # Expected: TRUST the persisted attempt row (handles empty windows cleanly)

    try:
        expected = DayRange(
            start=_parse_day_ts(row.expected_start),
            end=_parse_day_ts(row.expected_end),
        )
    except ValueError as e:
        raise ValueError(
            "Invalid expected window in attempts row (likely empty with start==end). "
            "Either allow empty DayRange (recommended) or change how expected windows are persisted. "
            f"contract_key={row.contract_key!r} expected_start={row.expected_start!r} expected_end={row.expected_end!r} "
            f"is_empty={row.is_empty!r}"
        ) from e

    # Stored snapshot (effective): prefer after, else before
    stored_rows = (
        row.stored_rows_after
        if row.stored_rows_after is not None
        else row.stored_rows_before
    )
    stored_min_s = (
        row.stored_min_after
        if row.stored_min_after is not None
        else row.stored_min_before
    )
    stored_max_s = (
        row.stored_max_after
        if row.stored_max_after is not None
        else row.stored_max_before
    )

    row_count = int(stored_rows or 0)
    stored_min = _parse_ts_or_none(stored_min_s)
    stored_max = _parse_ts_or_none(stored_max_s)

    stored_observed: ObservedRange | None = None
    stored_window: DayRange | None = None
    if stored_min is not None and stored_max is not None and row_count > 0:
        stored_observed = ObservedRange(min_ts=stored_min, max_ts=stored_max)
        stored_window = stored_observed.to_day_window()

    windows = CoverageWindows(
        available=available,
        expected=expected,
        stored_observed=stored_observed,
        stored_window=stored_window,
        row_count=row_count,
    )

    last_attempt = AttemptSummary(
        attempt_uid=row.attempt_uid,
        run_ts_utc=_parse_ts(row.run_ts_utc),
        mode=row.mode,
        dry_run=bool(row.dry_run),
        status=row.status,
        status_detail=row.status_detail,
        cost_cap_usd=getattr(row, "cost_cap_usd", None),
        cost_estimated_usd=getattr(row, "cost_estimated_usd", None),
        cost_charged_usd=None,
        cost_used_usd=None,
        error_type=row.error_type,
        error_message=row.error_message,
        is_empty=row.is_empty,
        vendor_final=row.vendor_final,
    )

    return ContractCoverage(
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


def _parse_ts(v: str) -> pd.Timestamp:
    # parse_ts already returns tz-aware UTC
    return parse_ts(v)


def _parse_ts_or_none(v: str | None) -> pd.Timestamp | None:
    if v is None or v == "":
        return None
    return parse_ts(v)


def _parse_day_ts(v: str) -> pd.Timestamp:
    # enforce midnight invariant
    return ensure_midnight_utc(parse_ts(v))
