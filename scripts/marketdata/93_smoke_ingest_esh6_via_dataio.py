from __future__ import annotations

from pathlib import Path

import databento as db
from mxm.dataio.registry import list_registered, register
from mxm_secrets import get_secret

from mxm.v1.marketdata.databento.cost import enforce_cost_cap, estimate_cost_ohlcv_1d
from mxm.v1.marketdata.databento.fetcher import DatabentoOhlcv1dFetcher
from mxm.v1.marketdata.databento.normalize import normalize_ohlcv_1d
from mxm.v1.marketdata.databento.pull_via_dataio import pull_ohlcv_1d_via_dataio
from mxm.v1.marketdata.store.layout import MarketdataLayout
from mxm.v1.marketdata.store.parquet_store import write_daily_bars


def _run_ingest_once(
    *,
    client: db.Historical,
    layout: MarketdataLayout,
    dataset: str,
    symbol: str,
    start: str,
    end: str,
    cap_usd: float,
) -> Path:
    # ---- Cost gate ----
    est = estimate_cost_ohlcv_1d(
        client=client,
        dataset=dataset,
        symbols=symbol,
        stype_in="raw_symbol",
        start=start,
        end=end,
    )
    print(
        f"[cost] estimated_cost_usd={est.estimated_cost_usd:.8f} "
        f"billable_size={est.billable_size}"
    )
    enforce_cost_cap(estimated_cost_usd=est.estimated_cost_usd, cap_usd=cap_usd)

    # ---- Pull via DataIO + normalize ----
    df_raw = pull_ohlcv_1d_via_dataio(
        dataset=dataset,
        symbol=symbol,
        stype_in="raw_symbol",
        start=start,
        end=end,
        source="databento",
    )

    df = normalize_ohlcv_1d(df_raw, dataset=dataset, raw_symbol=symbol)

    # ---- Resolve store identity from returned data ----
    publisher_id = int(df["publisher_id"].iloc[0])
    instrument_id = int(df["instrument_id"].iloc[0])

    # ---- Write to canonical store ----
    write_daily_bars(
        layout=layout,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        df_new=df,
    )

    bars_path = layout.bars_path(
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
    )

    print(f"[ok] wrote {len(df)} rows -> {bars_path}")
    print(f"[info] ts_event range: {df['ts_event'].min()} .. {df['ts_event'].max()}")

    return bars_path


def main() -> None:
    # ---- Fixed golden-path parameters (Session 4) ----
    dataset = "GLBX.MDP3"
    symbol = "ESH6"
    start = "2026-01-03"
    end = "2026-01-13"
    cap_usd = 0.01  # strict cap for smoke test

    # ---- MXM state root ----
    mxm_root = Path.home() / ".mxm"
    layout = MarketdataLayout(root=mxm_root)

    # ---- Databento client (via mxm_secrets) ----
    api_key = get_secret("mxm/dev/databento/api-key")
    client = db.Historical(api_key)

    # ---- Register DataIO adapter (Fetcher) once ----
    # register() raises on duplicates, so guard it for this smoke script.
    if "databento" not in list_registered():
        register("databento", DatabentoOhlcv1dFetcher(client=client))
    print("[dataio] registered adapter 'databento'")

    # ---- Proof: run twice in-process with identical request inputs ----
    print("\n=== RUN 1 (expected: DATAIO MISS, Databento called) ===")
    path1 = _run_ingest_once(
        client=client,
        layout=layout,
        dataset=dataset,
        symbol=symbol,
        start=start,
        end=end,
        cap_usd=cap_usd,
    )

    print("\n=== RUN 2 (expected: DATAIO HIT, NO Databento call) ===")
    path2 = _run_ingest_once(
        client=client,
        layout=layout,
        dataset=dataset,
        symbol=symbol,
        start=start,
        end=end,
        cap_usd=cap_usd,
    )

    # ---- Minimal assertion / proof summary ----
    if path1 != path2:
        raise RuntimeError(f"Store path mismatch between runs: {path1} vs {path2}")

    print("\n=== PROOF SUMMARY ===")
    print("If you saw '[DATABENTO CALL]' only during RUN 1, caching is proven.")
    print(f"[ok] canonical store path: {path1}")


if __name__ == "__main__":
    main()
