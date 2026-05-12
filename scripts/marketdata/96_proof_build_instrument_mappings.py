from __future__ import annotations

from pathlib import Path

from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.v1.marketdata.mapping.vendors.databento.instrument_mappings import (
    build_mappings_for_product,
)
from mxm.v1.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend

# -------------------------
# Config (proof-scoped)
# -------------------------

# MVP proof target
PRODUCT_ID = "cme_emini_snp500_futures"

# Marketdata layout root (consistent with your sqlite path usage)
DEFAULT_ROOT = Path.home() / ".mxm"


def _definition_feed(*, dataset: str, parent: str, stype_in: str) -> str:
    # Canonical feed identity used in instrument_definition_* tables.
    # Must match Session 8 ingest.
    return f"databento:dataset={dataset}:schema=definition:stype_in={stype_in}:symbol={parent}"


def _load_vendor_maturities(
    backend: SQLiteBackend, *, feed: str
) -> set[tuple[int, int]]:
    """
    Pull maturity pairs (y,m) from instrument_definition_current for outright futures.
    """
    with backend.transaction() as conn:
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


def _load_refdata_contract_maturities(product_id: str) -> list[tuple[int, int]]:
    """
    Enumerate (year, month) pairs for a product's contracts using refdata:
      FuturesContract.period_id -> Period.first_date.year/month
    """
    api = RefDataAPI()

    contracts = api.get_contracts_for_product(product_id)
    periods = api.get_periods()

    period_by_id = {p.period_id: p for p in periods}

    pairs: set[tuple[int, int]] = set()
    missing_periods: set[str] = set()

    for c in contracts:
        p = period_by_id.get(c.period_id)
        if p is None:
            missing_periods.add(c.period_id)
            continue
        pairs.add((p.first_date.year, p.first_date.month))

    if missing_periods:
        # Not fatal for mapping proof, but important diagnostic.
        # If you see this, your refdata DB may be inconsistent.
        print(
            f"[warn] {len(missing_periods)} contracts referenced missing periods "
            f"(showing up to 10): {sorted(list(missing_periods))[:10]}"
        )

    return sorted(pairs)


def main() -> None:
    # 1) Databento product root wiring
    root = get_databento_product_root(PRODUCT_ID)
    dataset = root.dataset
    parent = root.parent
    stype_in = root.stype_in
    feed = _definition_feed(dataset=dataset, parent=parent, stype_in=stype_in)

    # 2) Marketdata DB backend
    layout = MarketdataLayout(root=DEFAULT_ROOT)
    backend = SQLiteBackend(layout=layout)

    # 3) Vendor candidate maturities (bounded truth from current view)
    vendor_maturities = _load_vendor_maturities(backend, feed=feed)
    if not vendor_maturities:
        raise RuntimeError(
            f"No vendor outrights found in instrument_definition_current for feed={feed!r}. "
            "Run the instrument definition ingest proof first."
        )

    # 4) Refdata contract maturities (internal truth)
    refdata_maturities = _load_refdata_contract_maturities(PRODUCT_ID)
    if not refdata_maturities:
        raise RuntimeError(
            f"No refdata maturities found for product_id={PRODUCT_ID!r}. "
            "Check mxm-refdata bootstrap/state."
        )

    # 5) Overlap set: only attempt mappings that can exist today
    overlap = [ym for ym in refdata_maturities if ym in vendor_maturities]
    if not overlap:
        raise RuntimeError(
            "No overlap between refdata contract maturities and vendor current definitions. "
            "This likely means your instrument_definition ingest window is too narrow."
        )

    # 6) Build mappings (append-only, deterministic, idempotent)
    report = build_mappings_for_product(
        backend,
        product_id=PRODUCT_ID,
        feed=feed,
        dataset=dataset,
        contracts=overlap,
    )

    print("=== MXM V1 — PROOF 96: build instrument definition mappings ===")
    print(f"product_id: {PRODUCT_ID}")
    print(f"dataset: {dataset}")
    print(f"feed: {feed}")
    print(f"vendor_outright_maturities: {len(vendor_maturities)}")
    print(f"refdata_maturities: {len(refdata_maturities)}")
    print(f"overlap_attempted: {len(overlap)}")
    print(f"inserted: {report['inserted']}")
    print(f"ignored: {report['ignored']}")
    print(f"unmapped: {len(report['unmapped'])}")

    # 7) Demonstrate a concrete resolution by reading mapping table
    # Choose the latest overlap maturity deterministically.
    y, m = overlap[-1]
    with backend.transaction() as conn:
        row = conn.execute(
            """
            SELECT publisher_id, instrument_id, raw_symbol, valid_from, valid_to
            FROM instrument_definition_mappings
            WHERE product_id = ?
              AND contract_year = ?
              AND contract_month = ?
            ORDER BY valid_from DESC
            LIMIT 1;
            """,
            (PRODUCT_ID, y, m),
        ).fetchone()

        if row is None:
            raise RuntimeError(
                f"Expected mapping missing for {PRODUCT_ID} {y:04d}-{m:02d}"
            )

        print(f"resolve({y:04d}-{m:02d}): {dict(row)}")


if __name__ == "__main__":
    main()
