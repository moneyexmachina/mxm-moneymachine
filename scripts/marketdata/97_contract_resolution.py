from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timezone
from pathlib import Path

from mxm_refdata.api.ref_data_api import RefDataAPI

from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    contract_year_month,
    resolve_databento_instrument,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend

# -------------------------
# Config (proof-scoped)
# -------------------------

PRODUCT_ID = "cme_emini_snp500_futures"
DEFAULT_ROOT = Path.home() / ".mxm"

# Choose which resolvable contract to demonstrate
# "earliest" is usually best for proofs; "latest" is sometimes better operationally.
PICK: str = "earliest"  # {"earliest","latest"}


@dataclass(frozen=True)
class MappingCoverage:
    min_year: int
    min_month: int
    max_year: int
    max_month: int

    def __str__(self) -> str:
        return (
            f"{self.min_year:04d}-{self.min_month:02d} .. "
            f"{self.max_year:04d}-{self.max_month:02d}"
        )


def _load_mapping_coverage(
    backend: SQLiteBackend, *, product_id: str
) -> MappingCoverage:
    """
    Determine the maturity coverage of the instrument_definition_mappings table
    for this product. This makes the "refdata starts earlier than vendor coverage"
    constraint explicit in Proof 97 output.
    """
    tx = getattr(backend, "transaction_no_migrate", backend.transaction)
    with tx() as conn:
        row = conn.execute(
            """
            SELECT
              MIN(contract_year)  AS min_year,
              MIN(CASE WHEN contract_year = (SELECT MIN(contract_year) FROM instrument_definition_mappings WHERE product_id = ?)
                       THEN contract_month END) AS min_month,
              MAX(contract_year)  AS max_year,
              MAX(CASE WHEN contract_year = (SELECT MAX(contract_year) FROM instrument_definition_mappings WHERE product_id = ?)
                       THEN contract_month END) AS max_month
            FROM instrument_definition_mappings
            WHERE product_id = ?;
            """,
            (product_id, product_id, product_id),
        ).fetchone()

    if row is None or row["min_year"] is None:
        raise RuntimeError(
            f"No rows found in instrument_definition_mappings for product_id={product_id!r}. "
            "Run Proof 96 (mapping build) first."
        )

    return MappingCoverage(
        min_year=int(row["min_year"]),
        min_month=int(row["min_month"]),
        max_year=int(row["max_year"]),
        max_month=int(row["max_month"]),
    )


def _load_mapped_maturities(
    backend: SQLiteBackend, *, product_id: str
) -> set[tuple[int, int]]:
    """
    Load all (year,month) pairs present in instrument_definition_mappings for this product.
    """
    tx = getattr(backend, "transaction_no_migrate", backend.transaction)
    with tx() as conn:
        rows = conn.execute(
            """
            SELECT DISTINCT contract_year, contract_month
            FROM instrument_definition_mappings
            WHERE product_id = ?
            ORDER BY contract_year, contract_month;
            """,
            (product_id,),
        ).fetchall()

    return {(int(r["contract_year"]), int(r["contract_month"])) for r in rows}


def _select_contract_for_resolution(
    backend: SQLiteBackend,
    *,
    product_id: str,
    pick: str,
):
    """
    Deterministically select a FuturesContract that is resolvable given current mapping coverage.

    Policy:
      - Enumerate refdata contracts for the product
      - Convert each contract.period_id -> (year,month)
      - Filter to those whose (year,month) exists in instrument_definition_mappings
      - Select earliest/latest by (year,month), stable tie-breaker on contract_id
    """
    api = RefDataAPI()
    contracts = api.get_contracts_for_product(product_id)
    if not contracts:
        raise RuntimeError(
            f"No refdata contracts returned for product_id={product_id!r}"
        )

    mapped = _load_mapped_maturities(backend, product_id=product_id)
    if not mapped:
        raise RuntimeError(
            f"No mapped maturities available for product_id={product_id!r}. "
            "Run Proof 96 (mapping build) first."
        )

    candidates = []
    for c in contracts:
        y, m = contract_year_month(c)
        if (y, m) in mapped:
            candidates.append((y, m, c.contract_id, c))

    if not candidates:
        coverage = _load_mapping_coverage(backend, product_id=product_id)
        raise RuntimeError(
            "No resolvable contracts found. "
            f"Refdata product_id={product_id!r} has contracts, "
            f"but none fall within mapping coverage ({coverage})."
        )

    candidates.sort(key=lambda t: (t[0], t[1], t[2]))  # (y,m,contract_id)
    chosen = candidates[0] if pick == "earliest" else candidates[-1]
    return chosen[3]


def main() -> None:
    layout = MarketdataLayout(root=DEFAULT_ROOT)
    backend = SQLiteBackend(layout=layout)

    # IMPORTANT: migrate once (hot path uses transaction_no_migrate)
    backend.ensure_migrated()

    coverage = _load_mapping_coverage(backend, product_id=PRODUCT_ID)
    contract = _select_contract_for_resolution(
        backend, product_id=PRODUCT_ID, pick=PICK
    )
    y, m = contract_year_month(contract)

    id1 = resolve_databento_instrument(backend, contract)
    id2 = resolve_databento_instrument(backend, contract)
    assert id1 == id2, f"non-deterministic resolution: {id1!r} != {id2!r}"

    print("=== MXM V1 — PROOF 97 (slice): resolve Databento instrument identity ===")
    print(f"product_id: {contract.product_id}")
    print(f"contract_id: {contract.contract_id}")
    print(f"period_id: {contract.period_id}")
    print(f"maturity: {y:04d}-{m:02d}")
    print(f"mapping_coverage: {coverage}")
    print(
        f"resolved: dataset={id1.dataset} publisher_id={id1.publisher_id} instrument_id={id1.instrument_id} raw_symbol={id1.raw_symbol}"
    )


if __name__ == "__main__":
    main()
