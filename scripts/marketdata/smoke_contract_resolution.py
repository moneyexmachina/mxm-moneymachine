from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    contract_year_month,
    resolve_databento_instrument,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend

DEFAULT_ROOT = Path.home() / ".mxm"


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
    backend: SQLiteBackend,
    *,
    product_id: str,
) -> MappingCoverage:
    tx = getattr(backend, "transaction_no_migrate", backend.transaction)
    with tx() as conn:
        row = conn.execute(
            """
            SELECT
              MIN(contract_year) AS min_year,
              MIN(
                CASE
                  WHEN contract_year = (
                    SELECT MIN(contract_year)
                    FROM instrument_definition_mappings
                    WHERE product_id = ?
                  )
                  THEN contract_month
                END
              ) AS min_month,
              MAX(contract_year) AS max_year,
              MAX(
                CASE
                  WHEN contract_year = (
                    SELECT MAX(contract_year)
                    FROM instrument_definition_mappings
                    WHERE product_id = ?
                  )
                  THEN contract_month
                END
              ) AS max_month
            FROM instrument_definition_mappings
            WHERE product_id = ?;
            """,
            (product_id, product_id, product_id),
        ).fetchone()

    if row is None or row["min_year"] is None:
        raise RuntimeError(
            f"No rows found in instrument_definition_mappings for product_id={product_id!r}. "
            "Build mappings first."
        )

    return MappingCoverage(
        min_year=int(row["min_year"]),
        min_month=int(row["min_month"]),
        max_year=int(row["max_year"]),
        max_month=int(row["max_month"]),
    )


def _load_mapping_rows_for_maturity(
    backend: SQLiteBackend,
    *,
    product_id: str,
    contract_year: int,
    contract_month: int,
) -> list[dict]:
    tx = getattr(backend, "transaction_no_migrate", backend.transaction)
    with tx() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM instrument_definition_mappings
            WHERE product_id = ?
              AND contract_year = ?
              AND contract_month = ?
            ORDER BY dataset, publisher_id, instrument_id;
            """,
            (product_id, contract_year, contract_month),
        ).fetchall()

    return [dict(r) for r in rows]


def _load_mapped_maturities(
    backend: SQLiteBackend,
    *,
    product_id: str,
) -> set[tuple[int, int]]:
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


def _get_contract_by_id_or_raise(contract_id: str):
    api = RefDataAPI()
    contract = api.get_contract_by_id(contract_id)
    if contract is None:
        raise RuntimeError(f"Contract not found in refdata: {contract_id!r}")
    return contract


def _get_contracts_for_product(product_id: str):
    api = RefDataAPI()
    contracts = api.get_contracts_for_product(product_id)
    if not contracts:
        raise RuntimeError(
            f"No contracts found in refdata for product_id={product_id!r}"
        )
    return contracts


def _looks_suspicious_raw_symbol(raw_symbol: str | None) -> bool:
    if raw_symbol is None:
        return True
    s = str(raw_symbol).strip()
    if not s:
        return True
    if s.isdigit():
        return True
    return False


def _print_single_contract_resolution(
    backend: SQLiteBackend,
    *,
    contract_id: str,
) -> None:
    contract = _get_contract_by_id_or_raise(contract_id)
    product_id = contract.product_id
    coverage = _load_mapping_coverage(backend, product_id=product_id)

    y, m = contract_year_month(contract)
    mapping_rows = _load_mapping_rows_for_maturity(
        backend,
        product_id=product_id,
        contract_year=y,
        contract_month=m,
    )

    resolved1 = resolve_databento_instrument(backend, contract)
    resolved2 = resolve_databento_instrument(backend, contract)
    assert (
        resolved1 == resolved2
    ), f"non-deterministic resolution: {resolved1!r} != {resolved2!r}"

    suspicious = _looks_suspicious_raw_symbol(resolved1.raw_symbol)

    print("=== MXM V1 — smoke_contract_resolution ===")
    print(f"product_id: {product_id}")
    print(f"contract_id: {contract.contract_id}")
    print(f"period_id: {contract.period_id}")
    print(f"maturity: {y:04d}-{m:02d}")
    print(f"mapping_coverage: {coverage}")
    print(
        "resolved: "
        f"dataset={resolved1.dataset} "
        f"publisher_id={resolved1.publisher_id} "
        f"instrument_id={resolved1.instrument_id} "
        f"raw_symbol={resolved1.raw_symbol}"
    )
    print(f"suspicious_raw_symbol: {suspicious}")
    print(f"mapping_rows_for_maturity: {len(mapping_rows)}")

    if mapping_rows:
        print("--- mapping rows for this maturity ---")
        for i, row in enumerate(mapping_rows, start=1):
            print(f"[{i}] {row}")


def _print_product_surface(
    backend: SQLiteBackend,
    *,
    product_id: str,
    limit: int | None,
) -> None:
    contracts = _get_contracts_for_product(product_id)
    mapped = _load_mapped_maturities(backend, product_id=product_id)
    coverage = _load_mapping_coverage(backend, product_id=product_id)

    rows: list[tuple[int, int, str, str, int, int, str | None, bool]] = []
    for c in contracts:
        y, m = contract_year_month(c)
        if (y, m) not in mapped:
            continue
        resolved = resolve_databento_instrument(backend, c)
        suspicious = _looks_suspicious_raw_symbol(resolved.raw_symbol)
        rows.append(
            (
                y,
                m,
                c.contract_id,
                resolved.dataset,
                resolved.publisher_id,
                resolved.instrument_id,
                resolved.raw_symbol,
                suspicious,
            )
        )

    rows.sort(key=lambda x: (x[0], x[1], x[2]))
    if limit is not None:
        rows = rows[:limit]

    print("=== MXM V1 — smoke_contract_resolution surface ===")
    print(f"product_id: {product_id}")
    print(f"mapping_coverage: {coverage}")
    print(
        "maturity | contract_id | dataset | publisher_id | instrument_id | raw_symbol | suspicious"
    )
    for (
        y,
        m,
        contract_id,
        dataset,
        publisher_id,
        instrument_id,
        raw_symbol,
        suspicious,
    ) in rows:
        print(
            f"{y:04d}-{m:02d} | "
            f"{contract_id} | "
            f"{dataset} | "
            f"{publisher_id} | "
            f"{instrument_id} | "
            f"{raw_symbol} | "
            f"{suspicious}"
        )


def main() -> None:
    p = argparse.ArgumentParser(
        description="MXM: smoke-test Databento contract resolution",
    )
    p.add_argument(
        "--root",
        default=None,
        help="MXM root directory (default: ~/.mxm)",
    )

    sub = p.add_subparsers(dest="mode", required=True)

    p_contract = sub.add_parser(
        "contract",
        help="Resolve one explicit contract_id and show matching mapping rows",
    )
    p_contract.add_argument("--contract-id", required=True)

    p_surface = sub.add_parser(
        "product",
        help="Resolve all mapped contracts for a product and print the surface",
    )
    p_surface.add_argument("--product-id", required=True)
    p_surface.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Optional maximum number of rows to print",
    )

    args = p.parse_args()

    root = Path(args.root) if args.root else DEFAULT_ROOT
    layout = MarketdataLayout(root=root)
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()

    if args.mode == "contract":
        _print_single_contract_resolution(
            backend,
            contract_id=args.contract_id,
        )
        return

    if args.mode == "product":
        _print_product_surface(
            backend,
            product_id=args.product_id,
            limit=args.limit,
        )
        return

    raise RuntimeError(f"unexpected mode={args.mode!r}")


if __name__ == "__main__":
    main()
