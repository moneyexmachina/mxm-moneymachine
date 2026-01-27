from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Literal

import pandas as pd

from mxm.v1.marketdata.datasets.instrument_definitions.api import (
    get_start_from_watermark,
    make_instrument_definition_feed,
)
from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
    ResetFeedResult,
)
from mxm.v1.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)
from mxm.v1.marketdata.vendors.databento.cost import (
    enforce_cost_cap,
    estimate_cost_instrument_definition,
)
from mxm.v1.marketdata.vendors.databento.dataset_range import (
    clamp_end,
    clamp_start,
    get_dataset_range,
)
from mxm.v1.marketdata.vendors.databento.pull import pull_instrument_definitions

# Keep vendor availability constraints in orchestration/config, not in the dataset store.
# You can later move this into config.
DATASET_AVAILABLE_START: dict[str, str] = {
    "GLBX.MDP3": "2010-06-06T00:00:00.000000Z",
}


Mode = Literal["bootstrap", "update"]


@dataclass(frozen=True)
class WindowRun:
    start: str
    end: str
    estimated_cost_usd: float
    events_seen: int
    events_inserted: int
    watermark_before: str | None
    watermark_after: str | None


@dataclass()
class InstrumentDefinitionsOrchestratorReport:
    product_id: str
    feed: str
    dataset: str
    symbol: str
    stype_in: str

    mode: Mode
    ts_utc: str

    reset_requested: bool
    reset_result: ResetFeedResult | None

    watermark_before: str | None
    watermark_after: str | None

    windows_attempted: int
    requested_end: str
    requested_end_raw: str | None = None
    dataset_range_end: str | None = None
    dataset_range_start: str | None = None
    windows: list[WindowRun] = field(default_factory=list)

    cost_cap_usd: float = 0.0
    cost_usd_total: float = 0.0

    stopped_reason: str = (
        ""  # e.g. "reached_end" | "max_windows" | "cost_cap" | "no_progress"
    )

    cost_used_usd: float = 0.0
    stage_status: str = ""
    stop_reason: str = ""
    counts: dict[str, object] = field(default_factory=dict)


def _utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _add_days_iso_z(start_iso_z: str, days: int) -> str:
    ts = pd.Timestamp(start_iso_z)
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    else:
        ts = ts.tz_convert("UTC")
    ts2 = ts + pd.Timedelta(days=days)
    return ts2.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


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

    ts = max(ts_start, ts_avail)
    return ts.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _is_vendor_final(
    *, watermark: str | None, dataset_end: str | None, tolerance: str = "1D"
) -> bool:
    if watermark is None or dataset_end is None:
        return False
    wm = pd.Timestamp(watermark)
    end = pd.Timestamp(dataset_end)
    if wm.tzinfo is None:
        wm = wm.tz_localize("UTC")
    else:
        wm = wm.tz_convert("UTC")
    if end.tzinfo is None:
        end = end.tz_localize("UTC")
    else:
        end = end.tz_convert("UTC")
    return wm >= (end - pd.Timedelta(tolerance))


