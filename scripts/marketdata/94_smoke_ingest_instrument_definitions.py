from __future__ import annotations

from datetime import UTC, datetime

import databento as db
from mxm_secrets import get_secret
from rich import print as rprint

from mxm.dataio.registry import list_registered, register
from mxm.v1.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)
from mxm.v1.marketdata.vendors.databento.cost import (
    enforce_cost_cap,
    estimate_cost_instrument_definition,
)
from mxm.v1.marketdata.vendors.databento.pull import pull_instrument_definitions
from mxm.v1.marketdata.vendors.databento.timeseries import DatabentoTimeseriesFetcher


def _utc_today_yyyy_mm_dd() -> str:
    return datetime.now(UTC).date().isoformat()


def _brief_df_summary(df) -> None:
    cols = list(df.columns)
    print(f"[df] rows={len(df)} cols={len(cols)}")

    # ---- ts_event window ----
    if "ts_event" in df.columns:
        ts_min = df["ts_event"].min()
        ts_max = df["ts_event"].max()
        print(f"[df] ts_event range: {ts_min} .. {ts_max}")

    # ---- cardinalities ----
    if "instrument_id" in df.columns:
        print(
            f"[df] unique instrument_id: {int(df['instrument_id'].nunique(dropna=True))}"
        )
    if "raw_symbol" in df.columns:
        print(f"[df] unique raw_symbol: {int(df['raw_symbol'].nunique(dropna=True))}")

    # ---- action counts ----
    if "security_update_action" in df.columns:
        vc = df["security_update_action"].value_counts(dropna=False)
        print("[df] security_update_action:")
        for k, v in vc.items():
            print(f"  - {k!s}: {int(v)}")

    # ---- instrument class counts ----
    if "instrument_class" in df.columns:
        vc = df["instrument_class"].value_counts(dropna=False)
        print("[df] instrument_class:")
        for k, v in vc.items():
            print(f"  - {k!s}: {int(v)}")

    # ---- compact sample table ----
    sample_cols = [
        "ts_event",
        "security_update_action",
        "instrument_class",
        "publisher_id",
        "instrument_id",
        "raw_symbol",
        "activation",
        "expiration",
        "maturity_year",
        "maturity_month",
        "maturity_day",
    ]
    sample_cols = [c for c in sample_cols if c in df.columns]

    if sample_cols:
        df_sample = df[sample_cols].head(8).copy()
        print("[df] sample (first 8 rows):")
        try:
            print(df_sample.to_string(index=False))
        except Exception:
            rprint(df_sample)


def _run_once(
    *,
    client: db.Historical,
    product_id: str,
    start: str,
    end: str,
    cap_usd: float,
) -> str:
    # ---- Resolve product root (diagnostic) ----
    root = get_databento_product_root(product_id)
    print(
        f"[root] product_id={product_id} dataset={root.dataset} "
        f"parent={root.parent} stype_in={root.stype_in}"
    )

    # ---- Cost gate ----
    est = estimate_cost_instrument_definition(
        client=client,
        dataset=root.dataset,
        symbols=root.parent,
        stype_in=root.stype_in,
        start=start,
        end=end,
    )
    print(
        f"[cost] estimated_cost_usd={est.estimated_cost_usd:.8f} "
        f"billable_size={est.billable_size}"
    )
    enforce_cost_cap(estimated_cost_usd=est.estimated_cost_usd, cap_usd=cap_usd)

    # ---- Pull via DataIO ----
    df = pull_instrument_definitions(
        product_id=product_id,
        start=start,
        end=end,
        source="databento",
        extra=None,
    )
    _brief_df_summary(df)

    # Proof artifact (stable across runs as long as inputs are stable)
    return f"{product_id}:{start}:{end}"


def main() -> None:
    # ---- Parameters ----
    product_id = "cme_emini_snp500_futures"
    start = "2025-11-06"
    end = _utc_today_yyyy_mm_dd()
    cap_usd = 0.25  # still strict; adjust if you later expand product roots

    # ---- Databento client ----
    api_key = get_secret("mxm/dev/databento/api-key")
    client = db.Historical(api_key)

    # ---- Register DataIO adapter (Fetcher) once ----
    if "databento" not in list_registered():
        register("databento", DatabentoTimeseriesFetcher(client=client))
    print("[dataio] registered adapter 'databento'")

    # ---- Proof: run twice in-process with identical request inputs ----
    print("\n=== RUN 1 (expected: DATAIO MISS, Databento called) ===")
    key1 = _run_once(
        client=client,
        product_id=product_id,
        start=start,
        end=end,
        cap_usd=cap_usd,
    )

    print("\n=== RUN 2 (expected: DATAIO HIT, NO Databento call) ===")
    key2 = _run_once(
        client=client,
        product_id=product_id,
        start=start,
        end=end,
        cap_usd=cap_usd,
    )

    if key1 != key2:
        raise RuntimeError(f"Proof key mismatch between runs: {key1} vs {key2}")

    print("\n=== PROOF SUMMARY ===")
    print("If you saw '[DATABENTO CALL]' only during RUN 1, caching is proven.")
    print(f"[ok] proof key: {key1}")


if __name__ == "__main__":
    main()
