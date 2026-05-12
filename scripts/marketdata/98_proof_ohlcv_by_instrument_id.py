"""
scripts/marketdata/97_proof_ohlcv_by_instrument_id.py

Proof 97 — Session 10
Instrument-ID–based OHLCV ingestion from Databento with parquet persistence.

Proves:
1) FuturesContract -> DatabentoInstrumentIdentity via mapping table (no vendor calls)
2) Pull OHLCV-1D via DataIO using stype_in="instrument_id"
3) Normalize with raw_symbol sourced from mapping (not payload-dependent)
4) Persist to canonical parquet store keyed by (dataset, publisher_id, instrument_id)
5) Re-run in-process: DataIO cache hit + merge-write idempotency (no new rows)
"""

from __future__ import annotations

from pathlib import Path

import databento as db
from mxm_secrets import get_secret

from mxm.dataio.registry import list_registered, register
from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    DatabentoInstrumentIdentity,
    contract_year_month,
    resolve_databento_instrument,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.parquet.daily_bars import (
    read_daily_bars,
    write_daily_bars,
)
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.marketdata.vendors.databento.cost import (
    enforce_cost_cap,
    estimate_cost_ohlcv_1d,
)
from mxm.v1.marketdata.vendors.databento.normalize.ohlcv_1d import normalize_ohlcv_1d
from mxm.v1.marketdata.vendors.databento.pull import pull_ohlcv_1d_by_instrument_id
from mxm.v1.marketdata.vendors.databento.timeseries import DatabentoTimeseriesFetcher

# -------------------------
# Config (proof-scoped)
# -------------------------

PRODUCT_ID = "cme_emini_snp500_futures"

# Keep bounded. For the earliest mapped ES maturity (Jun-2010), this overlaps lifetime.
START = "2010-06-06T00:00:00Z"
END = "2010-07-06T00:00:00Z"

CAP_USD = 0.10
DEFAULT_ROOT = Path.home() / ".mxm"


def _select_contract_for_proof(backend: SQLiteBackend, *, product_id: str):
    """
    Deterministically select a FuturesContract that is mapped.

    Strategy:
      - choose earliest (contract_year, contract_month) present in instrument_definition_mappings
      - choose matching refdata FuturesContract
    """
    tx = getattr(backend, "transaction_no_migrate", backend.transaction)
    with tx() as conn:
        row = conn.execute(
            """
            SELECT contract_year, contract_month
            FROM instrument_definition_mappings
            WHERE product_id = ?
            ORDER BY contract_year, contract_month
            LIMIT 1;
            """,
            (product_id,),
        ).fetchone()

    if row is None:
        raise RuntimeError(
            f"No mappings found for product_id={product_id!r}. Run Proof 96 first."
        )

    target_y = int(row["contract_year"])
    target_m = int(row["contract_month"])

    api = RefDataAPI()
    contracts = api.get_contracts_for_product(product_id)
    if not contracts:
        raise RuntimeError(f"No refdata contracts found for product_id={product_id!r}")

    matches = []
    for c in contracts:
        y, m = contract_year_month(c)
        if (y, m) == (target_y, target_m):
            matches.append(c)

    if not matches:
        raise RuntimeError(
            f"Refdata has no contract matching mapped maturity {target_y:04d}-{target_m:02d}."
        )

    return sorted(matches, key=lambda c: c.contract_id)[0]


