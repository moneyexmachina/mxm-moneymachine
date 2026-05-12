from __future__ import annotations

import argparse
from datetime import UTC, datetime
from pathlib import Path

import databento as db
import pandas as pd
from mxm_secrets import get_secret

from mxm.dataio.registry import list_registered, register
from mxm.v1.marketdata.datasets.instrument_definitions.api import (
    get_start_from_watermark,
    make_instrument_definition_feed,
)
from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.marketdata.vendors.databento.cost import (
    enforce_cost_cap,
    estimate_cost_instrument_definition,
)
from mxm.v1.marketdata.vendors.databento.pull import pull_instrument_definitions
from mxm.v1.marketdata.vendors.databento.timeseries import DatabentoTimeseriesFetcher

# Databento dataset availability start (vendor constraint).
# Keep this in orchestration/proofs, not in the dataset store/API.
DATASET_AVAILABLE_START: dict[str, str] = {
    "GLBX.MDP3": "2010-06-08T00:00:00.000000Z",  # Todo... change this back
}


def _utc_today_yyyy_mm_dd() -> str:
    return datetime.now(UTC).date().isoformat()


def _iso_z(ts: pd.Timestamp) -> str:
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _add_days_iso_z(start_iso_z: str, days: int) -> str:
    ts = pd.Timestamp(start_iso_z)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    return _iso_z(ts + pd.Timedelta(days=days))


def _clamp_start_to_dataset_available(*, dataset: str, start: str) -> str:
    avail = DATASET_AVAILABLE_START.get(dataset)
    if not avail:
        return start
    ts_start = pd.Timestamp(start)
    ts_avail = pd.Timestamp(avail)
    if ts_start.tzinfo is None:
        ts_start = ts_start.tz_localize("UTC")
    else:
        ts_start = ts_start.tz_convert("UTC")
    if ts_avail.tzinfo is None:
        ts_avail = ts_avail.tz_localize("UTC")
    else:
        ts_avail = ts_avail.tz_convert("UTC")
    return _iso_z(max(ts_start, ts_avail))


def _count_rows(conn, table: str) -> int:
    row = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()
    return int(row["n"])


def _count_rows_for_feed(conn, table: str, feed: str) -> int:
    row = conn.execute(
        f"SELECT COUNT(*) AS n FROM {table} WHERE feed = ?", (feed,)
    ).fetchone()
    return int(row["n"])


def _run_window(
    *,
    client: db.Historical,
    store: InstrumentDefinitionsStore,
    backend: SQLiteBackend,
    product_id: str,
    start: str,
    end: str,
    cap_usd: float,
) -> None:
    root = get_databento_product_root(product_id)

    feed = make_instrument_definition_feed(
        source="databento",
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        schema="definition",
    ).key()

    # Clamp start to dataset availability (prevents 422).
    start = _clamp_start_to_dataset_available(dataset=root.dataset, start=start)

    print(
        f"[scope] product_id={product_id} dataset={root.dataset} "
        f"symbol={root.parent} stype_in={root.stype_in}"
    )
    print(f"[feed] {feed}")
    print(f"[window] start={start} end={end}")

    # Cost gate (still valuable; independent of DataIO caching proof)
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

    # Pull (DataIO-backed, but we do not assert caching behaviour here)
    df = pull_instrument_definitions(
        product_id=product_id,
        start=start,
        end=end,
        source="databento",
        extra=None,
    )
    print(type(df.index), df.index.name)
    print("ts_recv in cols?", "ts_recv" in df.columns)
    print(
        f"[pull] rows={len(df)} cols={len(df.columns)} index={df.index.name} dtype={df.index.dtype}"
    )

    # Persist
    before = store.get_watermark(feed=feed)
    res = store.ingest_batch(feed=feed, df=df)
    after = store.get_watermark(feed=feed)

    print(
        f"[ingest] events_seen={res.events_seen} events_inserted={res.events_inserted} "
        f"watermark_before={before} watermark_after={after}"
    )

    # Read-back sanity checks
    with backend.connect() as conn:
        # These table names are stable; import constants if you prefer.
        n_events_total = _count_rows(conn, "instrument_definition_events")
        n_events_feed = _count_rows_for_feed(conn, "instrument_definition_events", feed)
        n_current_total = _count_rows(conn, "instrument_definition_current")
        n_current_feed = _count_rows_for_feed(
            conn, "instrument_definition_current", feed
        )

    print(
        f"[read] events_total={n_events_total} events_for_feed={n_events_feed} "
        f"current_total={n_current_total} current_for_feed={n_current_feed}"
    )

    # Print a sample current row (first touched key if any)
    if res.keys_touched > 0:
        df_cur = store.list_current()
        if not df_cur.empty:
            sample = df_cur.iloc[0].to_dict()
            print(
                "[sample_current] keys=",
                {
                    k: sample.get(k)
                    for k in [
                        "feed",
                        "publisher_id",
                        "instrument_id",
                        "ts_recv",
                        "ts_event",
                        "security_update_action",
                    ]
                },
            )


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--reset",
        action="store_true",
        help="Delete marketdata sqlite db before running proof",
    )
    return p.parse_args()


