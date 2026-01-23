# mxm/v1/marketdata/datasets/ohlcv_1d/attempts_store.py

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import pandas as pd

from mxm.v1.marketdata.datasets.ohlcv_1d.expected import ExpectedWindow
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend

TABLE = "ohlcv_1d_attempts"


# -------------------------
# Lightweight coverage model
# -------------------------


@dataclass(frozen=True)
class CoverageSnapshot:
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

    status: str
    vendor_final: bool
    is_empty: bool

    expected_start: str
    expected_end: str

    # Optional diagnostics
    status_detail: str | None
    error_type: str | None
    error_message: str | None

    # Optional coverage (post-attempt is the most relevant)
    stored_rows_after: int | None
    stored_min_after: str | None
    stored_max_after: str | None

    # Optional vendor identity (useful for debugging)
    dataset: str | None
    publisher_id: int | None
    instrument_id: int | None
    raw_symbol: str | None


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
        coverage_before: CoverageSnapshot | None = None,
        coverage_after: CoverageSnapshot | None = None,
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
            "interest_start": _fmt_ts(ew.interest_start),
            "interest_end": _fmt_ts(ew.interest_end),
            "dataset_start": _fmt_ts(ew.dataset_start),
            "dataset_end": _fmt_ts(ew.dataset_end),
            "activation_floor": _fmt_ts_or_none(ew.activation_floor),
            "expiration_ceiling": _fmt_ts_or_none(ew.expiration_ceiling),
            # derived expected interval
            "expected_start": _fmt_ts(ew.expected_start),
            "expected_end": _fmt_ts(ew.expected_end),
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
                _fmt_ts_or_none(coverage_before.min_ts) if coverage_before else None
            ),
            "stored_max_before": (
                _fmt_ts_or_none(coverage_before.max_ts) if coverage_before else None
            ),
            "stored_rows_before": (
                int(coverage_before.row_count) if coverage_before else None
            ),
            "bars_path_before": coverage_before.bars_path if coverage_before else None,
            # coverage after
            "stored_min_after": (
                _fmt_ts_or_none(coverage_after.min_ts) if coverage_after else None
            ),
            "stored_max_after": (
                _fmt_ts_or_none(coverage_after.max_ts) if coverage_after else None
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

    # -------------------------
    # Read API
    # -------------------------

    def get_latest_attempt_for_contract(
        self, *, product_id: str, contract_id: str
    ) -> OHLCV1DAttemptRow | None:
        """
        Return the most recent attempt row for a given (product_id, contract_id),
        ordered by created_at descending.
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    attempt_uid, created_at,
                    run_ts_utc, mode, dry_run, reset_local,
                    product_id, contract_id, contract_key,
                    status, vendor_final, is_empty,
                    expected_start, expected_end,
                    status_detail, error_type, error_message,
                    stored_rows_after, stored_min_after, stored_max_after,
                    dataset, publisher_id, instrument_id, raw_symbol
                FROM {TABLE}
                WHERE product_id = ? AND contract_id = ?
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (product_id, contract_id),
            ).fetchone()

        if row is None:
            return None

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
            status=str(row["status"]),
            vendor_final=_bool01(row["vendor_final"]),
            is_empty=_bool01(row["is_empty"]),
            expected_start=str(row["expected_start"]),
            expected_end=str(row["expected_end"]),
            status_detail=(
                None if row["status_detail"] is None else str(row["status_detail"])
            ),
            error_type=None if row["error_type"] is None else str(row["error_type"]),
            error_message=(
                None if row["error_message"] is None else str(row["error_message"])
            ),
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
            dataset=None if row["dataset"] is None else str(row["dataset"]),
            publisher_id=_int_or_none(row["publisher_id"]),
            instrument_id=_int_or_none(row["instrument_id"]),
            raw_symbol=None if row["raw_symbol"] is None else str(row["raw_symbol"]),
        )

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
                    status, vendor_final, is_empty,
                    expected_start, expected_end,
                    status_detail, error_type, error_message,
                    stored_rows_after, stored_min_after, stored_max_after,
                    dataset, publisher_id, instrument_id, raw_symbol
                FROM {TABLE}
                WHERE contract_key = ?
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (contract_key,),
            ).fetchone()

        if row is None:
            return None

        # Delegate to the same mapping logic by faking a Row-to-dict conversion would be overkill;
        # keep duplication explicit for now (this is stable and small).
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
            status=str(row["status"]),
            vendor_final=_bool01(row["vendor_final"]),
            is_empty=_bool01(row["is_empty"]),
            expected_start=str(row["expected_start"]),
            expected_end=str(row["expected_end"]),
            status_detail=(
                None if row["status_detail"] is None else str(row["status_detail"])
            ),
            error_type=None if row["error_type"] is None else str(row["error_type"]),
            error_message=(
                None if row["error_message"] is None else str(row["error_message"])
            ),
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
            dataset=None if row["dataset"] is None else str(row["dataset"]),
            publisher_id=_int_or_none(row["publisher_id"]),
            instrument_id=_int_or_none(row["instrument_id"]),
            raw_symbol=None if row["raw_symbol"] is None else str(row["raw_symbol"]),
        )


# -------------------------
# Formatting helpers
# -------------------------


def _fmt_ts(ts: pd.Timestamp) -> str:
    """
    Canonical UTC ISO8601Z formatting, second resolution.

    We deliberately strip sub-second precision to:
    - keep DB ordering lexicographically stable
    - match your other store conventions
    """
    t = pd.Timestamp(ts)
    if t.tzinfo is None:
        t = t.tz_localize("UTC")
    else:
        t = t.tz_convert("UTC")
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _fmt_ts_or_none(ts: pd.Timestamp | None) -> str | None:
    return None if ts is None else _fmt_ts(ts)
