from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from mxm.v1.marketdata.schema.instrument_definitions import (
    TABLE_CURRENT,
    TABLE_EVENTS,
    TABLE_WATERMARKS,
    canonical_json,
    event_uid_from_payload_json,
)
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.utils.time_utils import (
    ensure_utc_datetime_series,
    ensure_utc_datetimeindex,
    fmt_run_ts,
)


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------
def _as_nullable_scalar(v: Any) -> Any:
    if v is None:
        return None
    try:
        if pd.isna(v):  # type: ignore[arg-type]
            return None
    except Exception:
        pass
    # sqlite can return bytes sometimes
    if isinstance(v, (bytes, bytearray)):
        try:
            return v.decode("utf-8")
        except Exception:
            return str(v)
    # normalize pandas/numpy scalars
    if hasattr(v, "item"):
        try:
            return v.item()
        except Exception:
            pass
    return v


@dataclass(frozen=True)
class IngestResult:
    feed: str
    events_seen: int
    events_inserted: int
    watermark_before: str | None
    watermark_after: str | None
    keys_touched: int


@dataclass(frozen=True)
class ResetFeedResult:
    feed: str
    events_deleted: int
    current_deleted: int
    watermark_deleted: int


@dataclass(frozen=True)
class CoverageCheck:
    """
    Read-only coverage check for a feed.

    Semantics (MVP):
      ok iff watermark(feed) >= required_end
    """

    ok: bool
    feed: str
    watermark: str | None
    required_end: str
    reason: str  # "ok" | "no_watermark" | "watermark_before_required_end"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class InstrumentDefinitionsStore:
    """
    Dataset-domain store for instrument definitions.

    Responsibilities:
    - Normalise incoming frames (materialise ts_recv from index)
    - Canonicalise payloads and compute deterministic event_uid
    - Append-only event ingestion (idempotent)
    - Maintain a materialised current view (one row per publisher_id + instrument_id)
    - Maintain ingestion watermarks (per feed)
    - Provide read-only dataset queries (feed-scoped), including coverage checks

    Non-responsibilities:
    - No vendor mapping logic (Session 9)
    - No mxm-refdata logic
    - No orchestration policies (windows/cost caps/etc.)
    """

    def __init__(self, *, backend: SQLiteBackend) -> None:
        self._backend = backend

    # -------------------------
    # Public write API
    # -------------------------

    def ingest_batch(self, *, feed: str, df: pd.DataFrame) -> IngestResult:
        """
        Ingest a batch of instrument definition events (DataFrame indexed by ts_recv).

        Idempotency is enforced via event_uid (sha256 of canonical payload_json).
        Watermark advances to max(ts_recv) observed in this batch.
        """
        if df.empty:
            # Still ensure migrations exist
            self._backend.ensure_migrated()
            before = self.get_watermark(feed=feed)
            return IngestResult(
                feed=feed,
                events_seen=0,
                events_inserted=0,
                watermark_before=before,
                watermark_after=before,
                keys_touched=0,
            )

        # Normalise: materialise ts_recv as a column (do not trust index downstream)
        df_norm = self._normalise_frame(df)

        # Build per-row event records
        events = self._build_event_rows(feed, df_norm)

        watermark_before = self.get_watermark(feed=feed)
        watermark_after = max(e["ts_recv"] for e in events)

        keys_touched = len({(e["publisher_id"], e["instrument_id"]) for e in events})

        with self._backend.transaction() as conn:
            inserted = self._insert_events(conn, events)
            self._update_current_view(conn, events)
            self._upsert_watermark(conn, feed=feed, ts_recv_last=watermark_after)

        return IngestResult(
            feed=feed,
            events_seen=len(events),
            events_inserted=inserted,
            watermark_before=watermark_before,
            watermark_after=watermark_after,
            keys_touched=keys_touched,
        )

    def reset_feed(self, *, feed: str) -> ResetFeedResult:
        """
        Feed-scoped destructive reset.

        Deletes:
        - all append-only event rows for this feed
        - all materialised current rows whose provenance feed matches this feed
        - the watermark row for this feed

        This does not affect other feeds.

        Returns reliable deletion counts (computed via count-before/after).
        """
        self._backend.ensure_migrated()

        with self._backend.transaction() as conn:
            # --- events ---
            before_events = conn.execute(
                f"SELECT COUNT(*) AS n FROM {TABLE_EVENTS} WHERE feed = ?",
                (feed,),
            ).fetchone()["n"]

            conn.execute(
                f"DELETE FROM {TABLE_EVENTS} WHERE feed = ?",
                (feed,),
            )

            after_events = conn.execute(
                f"SELECT COUNT(*) AS n FROM {TABLE_EVENTS} WHERE feed = ?",
                (feed,),
            ).fetchone()["n"]

            events_deleted = int(before_events - after_events)

            # --- current ---
            before_current = conn.execute(
                f"SELECT COUNT(*) AS n FROM {TABLE_CURRENT} WHERE feed = ?",
                (feed,),
            ).fetchone()["n"]

            conn.execute(
                f"DELETE FROM {TABLE_CURRENT} WHERE feed = ?",
                (feed,),
            )

            after_current = conn.execute(
                f"SELECT COUNT(*) AS n FROM {TABLE_CURRENT} WHERE feed = ?",
                (feed,),
            ).fetchone()["n"]

            current_deleted = int(before_current - after_current)

            # --- watermark ---
            before_wm = conn.execute(
                f"SELECT COUNT(*) AS n FROM {TABLE_WATERMARKS} WHERE feed = ?",
                (feed,),
            ).fetchone()["n"]

            conn.execute(
                f"DELETE FROM {TABLE_WATERMARKS} WHERE feed = ?",
                (feed,),
            )

            after_wm = conn.execute(
                f"SELECT COUNT(*) AS n FROM {TABLE_WATERMARKS} WHERE feed = ?",
                (feed,),
            ).fetchone()["n"]

            watermark_deleted = int(before_wm - after_wm)

        # Defensive: should never be negative
        if events_deleted < 0 or current_deleted < 0 or watermark_deleted < 0:
            raise RuntimeError(
                "reset_feed produced negative delete counts; unexpected concurrent writers?"
            )

        return ResetFeedResult(
            feed=feed,
            events_deleted=events_deleted,
            current_deleted=current_deleted,
            watermark_deleted=watermark_deleted,
        )

    # -------------------------
    # Public read API (feed-scoped)
    # -------------------------

    def get_watermark(self, *, feed: str) -> str | None:
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                f"SELECT ts_recv_last FROM {TABLE_WATERMARKS} WHERE feed = ?",
                (feed,),
            ).fetchone()
            return None if row is None else row["ts_recv_last"]

    def check_coverage(self, *, feed: str, required_end: str) -> CoverageCheck:
        """
        Read-only coverage gate for this dataset.

        Semantics (MVP):
          ok iff watermark(feed) >= required_end

        Both watermark and required_end are ISO8601Z strings.
        """
        wm = self.get_watermark(feed=feed)
        if wm is None:
            return CoverageCheck(
                ok=False,
                feed=feed,
                watermark=None,
                required_end=required_end,
                reason="no_watermark",
            )

        # Use string ordering only if format is canonical ISO8601Z with fixed width.
        # Your store writes ISO8601Z via to_iso_z; required_end should be same style.
        if wm >= required_end:
            return CoverageCheck(
                ok=True,
                feed=feed,
                watermark=wm,
                required_end=required_end,
                reason="ok",
            )

        return CoverageCheck(
            ok=False,
            feed=feed,
            watermark=wm,
            required_end=required_end,
            reason="watermark_before_required_end",
        )

    def count_events_by_feed(self, *, feed: str) -> int:
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {TABLE_EVENTS} WHERE feed = ?",
                (feed,),
            ).fetchone()
            return int(row["n"])

    def count_current_by_feed(self, *, feed: str) -> int:
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                f"SELECT COUNT(*) AS n FROM {TABLE_CURRENT} WHERE feed = ?",
                (feed,),
            ).fetchone()
            return int(row["n"])

    def list_current_outright_maturities_by_feed(
        self, *, feed: str
    ) -> set[tuple[int, int]]:
        """
        Return the set of (maturity_year, maturity_month) present in instrument_definition_current
        for this feed, filtered to outright futures (security_type=FUT, instrument_class=F).

        JSON paths correspond to Databento definition schema fields, stored in payload_json.
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT
                  json_extract(payload_json, '$.maturity_year')  AS maturity_year,
                  json_extract(payload_json, '$.maturity_month') AS maturity_month
                FROM {TABLE_CURRENT}
                WHERE feed = ?
                  AND json_extract(payload_json, '$.security_type') = 'FUT'
                  AND json_extract(payload_json, '$.instrument_class') = 'F'
                ORDER BY maturity_year, maturity_month;
                """,
                (feed,),
            ).fetchall()

        out: set[tuple[int, int]] = set()
        for r in rows:
            if r["maturity_year"] is None or r["maturity_month"] is None:
                continue
            out.add((int(r["maturity_year"]), int(r["maturity_month"])))
        return out

    def get_current(
        self, *, publisher_id: int, instrument_id: int
    ) -> dict[str, Any] | None:
        """
        Backwards-compatible point lookup (not feed-scoped).
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                f"""
                SELECT feed, publisher_id, instrument_id, ts_event, ts_recv,
                       security_update_action, rtype, payload_json, event_uid
                FROM {TABLE_CURRENT}
                WHERE publisher_id = ? AND instrument_id = ?
                """,
                (publisher_id, instrument_id),
            ).fetchone()
            return None if row is None else dict(row)

    def read_lifecycle_by_feed_and_identity(
        self,
        *,
        feed: str,
        publisher_id: int,
        instrument_id: int,
    ) -> tuple[int | None, int | None] | None:
        """
        Read activation/expiration (ns since epoch) for an instrument from the current view.

        Returns:
          (activation_ns, expiration_ns) if found, where each may be None,
          or None if no current row exists for this (feed, publisher_id, instrument_id).

        Notes:
        - We intentionally read from TABLE_CURRENT (materialised latest state).
        - Values are stored inside payload_json per Databento definition schema.
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                f"""
                SELECT
                  json_extract(payload_json, '$.activation') AS activation,
                  json_extract(payload_json, '$.expiration') AS expiration
                FROM {TABLE_CURRENT}
                WHERE feed = ?
                  AND publisher_id = ?
                  AND instrument_id = ?
                LIMIT 1;
                """,
                (feed, int(publisher_id), int(instrument_id)),
            ).fetchone()

        if row is None:
            return None

        activation = row["activation"]
        expiration = row["expiration"]

        activation_ns = None if activation is None else _as_nullable_scalar(activation)
        expiration_ns = None if expiration is None else _as_nullable_scalar(expiration)

        return (activation_ns, expiration_ns)

    def list_current(
        self, *, publisher_id: int | None = None, feed: str | None = None
    ) -> pd.DataFrame:
        """
        Backwards-compatible bulk listing, with optional publisher_id filter.
        Extended: optional feed filter.

        NOTE: This returns a DataFrame for convenience, as you already used it.
        For bounded reads, prefer read_current_by_feed(...).
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            if publisher_id is None and feed is None:
                rows = conn.execute(
                    f"""
                    SELECT feed, publisher_id, instrument_id, ts_event, ts_recv,
                           security_update_action, rtype, payload_json, event_uid
                    FROM {TABLE_CURRENT}
                    ORDER BY ts_recv, ts_event, publisher_id, instrument_id
                    """
                ).fetchall()
            elif publisher_id is not None and feed is None:
                rows = conn.execute(
                    f"""
                    SELECT feed, publisher_id, instrument_id, ts_event, ts_recv,
                           security_update_action, rtype, payload_json, event_uid
                    FROM {TABLE_CURRENT}
                    WHERE publisher_id = ?
                    ORDER BY ts_recv, ts_event, publisher_id, instrument_id
                    """,
                    (publisher_id,),
                ).fetchall()
            elif publisher_id is None and feed is not None:
                rows = conn.execute(
                    f"""
                    SELECT feed, publisher_id, instrument_id, ts_event, ts_recv,
                           security_update_action, rtype, payload_json, event_uid
                    FROM {TABLE_CURRENT}
                    WHERE feed = ?
                    ORDER BY ts_recv, ts_event, publisher_id, instrument_id
                    """,
                    (feed,),
                ).fetchall()
            else:
                rows = conn.execute(
                    f"""
                    SELECT feed, publisher_id, instrument_id, ts_event, ts_recv,
                           security_update_action, rtype, payload_json, event_uid
                    FROM {TABLE_CURRENT}
                    WHERE publisher_id = ? AND feed = ?
                    ORDER BY ts_recv, ts_event, publisher_id, instrument_id
                    """,
                    (publisher_id, feed),
                ).fetchall()

        return pd.DataFrame([dict(r) for r in rows])

    def read_current_by_feed(
        self, *, feed: str, limit: int = 1000, newest_first: bool = True
    ) -> list[dict[str, Any]]:
        """
        Bounded read for operational diagnostics.
        Returns list[dict] to keep it lightweight and avoid pandas dependency in callers.
        """
        if limit <= 0:
            raise ValueError("limit must be > 0")

        self._backend.ensure_migrated()
        order = "DESC" if newest_first else "ASC"
        with self._backend.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT feed, publisher_id, instrument_id, ts_event, ts_recv,
                       security_update_action, rtype, payload_json, event_uid
                FROM {TABLE_CURRENT}
                WHERE feed = ?
                ORDER BY ts_recv {order}, ts_event {order}, publisher_id, instrument_id
                LIMIT ?;
                """,
                (feed, int(limit)),
            ).fetchall()
            return [dict(r) for r in rows]

    # -------------------------
    # Internal helpers
    # -------------------------

    @staticmethod
    def _normalise_frame(df: pd.DataFrame) -> pd.DataFrame:
        df = df.copy()

        # Case A: ts_recv is the index (preferred)

        if isinstance(df.index, pd.DatetimeIndex):
            ts_recv = ensure_utc_datetimeindex(df.index)
            df["ts_recv"] = ts_recv
            if df.index.name is None:
                df.index.name = "ts_recv"

        # Case B: ts_recv is provided as a column (acceptable)
        elif "ts_recv" in df.columns:
            df["ts_recv"] = ensure_utc_datetime_series(df["ts_recv"])

        # Otherwise: cannot proceed
        else:
            raise ValueError(
                "Instrument definitions frame must have ts_recv as a DatetimeIndex "
                "or as a 'ts_recv' column; got index type "
                f"{type(df.index).__name__} and no ts_recv column."
            )

        # Ensure ts_event is tz-aware UTC
        if "ts_event" in df.columns:
            df["ts_event"] = ensure_utc_datetime_series(df["ts_event"])
        else:
            raise ValueError(
                "Instrument definitions frame missing required column 'ts_event'"
            )

        return df

    @staticmethod
    def _build_event_rows(feed: str, df: pd.DataFrame) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []

        # Iterate row-wise; this is metadata-scale, correctness-first.
        for _, row in df.iterrows():
            # Construct a raw record dict that includes all columns + ts_recv
            record: dict[str, Any] = row.to_dict()
            ts_recv_z = fmt_run_ts(record["ts_recv"])
            ts_event_z = fmt_run_ts(record["ts_event"])

            # Canonical JSON payload for hashing; include ts_recv explicitly
            payload = canonical_json(record)
            uid = event_uid_from_payload_json(payload)

            events.append(
                {
                    "event_uid": uid,
                    "feed": feed,
                    "publisher_id": int(record["publisher_id"]),
                    "instrument_id": int(record["instrument_id"]),
                    "ts_event": ts_event_z,
                    "ts_recv": ts_recv_z,
                    "security_update_action": str(record.get("security_update_action")),
                    "rtype": (
                        None if pd.isna(record.get("rtype")) else int(record["rtype"])
                    ),
                    "payload_json": payload,
                }
            )

        # Deterministic ordering for stable behaviour
        events.sort(
            key=lambda e: (
                e["feed"],
                e["ts_recv"],
                e["ts_event"],
                e["publisher_id"],
                e["instrument_id"],
            )
        )
        return events

    @staticmethod
    def _insert_events(conn, events: Iterable[dict[str, Any]]) -> int:
        sql = f"""
            INSERT OR IGNORE INTO {TABLE_EVENTS} (
                event_uid, feed, publisher_id, instrument_id,
                ts_event, ts_recv, security_update_action, rtype, payload_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """

        rows = [
            (
                e["event_uid"],
                e["feed"],
                e["publisher_id"],
                e["instrument_id"],
                e["ts_event"],
                e["ts_recv"],
                e["security_update_action"],
                e["rtype"],
                e["payload_json"],
            )
            for e in events
        ]

        if not rows:
            return 0

        # Reliable inserted-count for INSERT OR IGNORE batches:
        before = conn.execute(f"SELECT COUNT(*) AS n FROM {TABLE_EVENTS}").fetchone()[
            "n"
        ]

        conn.executemany(sql, rows)

        after = conn.execute(f"SELECT COUNT(*) AS n FROM {TABLE_EVENTS}").fetchone()[
            "n"
        ]

        inserted = after - before
        # Defensive: should never be negative, but guard against unexpected concurrent writers.
        return int(inserted) if inserted > 0 else 0

    @staticmethod
    def _is_newer(a: tuple[str, str], b: tuple[str, str]) -> bool:
        """
        Compare (ts_recv, ts_event) tuples as canonical ISO8601Z strings.
        Return True if a > b.
        """
        return a > b

    def _update_current_view(self, conn, events: list[dict[str, Any]]) -> None:
        """
        Materialise the latest state per (publisher_id, instrument_id) using
        ordering key (ts_recv, ts_event, publisher_id, instrument_id).

        We update per key touched; metadata-scale, correctness-first.
        """
        # Reduce to latest event per key in this batch
        latest_by_key: dict[tuple[int, int], dict[str, Any]] = {}
        for e in events:
            key = (e["publisher_id"], e["instrument_id"])
            if key not in latest_by_key:
                latest_by_key[key] = e
                continue
            cur = latest_by_key[key]
            if self._is_newer(
                (e["ts_recv"], e["ts_event"]), (cur["ts_recv"], cur["ts_event"])
            ):
                latest_by_key[key] = e

        # For each touched key: compare to existing current row and upsert if newer
        select_sql = f"""
            SELECT ts_recv, ts_event
            FROM {TABLE_CURRENT}
            WHERE publisher_id = ? AND instrument_id = ?
        """

        upsert_sql = f"""
            INSERT INTO {TABLE_CURRENT} (
                publisher_id, instrument_id, feed, ts_event, ts_recv,
                security_update_action, rtype, payload_json, event_uid
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(publisher_id, instrument_id) DO UPDATE SET
                feed = excluded.feed,
                ts_event = excluded.ts_event,
                ts_recv  = excluded.ts_recv,
                security_update_action = excluded.security_update_action,
                rtype = excluded.rtype,
                payload_json = excluded.payload_json,
                event_uid = excluded.event_uid,
                updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """

        for (publisher_id, instrument_id), e in latest_by_key.items():
            row = conn.execute(select_sql, (publisher_id, instrument_id)).fetchone()
            if row is not None:
                existing = (row["ts_recv"], row["ts_event"])
                incoming = (e["ts_recv"], e["ts_event"])
                if not self._is_newer(incoming, existing):
                    continue

            conn.execute(
                upsert_sql,
                (
                    publisher_id,
                    instrument_id,
                    e["feed"],
                    e["ts_event"],
                    e["ts_recv"],
                    e["security_update_action"],
                    e["rtype"],
                    e["payload_json"],
                    e["event_uid"],
                ),
            )

    @staticmethod
    def _upsert_watermark(conn, *, feed: str, ts_recv_last: str) -> None:
        sql = f"""
            INSERT INTO {TABLE_WATERMARKS} (feed, ts_recv_last)
            VALUES (?, ?)
            ON CONFLICT(feed) DO UPDATE SET
                ts_recv_last = excluded.ts_recv_last,
                updated_at = (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        """
        conn.execute(sql, (feed, ts_recv_last))
