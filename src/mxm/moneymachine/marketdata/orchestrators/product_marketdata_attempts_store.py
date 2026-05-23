from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from typing import cast

from mxm.moneymachine.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.types import JSONMap, JSONValue

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

    summary: JSONMap

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
        summary: JSONMap | None = None,
    ) -> str:
        """
        Insert a "running" attempt row and return attempt_uid.
        """
        self._backend.ensure_migrated()
        attempt_uid = str(uuid.uuid4())
        summary_json = _json_summary_dumps(summary)

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
        summary: JSONMap,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        """
        Finalize an existing attempt row (two-phase write).
        """
        self._backend.ensure_migrated()

        summary_json = _json_summary_dumps(summary)

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


def _json_summary_dumps(summary: JSONMap | None) -> str:
    return json.dumps(summary or {}, separators=(",", ":"), sort_keys=True)


def _json_summary_loads(raw: str) -> JSONMap:
    try:
        loaded = json.loads(raw)
    except Exception:
        return {"_summary_parse_error": True, "_raw": raw}

    if isinstance(loaded, dict):
        loaded_map = cast(dict[object, object], loaded)
        return _coerce_json_map(loaded_map)

    return {"_summary": _coerce_json_value(cast(object, loaded))}


def _coerce_json_map(raw: dict[object, object]) -> JSONMap:
    out: JSONMap = {}
    for key, value in raw.items():
        out[str(key)] = _coerce_json_value(value)
    return out


def _coerce_json_value(value: object) -> JSONValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value

    if isinstance(value, list):
        values = cast(list[object], value)
        return [_coerce_json_value(v) for v in values]

    if isinstance(value, dict):
        value_map = cast(dict[object, object], value)
        return _coerce_json_map(value_map)

    return repr(value)


def _row_str(row: sqlite3.Row, key: str) -> str:
    value = row[key]
    if not isinstance(value, str):
        raise TypeError(
            f"Expected sqlite column {key!r} to be str, got {type(value).__name__}"
        )
    return value


def _row_optional_str(row: sqlite3.Row, key: str) -> str | None:
    value = row[key]
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError(
            f"Expected sqlite column {key!r} to be str | None, got {type(value).__name__}"
        )
    return value


def _row_bool(row: sqlite3.Row, key: str) -> bool:
    return bool(row[key])


def _row_float(row: sqlite3.Row, key: str) -> float:
    return float(row[key])


def _row_to_attempt(row: sqlite3.Row) -> ProductMarketdataAttemptRow:
    summary_raw = _row_optional_str(row, "summary_json") or "{}"
    summary = _json_summary_loads(summary_raw)

    return ProductMarketdataAttemptRow(
        attempt_uid=_row_str(row, "attempt_uid"),
        created_at=_row_str(row, "created_at"),
        run_ts_utc=_row_str(row, "run_ts_utc"),
        mode=_row_str(row, "mode"),
        dry_run=_row_bool(row, "dry_run"),
        reset=_row_bool(row, "reset"),
        reset_local=_row_bool(row, "reset_local"),
        product_id=_row_str(row, "product_id"),
        cost_cap_usd=_row_float(row, "cost_cap_usd"),
        cost_used_usd=_row_float(row, "cost_used_usd"),
        remaining_usd=_row_float(row, "remaining_usd"),
        status=_row_str(row, "status"),
        stop_reason=_row_optional_str(row, "stop_reason"),
        started_at=_row_str(row, "started_at"),
        finished_at=_row_optional_str(row, "finished_at"),
        summary=summary,
        error_type=_row_optional_str(row, "error_type"),
        error_message=_row_optional_str(row, "error_message"),
    )