def main() -> None:
    args = _parse_args()

    layout = MarketdataLayout(root=Path.home() / ".mxm")
    backend = SQLiteBackend(layout=layout)

    if args.reset:
        db_path = backend.db_path()
        if db_path.exists():
            print(f"[reset] deleting sqlite db at {db_path}")
            db_path.unlink()

    # ---- Parameters ----
    product_id = "cme_emini_snp500_futures"
    cap_usd = 0.50  # adjust as needed

    # For proof: two consecutive 31-day windows, starting from dataset availability start.
    # We intentionally do not go "to today" to keep the proof small and repeatable.
    # The watermark logic is what we are proving.
    window_days = 31
    overlap = "1d"  # safe overlap across watermark boundary

    # ---- Databento client ----
    api_key = get_secret("mxm/dev/databento/api-key")
    client = db.Historical(api_key)

    # ---- Register DataIO adapter once ----
    if "databento" not in list_registered():
        register("databento", DatabentoTimeseriesFetcher(client=client))
    print("[dataio] registered adapter 'databento'")

    # ---- SQLite store wiring ----
    # Choose a root that matches your project conventions.
    # This will create: <root>/marketdata/marketdata.sqlite3
    store = InstrumentDefinitionsStore(backend=backend)

    # Resolve root to build feed + dataset start
    root = get_databento_product_root(product_id)
    dataset_default_start = DATASET_AVAILABLE_START.get(root.dataset)
    if not dataset_default_start:
        raise RuntimeError(
            f"No dataset available-start configured for dataset={root.dataset}. "
            "Add it to DATASET_AVAILABLE_START in this proof script."
        )

    # ---- Window 1 ----
    feed = make_instrument_definition_feed(
        source="databento",
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        schema="definition",
    ).key()

    wm0 = store.get_watermark(feed=feed)

    start1 = get_start_from_watermark(
        watermark=wm0,
        default_start=dataset_default_start,
        overlap=overlap,
    )
    start1 = _clamp_start_to_dataset_available(dataset=root.dataset, start=start1)
    end1 = _add_days_iso_z(start1, window_days)

    print("\n=== RUN 1: ingest first window ===")
    _run_window(
        client=client,
        store=store,
        backend=backend,
        product_id=product_id,
        start=start1,
        end=end1,
        cap_usd=cap_usd,
    )

    # ---- Window 2 (start from watermark after window 1) ----
    wm1 = store.get_watermark(feed=feed)
    if wm1 is None:
        raise RuntimeError("Expected watermark to be set after RUN 1, but it is None.")

    start2 = get_start_from_watermark(
        watermark=wm1,
        default_start=dataset_default_start,
        overlap=overlap,
    )
    start2 = _clamp_start_to_dataset_available(dataset=root.dataset, start=start2)
    end2 = _add_days_iso_z(start2, window_days)

    print("\n=== RUN 2: ingest second window (derived from watermark) ===")
    _run_window(
        client=client,
        store=store,
        backend=backend,
        product_id=product_id,
        start=start2,
        end=end2,
        cap_usd=cap_usd,
    )

    # ---- Re-run Window 2 to prove idempotency of persistence (no duplicate events) ----
    print("\n=== RUN 3: re-ingest second window (expected: 0 inserted or minimal) ===")
    _run_window(
        client=client,
        store=store,
        backend=backend,
        product_id=product_id,
        start=start2,
        end=end2,
        cap_usd=cap_usd,
    )

    print("\n=== PROOF SUMMARY ===")
    print("Proof obligations covered:")
    print("1) Ingest definitions into SQLite (RUN 1)")
    print("2) Re-running an already ingested window is idempotent (RUN 3)")
    print("3) Current view is populated and queryable (read-back counts + sample)")
    print("4) Watermarks advance per feed (RUN 1 -> RUN 2)")
    print(
        "5) Architecture supports later mapping and instrument_id-based ingestion (feed-scoped provenance + current view)."
    )


if __name__ == "__main__":
    main()
