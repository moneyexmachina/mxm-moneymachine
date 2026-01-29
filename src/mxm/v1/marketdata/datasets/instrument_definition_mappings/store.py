from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.marketdata.time_utils import utc_now_run_ts

# ---------------------------------------------------------------------------
# Results / report structures (typed, dataset-scoped)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResetProductResult:
    product_id: str
    rows_deleted: int


@dataclass(frozen=True)
class CandidateStats:
    feed: str
    dataset: str
    candidates_total: int
    candidates_with_maturity: int


@dataclass(frozen=True)
class BuildResult:
    product_id: str
    feed: str
    dataset: str

    contracts_attempted: int
    inserted: int
    ignored: int

    unmapped: list[tuple[int, int]]
    ambiguous: list[tuple[int, int, int]]

    candidate_stats: CandidateStats


# ---------------------------------------------------------------------------
# Internal model: mapping candidate extracted from instrument_definition_current
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class InstrumentDefinitionMappingsStore:
    """
    Dataset-domain store for instrument_definition_mappings.

    Responsibilities:
    - Own SQL for reading upstream *current* instrument definition state (feed-scoped)
      to produce mapping candidates.
    - Own SQL for inserting mappings into instrument_definition_mappings
      (append-only, deterministic identity via mapping_uid).
    - Provide product-scoped destructive reset for this derived dataset.
    - Provide read-only helpers for audits and downstream resolution.

    Non-responsibilities:
    - No vendor API calls (Databento, etc.)
    - No refdata calls / logic (contracts, periods) — orchestrator supplies contracts.
    - No policy decisions (what contracts to attempt, required coverage thresholds, etc.)
    """

    def __init__(self, *, backend: SQLiteBackend) -> None:
        self._backend = backend

    # ---------------------------------------------------------------------
    # Write API
    # ---------------------------------------------------------------------

    def reset_product(self, *, product_id: str) -> ResetProductResult:
        """
        Product-scoped destructive reset for mappings.

        Deletes all rows from instrument_definition_mappings for this product_id.
        This is intentionally separate from instrument_definitions.reset_feed().
        """
        self._backend.ensure_migrated()
        with self._backend.transaction() as conn:
            before = conn.execute(
                "SELECT COUNT(*) AS n FROM instrument_definition_mappings WHERE product_id = ?",
                (product_id,),
            ).fetchone()["n"]

            conn.execute(
                "DELETE FROM instrument_definition_mappings WHERE product_id = ?",
                (product_id,),
            )

            after = conn.execute(
                "SELECT COUNT(*) AS n FROM instrument_definition_mappings WHERE product_id = ?",
                (product_id,),
            ).fetchone()["n"]

        deleted = int(before - after)
        if deleted < 0:
            raise RuntimeError("reset_product produced negative delete count")
        return ResetProductResult(product_id=product_id, rows_deleted=deleted)

    def build_from_current_definitions(
        self,
        *,
        product_id: str,
        feed: str,
        dataset: str,
        # monthly maturities you want to map: (year, month)
        contracts: Iterable[tuple[int, int]],
        mapping_reason: str = "exact_maturity_match.instrument_class_F",
    ) -> BuildResult:
        """
        Build append-only mappings for a product using instrument_definition_current.

        Behaviour (MVP conservative):
        - 0 matches for contract maturity => record unmapped
        - >1 matches for contract maturity => record ambiguous and fail loudly at end
        - exactly 1 match => insert-or-ignore mapping row

        Idempotency:
        - insert uses deterministic mapping_uid with INSERT OR IGNORE, so reruns are safe.
        """
        self._backend.ensure_migrated()
        contracts_list = list(contracts)

        with self._backend.transaction() as conn:
            candidates, stats = self._load_outright_candidates(
                conn, feed=feed, dataset=dataset
            )

            by_maturity: dict[tuple[int, int], list[MappingCandidate]] = {}
            for c in candidates:
                by_maturity.setdefault((c.maturity_year, c.maturity_month), []).append(
                    c
                )

            inserted = 0
            ignored = 0
            unmapped: list[tuple[int, int]] = []
            ambiguous: list[tuple[int, int, int]] = []

            for y, m in contracts_list:
                matches = by_maturity.get((y, m), [])
                if len(matches) == 0:
                    unmapped.append((y, m))
                    continue
                if len(matches) > 1:
                    ambiguous.append((y, m, len(matches)))
                    continue

                did_insert = self._insert_mapping_append_only(
                    conn,
                    product_id=product_id,
                    contract_year=int(y),
                    contract_month=int(m),
                    candidate=matches[0],
                    mapping_reason=mapping_reason,
                )
                if did_insert:
                    inserted += 1
                else:
                    ignored += 1

            # Fail loudly if ambiguous exists: no silent choice.
            if ambiguous:
                raise RuntimeError(f"Ambiguous mappings encountered: {ambiguous}")

        return BuildResult(
            product_id=product_id,
            feed=feed,
            dataset=dataset,
            contracts_attempted=len(contracts_list),
            inserted=inserted,
            ignored=ignored,
            unmapped=unmapped,
            ambiguous=ambiguous,
            candidate_stats=stats,
        )

    # ---------------------------------------------------------------------
    # Read API
    # ---------------------------------------------------------------------

    def count_for_product(self, *, product_id: str) -> int:
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM instrument_definition_mappings WHERE product_id = ?",
                (product_id,),
            ).fetchone()
            return int(row["n"])

    def list_mapped_contracts(self, *, product_id: str) -> set[tuple[int, int]]:
        """
        Return the set of (contract_year, contract_month) keys present for product_id.
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            rows = conn.execute(
                """
                SELECT contract_year, contract_month
                FROM instrument_definition_mappings
                WHERE product_id = ?
                ORDER BY contract_year, contract_month;
                """,
                (product_id,),
            ).fetchall()

        return {(int(r["contract_year"]), int(r["contract_month"])) for r in rows}

    def get_latest_mapping_row(
        self, *, product_id: str, contract_year: int, contract_month: int
    ) -> Optional[dict[str, Any]]:
        """
        Return the latest mapping row for this contract key (for diagnostics).
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            row = conn.execute(
                """
                SELECT *
                FROM instrument_definition_mappings
                WHERE product_id = ?
                  AND contract_year = ?
                  AND contract_month = ?
                ORDER BY created_at DESC
                LIMIT 1;
                """,
                (product_id, int(contract_year), int(contract_month)),
            ).fetchone()
        return None if row is None else dict(row)

    def list_vendor_maturities_from_current(self, *, feed: str) -> set[tuple[int, int]]:
        """
        Read-only helper: maturity set present in instrument_definition_current for this feed.

        This is the dataset-derived analogue of the proof query you wrote.
        """
        self._backend.ensure_migrated()
        with self._backend.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                  json_extract(payload_json, '$.maturity_year')  AS maturity_year,
                  json_extract(payload_json, '$.maturity_month') AS maturity_month
                FROM instrument_definition_current
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

    # ---------------------------------------------------------------------
    # Internal helpers (SQL + deterministic identity)
    # ---------------------------------------------------------------------

    @staticmethod
    def _sha256_hex(s: str) -> str:
        return hashlib.sha256(s.encode("utf-8")).hexdigest()

    def _mapping_uid(
        self,
        *,
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
        """
        Deterministic mapping identity.

        Any change in the identity fields yields a new mapping row (append-only semantics).
        """
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
        return self._sha256_hex(key)

    def _load_outright_candidates(
        self, conn, *, feed: str, dataset: str
    ) -> tuple[list[MappingCandidate], CandidateStats]:
        """
        Extract Databento outright futures from instrument_definition_current for this feed.

        - Requires SQLite JSON1.
        - Filters to FUT + instrument_class 'F' (outright futures).
        """
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
        with_maturity = 0
        for r in rows:
            my = r["maturity_year"]
            mm = r["maturity_month"]
            if my is None or mm is None:
                # Still a candidate row, but cannot be used for maturity mapping.
                continue
            with_maturity += 1
            out.append(
                MappingCandidate(
                    feed=str(r["feed"]),
                    dataset=str(dataset),
                    publisher_id=int(r["publisher_id"]),
                    instrument_id=int(r["instrument_id"]),
                    raw_symbol=str(r["raw_symbol"]),
                    security_type=str(r["security_type"]),
                    instrument_class=str(r["instrument_class"]),
                    maturity_year=int(my),
                    maturity_month=int(mm),
                    activation=(
                        None if r["activation"] is None else str(r["activation"])
                    ),
                    expiration=(
                        None if r["expiration"] is None else str(r["expiration"])
                    ),
                    ts_event=str(r["ts_event"]),
                    definition_event_uid=str(r["event_uid"]),
                )
            )

        stats = CandidateStats(
            feed=feed,
            dataset=dataset,
            candidates_total=int(len(rows)),
            candidates_with_maturity=int(with_maturity),
        )
        return out, stats

    def _insert_mapping_append_only(
        self,
        conn,
        *,
        product_id: str,
        contract_year: int,
        contract_month: int,
        candidate: MappingCandidate,
        mapping_reason: str,
    ) -> bool:
        """
        Insert a mapping row using INSERT OR IGNORE (append-only).

        Validity window:
        - valid_from: candidate.activation if present, else candidate.ts_event
        - valid_to: candidate.expiration (nullable)
        """
        valid_from = candidate.activation or candidate.ts_event
        valid_to = candidate.expiration

        uid = self._mapping_uid(
            product_id=product_id,
            contract_year=int(contract_year),
            contract_month=int(contract_month),
            feed=candidate.feed,
            dataset=candidate.dataset,
            publisher_id=int(candidate.publisher_id),
            instrument_id=int(candidate.instrument_id),
            valid_from=str(valid_from),
            valid_to=(None if valid_to is None else str(valid_to)),
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
                int(contract_year),
                int(contract_month),
                candidate.feed,
                candidate.dataset,
                int(candidate.publisher_id),
                int(candidate.instrument_id),
                candidate.raw_symbol,
                candidate.security_type,
                candidate.instrument_class,
                int(candidate.maturity_year),
                int(candidate.maturity_month),
                candidate.activation,
                candidate.expiration,
                str(valid_from),
                (None if valid_to is None else str(valid_to)),
                candidate.definition_event_uid,
                mapping_reason,
            ),
        )
        return cur.rowcount == 1
