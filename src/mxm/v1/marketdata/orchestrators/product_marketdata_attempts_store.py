from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend

TABLE = "marketdata_product_attempts"


@dataclass(frozen=True)
class ProductMarketdataAttemptRow:
    attempt_uid: str
    created_at: str

    run_ts_utc: str
    mode: str
    dry_run: bool
    reset: bool
    reset_local: bool

    product_id: str

    cost_cap_usd: float
    cost_used_usd: float
    remaining_usd: float

    status: str
    stop_reason: str | None

    started_at: str
    finished_at: str | None

    summary: dict[str, Any]

    error_type: str | None
    error_message: str | None


class ProductMarketdataAttemptsStore:
    def __init__(self, *, backend: SQLiteBackend) -> None:
        self._backend = backend

    # -------------------------
    # Write API
    # -------------------------

    def start_attempt(
        self,
        *,
        run_ts_utc: str,
        product_id: str,
        mode: str,  # "bootstrap" | "update"
        dry_run: bool,
        reset: bool,
        reset_local: bool,
        cost_cap_usd: float,
        started_at: str,
        summary: dict[str, Any] | None = None,
    ) -> str:
        """
        Insert a "running" attempt row and return attempt_uid.
        """
        self._backend.ensure_migrated()
        attempt_uid = str(uuid.uuid4())

        summary_json = json.dumps(summary or {}, separators=(",", ":"), sort_keys=True)

        row = {
            "attempt_uid": attempt_uid,
            "run_ts_utc": run_ts_utc,
            "mode": mode,
            "dry_run": 1 if dry_run else 0,
            "reset": 1 if reset else 0,
            "reset_local": 1 if reset_local else 0,
            "product_id": product_id,
            "cost_cap_usd": float(cost_cap_usd),
            "cost_used_usd": 0.0,
            "remaining_usd": float(cost_cap_usd),
            "status": "running",
            "stop_reason": None,
            "started_at": started_at,
            "finished_at": None,
            "summary_json": summary_json,
            "error_type": None,
            "error_message": None,
        }

        cols = ", ".join(row.keys())
        placeholders = ", ".join(["?"] * len(row))
        sql = f"INSERT INTO {TABLE} ({cols}) VALUES ({placeholders})"

        with self._backend.transaction() as conn:
            conn.execute(sql, tuple(row.values()))

        return attempt_uid

    def finish_attempt(
        self,
        *,
        attempt_uid: str,
        status: str,  # "success" | "halted" | "error"
        stop_reason: str | None,
        finished_at: str,
        cost_used_usd: float,
        remaining_usd: float,
        summary: dict[str, Any],
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """
        Finalize an existing attempt row (two-phase write).
        """
        self._backend.ensure_migrated()

        summary_json = json.dumps(summary or {}, separators=(",", ":"), sort_keys=True)

        with self._backend.transaction() as conn:
            conn.execute(
                f"""
                UPDATE {TABLE}
                SET
                    status = ?,
                    stop_reason = ?,
                    finished_at = ?,
                    cost_used_usd = ?,
                    remaining_usd = ?,
                    summary_json = ?,
                    error_type = ?,
                    error_message = ?
                WHERE attempt_uid = ?
                """,
                (
                    status,
                    stop_reason,
                    finished_at,
                    float(cost_used_usd),
                    float(remaining_usd),
                    summary_json,
                    error_type,
                    error_message,
                    attempt_uid,
                ),
            )

    # -------------------------
    # Read API
    # -------------------------

    def get_latest_attempt_for_product(
        self, *, product_id: str
    ) -> ProductMarketdataAttemptRow | None:
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                    attempt_uid, created_at,
                    run_ts_utc, mode, dry_run, reset, reset_local,
                    product_id,
                    cost_cap_usd, cost_used_usd, remaining_usd,
                    status, stop_reason,
                    started_at, finished_at,
                    summary_json,
                    error_type, error_message
                FROM {TABLE}
                WHERE product_id = ?
                ORDER BY started_at DESC, created_at DESC
                LIMIT 1
                """,
                (product_id,),
            ).fetchone()

        return _row_to_attempt(row) if row else None

    def list_attempts_for_product(
        self, *, product_id: str, limit: int = 50
    ) -> list[ProductMarketdataAttemptRow]:
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                    attempt_uid, created_at,
                    run_ts_utc, mode, dry_run, reset, reset_local,
                    product_id,
                    cost_cap_usd, cost_used_usd, remaining_usd,
                    status, stop_reason,
                    started_at, finished_at,
                    summary_json,
                    error_type, error_message
                FROM {TABLE}
                WHERE product_id = ?
                ORDER BY started_at DESC, created_at DESC
                LIMIT ?
                """,
                (product_id, int(limit)),
            ).fetchall()

        return [_row_to_attempt(r) for r in rows]


def _row_to_attempt(row) -> ProductMarketdataAttemptRow:
    # sqlite3.Row supports dict-style access
    summary_raw = row["summary_json"] or "{}"
    try:
        summary = json.loads(summary_raw)
        if not isinstance(summary, dict):
            summary = {"_summary": summary}
    except Exception:
        summary = {"_summary_parse_error": True, "_raw": summary_raw}

    return ProductMarketdataAttemptRow(
        attempt_uid=row["attempt_uid"],
        created_at=row["created_at"],
        run_ts_utc=row["run_ts_utc"],
        mode=row["mode"],
        dry_run=bool(row["dry_run"]),
        reset=bool(row["reset"]),
        reset_local=bool(row["reset_local"]),
        product_id=row["product_id"],
        cost_cap_usd=float(row["cost_cap_usd"]),
        cost_used_usd=float(row["cost_used_usd"]),
        remaining_usd=float(row["remaining_usd"]),
        status=row["status"],
        stop_reason=row["stop_reason"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        summary=summary,
        error_type=row["error_type"],
        error_message=row["error_message"],
    )
