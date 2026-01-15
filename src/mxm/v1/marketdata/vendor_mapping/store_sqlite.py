# src/mxm/v1/marketdata/vendor_mapping/store_sqlite.py
"""
SQLite-backed store for vendor ↔ MXM contract mapping.

This is intentionally a small, explicit persistence layer:
- durable local cache
- inspectable with standard sqlite tooling
- supports keyed lookups and product-scoped loads
- supports idempotent upserts keyed by (vendor, product_id, period_id)

No vendor SDK imports here.
No RefData imports here.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterable, Optional

from .models import MappingStatus, VendorContractKey, VendorContractMappingRow

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS vendor_contract_mapping (
    vendor           TEXT NOT NULL,
    product_id       TEXT NOT NULL,
    period_id        TEXT NOT NULL,

    instrument_id    INTEGER,
    raw_symbol       TEXT,

    expiration_date  TEXT,
    exp_year         INTEGER,
    exp_month        INTEGER,

    status           TEXT NOT NULL,
    mapped_at        TEXT,
    notes            TEXT,

    meta_json        TEXT,

    PRIMARY KEY (vendor, product_id, period_id)
);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_mapping_product
    ON vendor_contract_mapping (vendor, product_id);

CREATE INDEX IF NOT EXISTS idx_vendor_contract_mapping_instrument
    ON vendor_contract_mapping (vendor, instrument_id);
"""


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    # Basic durability; safe default for a cache that matters.
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


def _ensure_schema(con: sqlite3.Connection) -> None:
    con.executescript(_SCHEMA_SQL)
    con.commit()


def _row_to_mapping(row: sqlite3.Row) -> VendorContractMappingRow:
    key = VendorContractKey(
        vendor=row["vendor"],
        product_id=row["product_id"],
        period_id=row["period_id"],
    )
    status = MappingStatus(row["status"])
    meta_json = row["meta_json"]
    # We intentionally avoid hard-depending on json here unless needed; it is stdlib anyway.
    meta = {}
    if meta_json:
        import json  # noqa: PLC0415

        meta = json.loads(meta_json)

    return VendorContractMappingRow(
        key=key,
        instrument_id=row["instrument_id"],
        raw_symbol=row["raw_symbol"],
        expiration_date=row["expiration_date"],
        exp_year=row["exp_year"],
        exp_month=row["exp_month"],
        status=status,
        mapped_at=row["mapped_at"],
        notes=row["notes"],
        meta=meta,
    )


def _mapping_to_params(m: VendorContractMappingRow) -> dict:
    import json  # noqa: PLC0415

    return {
        "vendor": m.key.vendor,
        "product_id": m.key.product_id,
        "period_id": m.key.period_id,
        "instrument_id": m.instrument_id,
        "raw_symbol": m.raw_symbol,
        "expiration_date": m.expiration_date,
        "exp_year": m.exp_year,
        "exp_month": m.exp_month,
        "status": m.status.value,
        "mapped_at": m.mapped_at,
        "notes": m.notes,
        "meta_json": json.dumps(dict(m.meta)) if m.meta else None,
    }


_UPSERT_SQL = """
INSERT INTO vendor_contract_mapping (
    vendor, product_id, period_id,
    instrument_id, raw_symbol,
    expiration_date, exp_year, exp_month,
    status, mapped_at, notes,
    meta_json
) VALUES (
    :vendor, :product_id, :period_id,
    :instrument_id, :raw_symbol,
    :expiration_date, :exp_year, :exp_month,
    :status, :mapped_at, :notes,
    :meta_json
)
ON CONFLICT(vendor, product_id, period_id) DO UPDATE SET
    instrument_id   = excluded.instrument_id,
    raw_symbol      = excluded.raw_symbol,
    expiration_date = excluded.expiration_date,
    exp_year        = excluded.exp_year,
    exp_month       = excluded.exp_month,
    status          = excluded.status,
    mapped_at       = excluded.mapped_at,
    notes           = excluded.notes,
    meta_json       = excluded.meta_json;
"""


class VendorContractMappingStoreSqlite:
    """
    Small SQLite store for VendorContractMappingRow.

    Usage pattern:
        store = VendorContractMappingStoreSqlite(Path(".../vendor_mapping.sqlite3"))
        store.ensure_schema()
        store.upsert_rows(rows)
        row = store.get_row(key)
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @property
    def db_path(self) -> Path:
        return self._db_path

    def ensure_schema(self) -> None:
        con = _connect(self._db_path)
        try:
            _ensure_schema(con)
        finally:
            con.close()

    def upsert_rows(self, rows: Iterable[VendorContractMappingRow]) -> int:
        """
        Upsert mapping rows. Returns number of rows processed (not SQLite rowcount).
        """
        rows_list = list(rows)
        if not rows_list:
            return 0

        con = _connect(self._db_path)
        try:
            _ensure_schema(con)
            con.executemany(_UPSERT_SQL, [_mapping_to_params(r) for r in rows_list])
            con.commit()
            return len(rows_list)
        finally:
            con.close()

    def get_row(self, key: VendorContractKey) -> Optional[VendorContractMappingRow]:
        con = _connect(self._db_path)
        try:
            _ensure_schema(con)
            cur = con.execute(
                """
                SELECT *
                FROM vendor_contract_mapping
                WHERE vendor = ? AND product_id = ? AND period_id = ?
                """,
                (key.vendor, key.product_id, key.period_id),
            )
            row = cur.fetchone()
            return _row_to_mapping(row) if row else None
        finally:
            con.close()

    def get_rows_for_product(
        self,
        *,
        vendor: str,
        product_id: str,
    ) -> list[VendorContractMappingRow]:
        con = _connect(self._db_path)
        try:
            _ensure_schema(con)
            cur = con.execute(
                """
                SELECT *
                FROM vendor_contract_mapping
                WHERE vendor = ? AND product_id = ?
                ORDER BY period_id ASC
                """,
                (vendor, product_id),
            )
            return [_row_to_mapping(r) for r in cur.fetchall()]
        finally:
            con.close()

    def delete_rows_for_product(self, *, vendor: str, product_id: str) -> int:
        """
        Delete all mapping rows for a product. Useful for clean rebuilds.
        Returns the SQLite cursor rowcount.
        """
        con = _connect(self._db_path)
        try:
            _ensure_schema(con)
            cur = con.execute(
                """
                DELETE FROM vendor_contract_mapping
                WHERE vendor = ? AND product_id = ?
                """,
                (vendor, product_id),
            )
            con.commit()
            return int(cur.rowcount)
        finally:
            con.close()

    def list_products(self, *, vendor: Optional[str] = None) -> list[tuple[str, str]]:
        """
        Returns distinct (vendor, product_id) pairs in the store.
        """
        con = _connect(self._db_path)
        try:
            _ensure_schema(con)
            if vendor is None:
                cur = con.execute(
                    """
                    SELECT DISTINCT vendor, product_id
                    FROM vendor_contract_mapping
                    ORDER BY vendor, product_id
                    """
                )
                return [(r["vendor"], r["product_id"]) for r in cur.fetchall()]

            cur = con.execute(
                """
                SELECT DISTINCT vendor, product_id
                FROM vendor_contract_mapping
                WHERE vendor = ?
                ORDER BY vendor, product_id
                """,
                (vendor,),
            )
            return [(r["vendor"], r["product_id"]) for r in cur.fetchall()]
        finally:
            con.close()

    def vacuum(self) -> None:
        """
        Optional maintenance. Safe to call occasionally.
        """
        con = _connect(self._db_path)
        try:
            con.execute("VACUUM;")
            con.commit()
        finally:
            con.close()
