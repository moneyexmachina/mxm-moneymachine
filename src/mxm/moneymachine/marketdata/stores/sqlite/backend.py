from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout


@dataclass(frozen=True)
class SQLiteBackend:
    """
    Thin SQLite technology adapter for MXM marketdata.

    Responsibilities:
    - Open connections to the single marketdata SQLite database
    - Apply migrations deterministically
    - Provide transaction boundaries

    Non-responsibilities:
    - No dataset business logic
    - No vendor logic
    """

    layout: MarketdataLayout

    def db_path(self) -> Path:
        return self.layout.sqlite_db_path()

    def connect(self) -> sqlite3.Connection:
        """
        Open a SQLite connection with sensible defaults.
        """
        path = self.db_path()
        path.parent.mkdir(parents=True, exist_ok=True)

        conn = sqlite3.connect(str(path))
        conn.row_factory = sqlite3.Row

        # Pragmas: correctness > throughput for this dataset.
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")

        return conn

    def ensure_migrated(self) -> None:
        """
        Apply all pending migrations in stores/sqlite/migrations in lexical order.
        """
        migrations_dir = Path(__file__).resolve().parent / "migrations"
        migration_files = sorted(p for p in migrations_dir.glob("*.sql") if p.is_file())

        with self.connect() as conn:
            self._ensure_migrations_table(conn)
            applied = set(self._get_applied_migrations(conn))

            for path in migration_files:
                name = path.name
                if name in applied:
                    continue

                sql = path.read_text(encoding="utf-8")
                with self._transaction(conn):
                    conn.executescript(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (name) VALUES (?)",
                        (name,),
                    )

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """
        Public transaction context manager: yields a migrated connection
        and wraps the body in a BEGIN/COMMIT (rollback on exception).
        """
        self.ensure_migrated()
        with self.connect() as conn:
            with self._transaction(conn):
                yield conn

    @contextmanager
    def transaction_no_migrate(self) -> Iterator[sqlite3.Connection]:
        with self.connect() as conn:
            with self._transaction(conn):
                yield conn

    # -------------------------
    # Internal helpers
    # -------------------------

    @staticmethod
    def _ensure_migrations_table(conn: sqlite3.Connection) -> None:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                name TEXT PRIMARY KEY,
                applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
            );
            """
        )

    @staticmethod
    def _get_applied_migrations(conn: sqlite3.Connection) -> list[str]:
        rows = conn.execute(
            "SELECT name FROM schema_migrations ORDER BY name"
        ).fetchall()
        return [r["name"] for r in rows]

    @staticmethod
    @contextmanager
    def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
        try:
            conn.execute("BEGIN;")
            yield
            conn.execute("COMMIT;")
        except Exception:
            conn.execute("ROLLBACK;")
            raise