def _run_ingest_once(
    *,
    client: db.Historical,
    backend: SQLiteBackend,
    layout: MarketdataLayout,
    cap_usd: float,
) -> tuple[DatabentoInstrumentIdentity, Path, int]:
    """
    Returns (identity, bars_path, row_count_after_write)
    """
    contract = _select_contract_for_proof(backend, product_id=PRODUCT_ID)
    y, m = contract_year_month(contract)

    ident = resolve_databento_instrument(backend, contract)

    print("[resolve]")
    print(f"  product_id: {contract.product_id}")
    print(f"  contract_id: {contract.contract_id}")
    print(f"  period_id: {contract.period_id}")
    print(f"  maturity: {y:04d}-{m:02d}")
    print(
        f"  resolved: dataset={ident.dataset} publisher_id={ident.publisher_id} "
        f"instrument_id={ident.instrument_id} raw_symbol={ident.raw_symbol}"
    )
    print(f"  window: {START} .. {END}")

    # ---- Cost gate ----
    est = estimate_cost_ohlcv_1d(
        client=client,
        dataset=ident.dataset,
        symbols=str(ident.instrument_id),
        stype_in="instrument_id",
        start=START,
        end=END,
    )
    print(
        f"[cost] estimated_cost_usd={est.estimated_cost_usd:.8f} "
        f"billable_size={est.billable_size}"
    )
    enforce_cost_cap(estimated_cost_usd=est.estimated_cost_usd, cap_usd=cap_usd)

    # ---- Pull via DataIO + normalize ----
    df_raw = pull_ohlcv_1d_by_instrument_id(
        dataset=ident.dataset,
        instrument_id=ident.instrument_id,
        start=START,
        end=END,
        source="databento",
    )

    df = normalize_ohlcv_1d(df_raw, dataset=ident.dataset, raw_symbol=ident.raw_symbol)

    # ---- Persist via canonical store (merge/dedup) ----
    write_daily_bars(
        layout=layout,
        dataset=ident.dataset,
        publisher_id=ident.publisher_id,
        instrument_id=ident.instrument_id,
        df_new=df,
    )

    bars_path = layout.bars_path(
        dataset=ident.dataset,
        publisher_id=ident.publisher_id,
        instrument_id=ident.instrument_id,
    )

    df_read = read_daily_bars(
        layout=layout,
        dataset=ident.dataset,
        publisher_id=ident.publisher_id,
        instrument_id=ident.instrument_id,
    )
    n = len(df_read)

    print(f"[ok] wrote+merged rows={len(df)} stored_rows={n} -> {bars_path}")
    print(
        f"[info] stored ts_event range: {df_read['ts_event'].min()} .. {df_read['ts_event'].max()}"
    )

    return ident, bars_path, n


def main() -> None:
    layout = MarketdataLayout(root=DEFAULT_ROOT)
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()

    # ---- Databento client ----
    api_key = get_secret("mxm/dev/databento/api-key")
    client = db.Historical(api_key)

    # ---- Register DataIO adapter once ----
    if "databento" not in list_registered():
        register("databento", DatabentoTimeseriesFetcher(client=client))
    print("[dataio] registered adapter 'databento'")

    print("\n=== RUN 1 (expected: DATAIO MISS, Databento called) ===")
    ident1, path1, n1 = _run_ingest_once(
        client=client,
        backend=backend,
        layout=layout,
        cap_usd=CAP_USD,
    )

    print("\n=== RUN 2 (expected: DATAIO HIT, NO Databento call) ===")
    ident2, path2, n2 = _run_ingest_once(
        client=client,
        backend=backend,
        layout=layout,
        cap_usd=CAP_USD,
    )

    # ---- Assertions / proof closure ----
    if (ident1.dataset, ident1.publisher_id, ident1.instrument_id) != (
        ident2.dataset,
        ident2.publisher_id,
        ident2.instrument_id,
    ):
        raise RuntimeError(
            "Identity mismatch between runs (non-deterministic resolution)."
        )

    if path1 != path2:
        raise RuntimeError(f"Store path mismatch between runs: {path1} vs {path2}")

    if n1 != n2:
        raise RuntimeError(
            f"Merge idempotency failure: stored rows changed (n1={n1}, n2={n2})"
        )

    # Additional invariant: ts_event strictly increasing
    df_final = read_daily_bars(
        layout=layout,
        dataset=ident1.dataset,
        publisher_id=ident1.publisher_id,
        instrument_id=ident1.instrument_id,
    )
    if not df_final["ts_event"].is_monotonic_increasing:
        raise RuntimeError(
            "Invariant failure: ts_event not monotonic increasing after merge."
        )

    print("\n=== PROOF SUMMARY ===")
    print("If you saw '[DATABENTO CALL]' only during RUN 1, caching is proven.")
    print(
        f"[ok] identity: dataset={ident1.dataset} publisher_id={ident1.publisher_id} instrument_id={ident1.instrument_id}"
    )
    print(f"[ok] raw_symbol injected: {ident1.raw_symbol}")
    print(f"[ok] canonical store path: {path1}")
    print(f"[ok] stored row-count stable across rerun: {n1}")


if __name__ == "__main__":
    main()
