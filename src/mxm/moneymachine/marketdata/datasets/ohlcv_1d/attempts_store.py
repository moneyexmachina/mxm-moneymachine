from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pandas as pd

from mxm.moneymachine.marketdata.datasets.ohlcv_1d.expected import ExpectedWindow
from mxm.moneymachine.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.moneymachine.utils.time_utils import (
    fmt_day_ts,
    fmt_second_ts,
)

TABLE = "ohlcv_1d_attempts"


# -------------------------
# Lightweight coverage model
# -------------------------


@dataclass(frozen=True)
class AttemptsCoverageSnapshot:
    min_ts: pd.Timestamp | None
    max_ts: pd.Timestamp | None
    row_count: int
    bars_path: str | None = None


@dataclass(frozen=True)
class OHLCV1DAttemptRow:
    attempt_uid: str
    created_at: str

    run_ts_utc: str
    mode: str
    dry_run: bool
    reset_local: bool

    product_id: str
    contract_id: str
    contract_key: str

    # Vendor identity (nullable if unmapped / pre-mapping failures)
    feed: str | None
    dataset: str | None
    publisher_id: int | None
    instrument_id: int | None
    raw_symbol: str | None

    # Surfaces (all half-open [start,end), day-aligned ISO8601Z strings)
    interest_start: str
    interest_end: str
    dataset_start: str
    dataset_end: str
    activation_floor: str | None
    expiration_ceiling: str | None

    # Expected window (intersection)
    expected_start: str
    expected_end: str
    is_empty: bool

    # Diagnostics on why expected differs from interest  (persisted)
    is_vendor_limited: bool
    is_lifecycle_limited: bool

    # Derived flags
    vendor_final: bool

    # Orchestrator result
    status: str
    status_detail: str | None

    # Diagnostics
    error_type: str | None
    error_message: str | None

    # Coverage snapshots (before/after)
    stored_rows_before: int | None
    stored_min_before: str | None
    stored_max_before: str | None
    bars_path_before: str | None

    stored_rows_after: int | None
    stored_min_after: str | None
    stored_max_after: str | None
    bars_path_after: str | None

    # Cost accounting — snapshot at time of attempt (persisted)
    cost_cap_usd: float | None = None
    cost_estimated_usd: float | None = None
    cost_used_usd: float | None = None
    cost_charged_usd: float | None = None


def _bool01(v: Any) -> bool:
    return bool(int(v)) if v is not None else False


def _int_or_none(v: Any) -> int | None:
    return None if v is None else int(v)


# -------------------------
# Store
# -------------------------