def ingest_instrument_definitions(
    *,
    store: InstrumentDefinitionsStore,
    product_id: str,
    client,  # databento.Historical; keep untyped here to avoid hard dependency
    mode: Mode,
    cost_cap_usd: float,
    window_days: int = 31,
    overlap: str = "1d",
    max_windows: int = 3,
    reset: bool = False,
    end: str | None = None,
) -> InstrumentDefinitionsOrchestratorReport:
    """
    Orchestrate ingestion of instrument definition events for a single product-root feed.

    - feed-scoped watermark (ts_recv_last) drives forward ingestion
    - bootstrap: from default start (if watermark None) until end/limits
    - update: from watermark until end/limits
    - reset: destructive feed-scoped reset before bootstrapping
    """
    if cost_cap_usd <= 0:
        raise ValueError("cost_cap_usd must be > 0")
    if window_days <= 0:
        raise ValueError("window_days must be > 0")
    if max_windows <= 0:
        raise ValueError("max_windows must be > 0")

    root = get_databento_product_root(product_id)

    feed = make_instrument_definition_feed(
        source="databento",
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        schema="definition",
    ).key()
    print(
        f"[defs] product_id={product_id} "
        f"feed={feed} "
        f"mode={mode} "
        f"reset={reset} "
        f"cost_cap_usd={cost_cap_usd:.2f}"
    )
    reset_result: ResetFeedResult | None = None
    if reset:
        reset_result = store.reset_feed(feed=feed)
        if reset:
            print(
                f"[defs][reset] events_deleted={reset_result.events_deleted} "
                f"current_deleted={reset_result.current_deleted} "
                f"watermark_deleted={reset_result.watermark_deleted}"
            )
    watermark_before = store.get_watermark(feed=feed)
    avail = get_dataset_range(
        client=client,
        dataset=root.dataset,
        schema="definition",  # or root.schema if you prefer to pass it through
    )
    default_start = avail.start
    requested_end_raw = end or _utc_now_iso_z()
    requested_end = clamp_end(end=requested_end_raw, available=avail)
    remaining_cap = float(cost_cap_usd)

    report = InstrumentDefinitionsOrchestratorReport(
        product_id=product_id,
        feed=feed,
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        mode=mode,
        ts_utc=_utc_now_iso_z(),
        reset_requested=reset,
        reset_result=reset_result,
        watermark_before=watermark_before,
        watermark_after=watermark_before,
        requested_end=requested_end,
        requested_end_raw=requested_end_raw,
        dataset_range_start=avail.start,
        dataset_range_end=avail.end,
        windows_attempted=0,
        cost_cap_usd=float(cost_cap_usd),
        cost_usd_total=0.0,
        stopped_reason="",
    )

    # Determine initial start from watermark
    start = get_start_from_watermark(
        watermark=watermark_before,
        default_start=default_start,
        overlap=overlap,
    )
    start = clamp_start(start=start, available=avail)

    last_watermark = watermark_before
    print(
        f"[defs][start] watermark_before={watermark_before} "
        f"default_start={default_start} "
        f"computed_start={start} "
        f"requested_end={requested_end}"
    )
    for _ in range(max_windows):
        # Stop if we are at or beyond the end target
        if pd.Timestamp(start) >= pd.Timestamp(requested_end):
            report.stopped_reason = "reached_end"
            break

        # Compute this window's end (bounded by requested_end)
        end_i = _add_days_iso_z(start, window_days)
        if pd.Timestamp(end_i) > pd.Timestamp(requested_end):
            end_i = requested_end
        print(
            f"[defs][window {report.windows_attempted + 1}] start={start} end={end_i}"
        )
        # Estimate and gate cost
        est = estimate_cost_instrument_definition(
            client=client,
            dataset=root.dataset,
            symbols=root.parent,
            stype_in=root.stype_in,
            start=start,
            end=end_i,
        )

        print(
            f"[defs][cost] estimated_cost_usd={est.estimated_cost_usd:.6f} "
            f"remaining_cap_usd={remaining_cap:.6f}"
        )
        enforce_cost_cap(
            estimated_cost_usd=est.estimated_cost_usd, cap_usd=remaining_cap
        )

        # Pull + ingest
        df = pull_instrument_definitions(
            product_id=product_id,
            start=start,
            end=end_i,
            source="databento",
            extra=None,
        )
        wm_before_i = store.get_watermark(feed=feed)
        res = store.ingest_batch(feed=feed, df=df)
        wm_after_i = store.get_watermark(feed=feed)
        print(
            f"[defs][ingest] "
            f"events_seen={res.events_seen} "
            f"events_inserted={res.events_inserted} "
            f"watermark_before={wm_before_i} "
            f"watermark_after={wm_after_i}"
        )
        report.windows_attempted += 1
        report.cost_usd_total += float(est.estimated_cost_usd)
        remaining_cap -= float(est.estimated_cost_usd)

        report.windows.append(
            WindowRun(
                start=start,
                end=end_i,
                estimated_cost_usd=float(est.estimated_cost_usd),
                events_seen=int(res.events_seen),
                events_inserted=int(res.events_inserted),
                watermark_before=wm_before_i,
                watermark_after=wm_after_i,
            )
        )

        # Progress / safety stop

        if wm_after_i == last_watermark:
            if _is_vendor_final(
                watermark=wm_after_i,
                dataset_end=report.dataset_range_end,
                tolerance="1D",
            ):
                report.stopped_reason = "vendor_final"
                report.watermark_after = wm_after_i
                print(
                    f"[defs][stop] vendor_final (watermark at dataset end: {wm_after_i})"
                )
            else:
                report.stopped_reason = "no_progress"
                report.watermark_after = wm_after_i
                print(
                    f"[defs][stop] no_progress (watermark did not advance: {wm_after_i})"
                )
            break

        # Advance start from the updated watermark
        last_watermark = wm_after_i
        report.watermark_after = wm_after_i
        start = get_start_from_watermark(
            watermark=wm_after_i,
            default_start=default_start,
            overlap=overlap,
        )
        start = _clamp_start_to_dataset_available(dataset=root.dataset, start=start)

        # Cost cap stop
        if remaining_cap <= 0:
            report.stopped_reason = "cost_cap"
            print(
                f"[defs][stop] cost_cap_exhausted "
                f"spent={report.cost_usd_total:.6f} "
                f"cap={cost_cap_usd:.6f}"
            )
            break

    if report.stopped_reason == "":
        report.stopped_reason = "max_windows"

    if report.stopped_reason == "max_windows":
        print(f"[defs][stop] max_windows reached ({max_windows})")
    elif report.stopped_reason == "reached_end":
        print("[defs][stop] reached requested_end")
    else:
        print(f"[defs][stop] {report.stopped_reason}")
    print(
        f"[defs][done] windows={report.windows_attempted} "
        f"cost_usd_total={report.cost_usd_total:.6f} "
        f"watermark_after={report.watermark_after} "
        f"stopped_reason={report.stopped_reason}"
    )

    # --- meta-orchestrator surface  ---
    report.cost_used_usd = float(report.cost_usd_total)
    report.stop_reason = report.stopped_reason
    events_inserted_total = int(sum(w.events_inserted for w in report.windows))

    if report.stopped_reason in ("no_progress",):
        # conservative: if we inserted something this run, do not block downstream
        report.stage_status = "halted" if events_inserted_total == 0 else "ok"
    else:
        report.stage_status = "ok"

    report.counts = {
        "windows_attempted": int(report.windows_attempted),
        "events_seen_total": int(sum(w.events_seen for w in report.windows)),
        "events_inserted_total": events_inserted_total,
        "watermark_before": report.watermark_before,
        "watermark_after": report.watermark_after,
        "dataset": report.dataset,
        "symbol": report.symbol,
        "stype_in": report.stype_in,
        "stopped_reason": report.stopped_reason,
    }

    return report
