from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Iterable

from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.utils.time_utils import utc_now_run_ts


@dataclass(frozen=True)
class MappingCandidate:
    feed: str
    dataset: str
    publisher_id: int
    instrument_id: int
    raw_symbol: str
    security_type: str
    instrument_class: str
    maturity_year: int
    maturity_month: int
    activation: str | None
    expiration: str | None
    ts_event: str
    definition_event_uid: str


def _sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def _mapping_uid(
    product_id: str,
    contract_year: int,
    contract_month: int,
    feed: str,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    valid_from: str,
    valid_to: str | None,
) -> str:
    # Deterministic identity. Any change produces a new row (append-only semantics).
    key = "|".join(
        [
            product_id,
            f"{contract_year:04d}",
            f"{contract_month:02d}",
            feed,
            dataset,
            str(publisher_id),
            str(instrument_id),
            valid_from,
            valid_to or "",
        ]
    )
    return _sha256_hex(key)


def load_databento_outright_candidates(
    conn,
    *,
    feed: str,
    dataset: str,
) -> list[MappingCandidate]:
    # NOTE: relies on SQLite JSON1 functions.
    rows = conn.execute(
        """
        SELECT
          feed,
          publisher_id,
          instrument_id,
          ts_event,
          event_uid,
          json_extract(payload_json, '$.raw_symbol') as raw_symbol,
          json_extract(payload_json, '$.security_type') as security_type,
          json_extract(payload_json, '$.instrument_class') as instrument_class,
          json_extract(payload_json, '$.maturity_year') as maturity_year,
          json_extract(payload_json, '$.maturity_month') as maturity_month,
          json_extract(payload_json, '$.activation') as activation,
          json_extract(payload_json, '$.expiration') as expiration
        FROM instrument_definition_current
        WHERE feed = ?
          AND json_extract(payload_json, '$.security_type') = 'FUT'
          AND json_extract(payload_json, '$.instrument_class') = 'F'
        ORDER BY maturity_year, maturity_month;
        """,
        (feed,),
    ).fetchall()

    out: list[MappingCandidate] = []
    for r in rows:
        out.append(
            MappingCandidate(
                feed=str(r["feed"]),
                dataset=dataset,
                publisher_id=int(r["publisher_id"]),
                instrument_id=int(r["instrument_id"]),
                raw_symbol=str(r["raw_symbol"]),
                security_type=str(r["security_type"]),
                instrument_class=str(r["instrument_class"]),
                maturity_year=int(r["maturity_year"]),
                maturity_month=int(r["maturity_month"]),
                activation=(None if r["activation"] is None else str(r["activation"])),
                expiration=(None if r["expiration"] is None else str(r["expiration"])),
                ts_event=str(r["ts_event"]),
                definition_event_uid=str(r["event_uid"]),
            )
        )
    return out


def upsert_mappings_append_only(
    conn,
    *,
    product_id: str,
    contract_year: int,
    contract_month: int,
    candidate: MappingCandidate,
    mapping_reason: str,
) -> tuple[bool, str]:
    # Choose validity window for resolution. Prefer activation; fall back to ts_event.
    valid_from = candidate.activation or candidate.ts_event
    valid_to = candidate.expiration

    uid = _mapping_uid(
        product_id=product_id,
        contract_year=contract_year,
        contract_month=contract_month,
        feed=candidate.feed,
        dataset=candidate.dataset,
        publisher_id=candidate.publisher_id,
        instrument_id=candidate.instrument_id,
        valid_from=valid_from,
        valid_to=valid_to,
    )

    cur = conn.execute(
        """
        INSERT OR IGNORE INTO instrument_definition_mappings (
          mapping_uid, created_at,
          product_id, contract_year, contract_month,
          feed, dataset, publisher_id, instrument_id,
          raw_symbol, security_type, instrument_class,
          maturity_year, maturity_month,
          activation, expiration,
          valid_from, valid_to,
          definition_event_uid, mapping_reason
        ) VALUES (
          ?, ?,
          ?, ?, ?,
          ?, ?, ?, ?,
          ?, ?, ?,
          ?, ?,
          ?, ?,
          ?, ?,
          ?, ?
        );
        """,
        (
            uid,
            utc_now_run_ts(),
            product_id,
            contract_year,
            contract_month,
            candidate.feed,
            candidate.dataset,
            candidate.publisher_id,
            candidate.instrument_id,
            candidate.raw_symbol,
            candidate.security_type,
            candidate.instrument_class,
            candidate.maturity_year,
            candidate.maturity_month,
            candidate.activation,
            candidate.expiration,
            valid_from,
            valid_to,
            candidate.definition_event_uid,
            mapping_reason,
        ),
    )

    inserted = cur.rowcount == 1
    return inserted, uid


def build_mappings_for_product(
    backend: SQLiteBackend,
    *,
    product_id: str,
    feed: str,
    dataset: str,
    # Iterable of (year, month) contracts you want to attempt to map (monthly MVP)
    contracts: Iterable[tuple[int, int]],
) -> dict[str, object]:
    """
    Deterministically build append-only mappings for a product from current definitions.

    Conservative behaviour:
    - 0 matches for a contract: record as unmapped
    - >1 matches: record as ambiguous and raise (no silent choice)
    """
    mapping_reason = "exact_maturity_match.instrument_class_F"

    with backend.transaction() as conn:
        candidates = load_databento_outright_candidates(
            conn, feed=feed, dataset=dataset
        )

        # key: (y, m) -> list[candidate]
        by_maturity: dict[tuple[int, int], list[MappingCandidate]] = {}
        for c in candidates:
            by_maturity.setdefault((c.maturity_year, c.maturity_month), []).append(c)

        inserted = 0
        ignored = 0
        unmapped: list[tuple[int, int]] = []
        ambiguous: list[tuple[int, int, int]] = []

        for y, m in contracts:
            matches = by_maturity.get((y, m), [])
            if len(matches) == 0:
                unmapped.append((y, m))
                continue
            if len(matches) > 1:
                ambiguous.append((y, m, len(matches)))
                continue

            did_insert, _uid = upsert_mappings_append_only(
                conn,
                product_id=product_id,
                contract_year=y,
                contract_month=m,
                candidate=matches[0],
                mapping_reason=mapping_reason,
            )
            if did_insert:
                inserted += 1
            else:
                ignored += 1

        if ambiguous:
            # Fail loudly; do not pretend the mapping is safe.
            raise RuntimeError(f"Ambiguous mappings encountered: {ambiguous}")

        return {
            "product_id": product_id,
            "feed": feed,
            "dataset": dataset,
            "candidates": len(candidates),
            "inserted": inserted,
            "ignored": ignored,
            "unmapped": unmapped,
            "ambiguous": ambiguous,
        }