class OHLCV1DAttemptsStore:
    """
    Append-only operational ledger for OHLCV-1D ingestion attempts.

    Expected usage:
    - The orchestrator calls record_attempt(...) exactly once per contract considered,
      including skips ("unmapped", "skipped_cost_cap", "skipped_empty_expected_window", etc.).
    """

    def __init__(self, *, backend: SQLiteBackend) -> None:
        self._backend = backend

    def record_attempt(
        self,
        *,
        # run-level context
        run_ts_utc: str,
        mode: str,  # "bootstrap" | "update"
        dry_run: bool,
        reset_local: bool,
        cost_cap_usd: float | None,
        # contract identity
        product_id: str,
        contract_id: str,
        contract_key: str,
        # vendor identity (nullable for unmapped / pre-mapping failures)
        feed: str | None = None,
        dataset: str | None = None,
        publisher_id: int | None = None,
        instrument_id: int | None = None,
        raw_symbol: str | None = None,
        # expected window (always present in your new design)
        ew: ExpectedWindow,
        # outcome
        status: str,
        status_detail: str | None = None,
        # cost accounting (optional, depending on path)
        cost_estimated_usd: float | None = None,
        cost_used_usd: float | None = None,
        cost_charged_usd: float | None = None,
        # coverage snapshots
        coverage_before: AttemptsCoverageSnapshot | None = None,
        coverage_after: AttemptsCoverageSnapshot | None = None,
        # error capture (optional)
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> str:
        """
        Insert a single attempt row. Returns attempt_uid (uuid4).
        """
        self._backend.ensure_migrated()
        attempt_uid = str(uuid.uuid4())

        row = {
            # primary id
            "attempt_uid": attempt_uid,
            # run context
            "run_ts_utc": run_ts_utc,
            "mode": mode,
            "dry_run": 1 if dry_run else 0,
            "reset_local": 1 if reset_local else 0,
            "cost_cap_usd": cost_cap_usd,
            # mxm keys
            "product_id": product_id,
            "contract_id": contract_id,
            "contract_key": contract_key,
            # vendor identity
            "feed": feed,
            "dataset": dataset,
            "publisher_id": publisher_id,
            "instrument_id": instrument_id,
            "raw_symbol": raw_symbol,
            # expected window surfaces
            "interest_start": fmt_day_ts(ew.interest_start),
            "interest_end": fmt_day_ts(ew.interest_end),
            "dataset_start": fmt_day_ts(ew.dataset_start),
            "dataset_end": fmt_day_ts(ew.dataset_end),
            "activation_floor": (
                None if ew.activation_floor is None else fmt_day_ts(ew.activation_floor)
            ),
            "expiration_ceiling": (
                None
                if ew.expiration_ceiling is None
                else fmt_day_ts(ew.expiration_ceiling)
            ),
            # derived expected interval
            "expected_start": fmt_day_ts(ew.expected_start),
            "expected_end": fmt_day_ts(ew.expected_end),
            # derived flags
            "is_empty": 1 if ew.is_empty else 0,
            "is_vendor_limited": 1 if ew.is_vendor_limited else 0,
            "is_lifecycle_limited": 1 if ew.is_lifecycle_limited else 0,
            "vendor_final": 1 if ew.vendor_final else 0,
            # outcome
            "status": status,
            "status_detail": status_detail,
            # costs
            "cost_estimated_usd": cost_estimated_usd,
            "cost_used_usd": cost_used_usd,
            "cost_charged_usd": cost_charged_usd,
            # coverage before
            "stored_min_before": (
                None
                if coverage_before is None or coverage_before.min_ts is None
                else fmt_second_ts(coverage_before.min_ts)
            ),
            "stored_max_before": (
                None
                if coverage_before is None or coverage_before.max_ts is None
                else fmt_second_ts(coverage_before.max_ts)
            ),
            "stored_rows_before": (
                int(coverage_before.row_count) if coverage_before else None
            ),
            "bars_path_before": coverage_before.bars_path if coverage_before else None,
            # coverage after
            "stored_min_after": (
                None
                if coverage_after is None or coverage_after.min_ts is None
                else fmt_second_ts(coverage_after.min_ts)
            ),
            "stored_max_after": (
                None
                if coverage_after is None or coverage_after.max_ts is None
                else fmt_second_ts(coverage_after.max_ts)
            ),
            "stored_rows_after": (
                int(coverage_after.row_count) if coverage_after else None
            ),
            "bars_path_after": coverage_after.bars_path if coverage_after else None,
            # error capture
            "error_type": error_type,
            "error_message": error_message,
        }

        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        sql = f"INSERT INTO {TABLE} ({cols}) VALUES ({placeholders})"

        with self._backend.transaction() as conn:
            conn.execute(sql, tuple(row.values()))

        return attempt_uid

    def _row_to_attempt(self, row: Any) -> OHLCV1DAttemptRow:
        return OHLCV1DAttemptRow(
            attempt_uid=str(row["attempt_uid"]),
            created_at=str(row["created_at"]),
            run_ts_utc=str(row["run_ts_utc"]),
            mode=str(row["mode"]),
            dry_run=_bool01(row["dry_run"]),
            reset_local=_bool01(row["reset_local"]),
            product_id=str(row["product_id"]),
            contract_id=str(row["contract_id"]),
            contract_key=str(row["contract_key"]),
            # Vendor identity
            feed=None if row["feed"] is None else str(row["feed"]),
            dataset=None if row["dataset"] is None else str(row["dataset"]),
            publisher_id=_int_or_none(row["publisher_id"]),
            instrument_id=_int_or_none(row["instrument_id"]),
            raw_symbol=None if row["raw_symbol"] is None else str(row["raw_symbol"]),
            # Surfaces (day-aligned, half-open)
            interest_start=str(row["interest_start"]),
            interest_end=str(row["interest_end"]),
            dataset_start=str(row["dataset_start"]),
            dataset_end=str(row["dataset_end"]),
            activation_floor=(
                None
                if row["activation_floor"] is None
                else str(row["activation_floor"])
            ),
            expiration_ceiling=(
                None
                if row["expiration_ceiling"] is None
                else str(row["expiration_ceiling"])
            ),
            # Expected window
            expected_start=str(row["expected_start"]),
            expected_end=str(row["expected_end"]),
            is_empty=_bool01(row["is_empty"]),
            # Limiting diagnostics (persisted)
            is_vendor_limited=_bool01(row["is_vendor_limited"]),
            is_lifecycle_limited=_bool01(row["is_lifecycle_limited"]),
            # Derived flags
            vendor_final=_bool01(row["vendor_final"]),
            # Result
            status=str(row["status"]),
            status_detail=(
                None if row["status_detail"] is None else str(row["status_detail"])
            ),
            # Diagnostics
            error_type=None if row["error_type"] is None else str(row["error_type"]),
            error_message=(
                None if row["error_message"] is None else str(row["error_message"])
            ),
            # Coverage snapshots (before)
            stored_rows_before=_int_or_none(row["stored_rows_before"]),
            stored_min_before=(
                None
                if row["stored_min_before"] is None
                else str(row["stored_min_before"])
            ),
            stored_max_before=(
                None
                if row["stored_max_before"] is None
                else str(row["stored_max_before"])
            ),
            bars_path_before=(
                None
                if row["bars_path_before"] is None
                else str(row["bars_path_before"])
            ),
            # Coverage snapshots (after)
            stored_rows_after=_int_or_none(row["stored_rows_after"]),
            stored_min_after=(
                None
                if row["stored_min_after"] is None
                else str(row["stored_min_after"])
            ),
            stored_max_after=(
                None
                if row["stored_max_after"] is None
                else str(row["stored_max_after"])
            ),
            bars_path_after=(
                None if row["bars_path_after"] is None else str(row["bars_path_after"])
            ),
            # Optional cost accounting (include these in SELECTs if you want them populated)
            cost_cap_usd=(
                None if row["cost_cap_usd"] is None else float(row["cost_cap_usd"])
            ),
            cost_estimated_usd=(
                None
                if row["cost_estimated_usd"] is None
                else float(row["cost_estimated_usd"])
            ),
        )

    # -------------------------
    # Read API
    # -------------------------

    def get_latest_attempt_for_contract(
        self, *, product_id: str, contract_id: str
    ) -> OHLCV1DAttemptRow | None:
        """
        Return the most recent attempt row for a given (product_id, contract_id),
        ordered by (run_ts_utc, created_at, attempt_uid) descending.
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    attempt_uid, created_at,
                    run_ts_utc, mode, dry_run, reset_local,
    
                    product_id, contract_id, contract_key,
    
                    -- vendor identity
                    feed, dataset, publisher_id, instrument_id, raw_symbol,
    
                    -- surfaces (day-aligned, half-open)
                    interest_start, interest_end,
                    dataset_start, dataset_end,
                    activation_floor, expiration_ceiling,
    
                    -- expected window + flags
                    expected_start, expected_end,
                    is_empty, is_vendor_limited, is_lifecycle_limited, vendor_final,
    
                    -- result / diagnostics
                    status, status_detail,
                    error_type, error_message,
    
                    -- coverage before
                    stored_rows_before, stored_min_before, stored_max_before,
                    bars_path_before,
    
                    -- coverage after
                    stored_rows_after, stored_min_after, stored_max_after,
                    bars_path_after,
    
                    -- optional cost accounting (safe to include; may be NULL)
                    cost_cap_usd, cost_estimated_usd, cost_used_usd, cost_charged_usd
    
                FROM {TABLE}
                WHERE product_id = ? AND contract_id = ?
                ORDER BY run_ts_utc DESC, created_at DESC, attempt_uid DESC
                LIMIT 1;
                """,
                (product_id, contract_id),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_attempt(row)

    def get_latest_attempt_for_contract_key(
        self, *, contract_key: str
    ) -> OHLCV1DAttemptRow | None:
        """
        Convenience lookup if you already compute/emit contract_key.
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    attempt_uid, created_at,
                    run_ts_utc, mode, dry_run, reset_local,
    
                    product_id, contract_id, contract_key,
    
                    -- vendor identity
                    feed, dataset, publisher_id, instrument_id, raw_symbol,
    
                    -- surfaces (day-aligned, half-open)
                    interest_start, interest_end,
                    dataset_start, dataset_end,
                    activation_floor, expiration_ceiling,
    
                    -- expected window + flags
                    expected_start, expected_end,
                    is_empty, is_vendor_limited, is_lifecycle_limited, vendor_final,
    
                    -- result / diagnostics
                    status, status_detail,
                    error_type, error_message,
    
                    -- coverage before
                    stored_rows_before, stored_min_before, stored_max_before,
                    bars_path_before,
    
                    -- coverage after
                    stored_rows_after, stored_min_after, stored_max_after,
                    bars_path_after,
    
                    -- optional cost accounting (supported fields only)
                    cost_cap_usd, cost_estimated_usd, cost_used_usd, cost_charged_usd
    
                FROM {TABLE}
                WHERE contract_key = ?
                ORDER BY run_ts_utc DESC, created_at DESC, attempt_uid DESC
                LIMIT 1;
                """,
                (contract_key,),
            ).fetchone()

        if row is None:
            return None

        return self._row_to_attempt(row)

    def list_latest_attempts_for_product(
        self, *, product_id: str
    ) -> list[OHLCV1DAttemptRow]:
        """
        Return the latest attempt row per contract_key for a given product_id.
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            rows = conn.execute(
                f"""
                WITH latest_run AS (
                    SELECT contract_key, MAX(run_ts_utc) AS run_ts_utc
                    FROM {TABLE}
                    WHERE product_id = ?
                    GROUP BY contract_key
                ),
                latest_created AS (
                    SELECT a.contract_key, a.run_ts_utc, MAX(a.created_at) AS created_at
                    FROM {TABLE} a
                    JOIN latest_run lr
                      ON lr.contract_key = a.contract_key AND lr.run_ts_utc = a.run_ts_utc
                    WHERE a.product_id = ?
                    GROUP BY a.contract_key, a.run_ts_utc
                )
                SELECT
                    a.attempt_uid, a.created_at,
                    a.run_ts_utc, a.mode, a.dry_run, a.reset_local,
    
                    a.product_id, a.contract_id, a.contract_key,
    
                    -- vendor identity
                    a.feed, a.dataset, a.publisher_id, a.instrument_id, a.raw_symbol,
    
                    -- surfaces (day-aligned, half-open)
                    a.interest_start, a.interest_end,
                    a.dataset_start, a.dataset_end,
                    a.activation_floor, a.expiration_ceiling,
    
                    -- expected window + flags
                    a.expected_start, a.expected_end,
                    a.is_empty, a.is_vendor_limited, a.is_lifecycle_limited, a.vendor_final,
    
                    -- result / diagnostics
                    a.status, a.status_detail,
                    a.error_type, a.error_message,
    
                    -- coverage before
                    a.stored_rows_before, a.stored_min_before, a.stored_max_before,
                    a.bars_path_before,
    
                    -- coverage after
                    a.stored_rows_after, a.stored_min_after, a.stored_max_after,
                    a.bars_path_after,
    
                    -- optional cost accounting (supported fields only)
                    a.cost_cap_usd, a.cost_estimated_usd, a.cost_used_usd, a.cost_charged_usd
    
                FROM {TABLE} a
                JOIN latest_created lc
                  ON lc.contract_key = a.contract_key
                 AND lc.run_ts_utc = a.run_ts_utc
                 AND lc.created_at = a.created_at
                WHERE a.product_id = ?
                ORDER BY a.contract_key ASC;
                """,
                (product_id, product_id, product_id),
            ).fetchall()

        return [self._row_to_attempt(r) for r in rows]

    def list_latest_attempts_all_contracts(self) -> list[OHLCV1DAttemptRow]:
        """
        Return the latest attempt row per contract_key across the entire table.
        Useful for system-wide coverage summaries.
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            rows = conn.execute(
                f"""
                WITH latest_run AS (
                    SELECT contract_key, MAX(run_ts_utc) AS run_ts_utc
                    FROM {TABLE}
                    GROUP BY contract_key
                ),
                latest_created AS (
                    SELECT a.contract_key, a.run_ts_utc, MAX(a.created_at) AS created_at
                    FROM {TABLE} a
                    JOIN latest_run lr
                      ON lr.contract_key = a.contract_key AND lr.run_ts_utc = a.run_ts_utc
                    GROUP BY a.contract_key, a.run_ts_utc
                )
                SELECT
                    a.attempt_uid, a.created_at,
                    a.run_ts_utc, a.mode, a.dry_run, a.reset_local,
    
                    a.product_id, a.contract_id, a.contract_key,
    
                    -- vendor identity
                    a.feed, a.dataset, a.publisher_id, a.instrument_id, a.raw_symbol,
    
                    -- surfaces (day-aligned, half-open)
                    a.interest_start, a.interest_end,
                    a.dataset_start, a.dataset_end,
                    a.activation_floor, a.expiration_ceiling,
    
                    -- expected window + flags
                    a.expected_start, a.expected_end,
                    a.is_empty, a.is_vendor_limited, a.is_lifecycle_limited, a.vendor_final,
    
                    -- result / diagnostics
                    a.status, a.status_detail,
                    a.error_type, a.error_message,
    
                    -- coverage before
                    a.stored_rows_before, a.stored_min_before, a.stored_max_before,
                    a.bars_path_before,
    
                    -- coverage after
                    a.stored_rows_after, a.stored_min_after, a.stored_max_after,
                    a.bars_path_after,
    
                    -- optional cost accounting (supported fields only)
                    a.cost_cap_usd, a.cost_estimated_usd, a.cost_used_usd, a.cost_charged_usd
    
                FROM {TABLE} a
                JOIN latest_created lc
                  ON lc.contract_key = a.contract_key
                 AND lc.run_ts_utc = a.run_ts_utc
                 AND lc.created_at = a.created_at
                ORDER BY a.product_id ASC, a.contract_key ASC;
                """
            ).fetchall()

        return [self._row_to_attempt(r) for r in rows]

    def list_products_with_attempts(self) -> list[str]:
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            rows = conn.execute(
                f"SELECT DISTINCT product_id FROM {TABLE} ORDER BY product_id ASC;"
            ).fetchall()
        return [str(r["product_id"]) for r in rows]
