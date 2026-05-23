from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, cast

import databento as db
import pandas as pd

from mxm.moneymachine.marketdata.datasets.instrument_definitions.api import (
    get_start_from_watermark,
    make_instrument_definition_feed,
)
from mxm.moneymachine.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
    ResetFeedResult,
)
from mxm.moneymachine.marketdata.mapping.vendors.databento.product_roots import (
    DatabentoProductRoot,
    get_databento_product_root,
)
from mxm.moneymachine.marketdata.types import InstrumentDefinitionsClient
from mxm.moneymachine.marketdata.vendors.databento.cost import (
    enforce_cost_cap,
    estimate_cost_instrument_definition,
)
from mxm.moneymachine.marketdata.vendors.databento.dataset_range import (
    DatasetRange,
    clamp_end,
    clamp_start,
    get_dataset_range,
)
from mxm.moneymachine.marketdata.vendors.databento.pull import (
    pull_instrument_definitions,
)
from mxm.moneymachine.utils.time_utils import (
    fmt_run_ts,
    parse_duration,
    parse_ts,
    to_utc_ts,
    utc_now_run_ts,
)

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


def _empty_window_runs() -> list[WindowRun]:
    return []


def _empty_counts() -> dict[str, object]:
    return {}


@dataclass()
class InstrumentDefinitionsIngestReport:
    """
    Report returned by `ingest_instrument_definitions`.

    This includes:
    - ingest-native control-plane details for the definition feed
    - a lightweight job-reporting surface used by higher-level compound jobs
    """

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
    windows: list[WindowRun] = field(default_factory=_empty_window_runs)

    cost_cap_usd: float = 0.0
    cost_usd_total: float = 0.0

    stopped_reason: str = (
        ""  # e.g. "reached_end" | "max_windows" | "cost_cap" | "no_progress"
    )

    cost_used_usd: float = 0.0
    stage_status: str = ""
    stop_reason: str = ""
    counts: dict[str, object] = field(default_factory=_empty_counts)


@dataclass(frozen=True)
class InstrumentDefinitionsRunContext:
    root: DatabentoProductRoot
    avail: DatasetRange
    feed: str
    default_start: str
    requested_end: str
    requested_end_raw: str
    end_target_ts: pd.Timestamp


@dataclass(frozen=True)
class InstrumentDefinitionsWindowResult:
    start: str
    end: str
    estimated_cost_usd: float
    watermark_before: str | None
    watermark_after: str | None
    events_seen: int
    events_inserted: int


def _is_vendor_final(
    *, watermark: str | None, dataset_end: str | None, tolerance: str = "1D"
) -> bool:
    """
    Heuristic: treat the feed as vendor-final if the watermark is within `tolerance`
    of the dataset's end boundary.

    Parameters
    ----------
    watermark:
        The last-seen vendor timestamp for this feed (control-plane), as canonical
        ISO8601Z with microseconds (e.g. '2026-01-27T00:00:00.000000Z').
    dataset_end:
        The dataset availability end timestamp (exclusive end boundary) returned by
        vendor metadata, as canonical ISO8601Z with microseconds.
    tolerance:
        A small duration string subtracted from dataset_end to define "close enough"
        (e.g. '1d', '12h', '30m'). This is a pragmatic guard against tiny vendor-side
        boundary effects and aligns with the idea that daily ingest may consider the
        most recent boundary "final" once sufficiently close.

    Returns
    -------
    bool
        True if watermark >= dataset_end - tolerance, else False.

    Notes
    -----
    - This is a *control-plane* check only. It does not assert anything about the
      completeness of stored data, merely that the vendor watermark is effectively at
      the dataset end boundary for this schema.
    - If watermark or dataset_end is missing, returns False (not vendor-final).
    """
    if watermark is None or dataset_end is None:
        return False

    wm = to_utc_ts(parse_ts(watermark))
    end = to_utc_ts(parse_ts(dataset_end))

    # Accept common tolerance notations like "1D" by normalising to lowercase.
    td = parse_duration(tolerance.strip().lower())

    return wm >= (end - td)


def ingest_instrument_definitions(
    *,
    store: InstrumentDefinitionsStore,
    product_id: str,
    client: InstrumentDefinitionsClient,
    mode: Mode,
    cost_cap_usd: float,
    window_days: int = 31,
    overlap: str = "1d",
    max_windows: int = 3,
    reset: bool = False,
    end: str | None = None,
) -> InstrumentDefinitionsIngestReport:
    """
    Orchestrate ingestion of instrument definition events for a single product-root feed.
    """
    _validate_instrument_definitions_request(
        cost_cap_usd=cost_cap_usd,
        window_days=window_days,
        max_windows=max_windows,
    )

    context, reset_result, watermark_before = _prepare_instrument_definitions_run(
        store=store,
        product_id=product_id,
        client=client,
        mode=mode,
        cost_cap_usd=cost_cap_usd,
        reset=reset,
        end=end,
    )

    report = _init_instrument_definitions_report(
        product_id=product_id,
        mode=mode,
        cost_cap_usd=cost_cap_usd,
        reset=reset,
        reset_result=reset_result,
        watermark_before=watermark_before,
        context=context,
    )

    _run_instrument_definitions_windows(
        store=store,
        product_id=product_id,
        client=client,
        mode=mode,
        window_days=window_days,
        overlap=overlap,
        max_windows=max_windows,
        cost_cap_usd=cost_cap_usd,
        context=context,
        report=report,
    )

    _finalize_instrument_definitions_report(report, max_windows=max_windows)
    return report


def _validate_instrument_definitions_request(
    *,
    cost_cap_usd: float,
    window_days: int,
    max_windows: int,
) -> None:
    if cost_cap_usd <= 0:
        raise ValueError("cost_cap_usd must be > 0")
    if window_days <= 0:
        raise ValueError("window_days must be > 0")
    if max_windows <= 0:
        raise ValueError("max_windows must be > 0")


def _prepare_instrument_definitions_run(
    *,
    store: InstrumentDefinitionsStore,
    product_id: str,
    client: InstrumentDefinitionsClient,
    mode: Mode,
    cost_cap_usd: float,
    reset: bool,
    end: str | None,
) -> tuple[InstrumentDefinitionsRunContext, ResetFeedResult | None, str | None]:
    root = get_databento_product_root(product_id)
    feed = make_instrument_definition_feed(
        source="databento",
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        schema="definition",
    ).key()

    _print_defs_start(
        product_id=product_id,
        feed=feed,
        mode=mode,
        reset=reset,
        cost_cap_usd=cost_cap_usd,
    )

    reset_result = _maybe_reset_instrument_definitions_feed(
        store=store,
        feed=feed,
        reset=reset,
    )
    watermark_before = store.get_watermark(feed=feed)

    avail = get_dataset_range(
        client=client,
        dataset=root.dataset,
        schema="definition",
    )
    requested_end_raw = end or utc_now_run_ts()
    requested_end = clamp_end(end=requested_end_raw, available=avail)

    context = InstrumentDefinitionsRunContext(
        root=root,
        avail=avail,
        feed=feed,
        default_start=avail.start,
        requested_end=requested_end,
        requested_end_raw=requested_end_raw,
        end_target_ts=parse_ts(requested_end),
    )

    return context, reset_result, watermark_before


def _maybe_reset_instrument_definitions_feed(
    *,
    store: InstrumentDefinitionsStore,
    feed: str,
    reset: bool,
) -> ResetFeedResult | None:
    if not reset:
        return None

    reset_result = store.reset_feed(feed=feed)
    print(
        f"[defs][reset] events_deleted={reset_result.events_deleted} "
        f"current_deleted={reset_result.current_deleted} "
        f"watermark_deleted={reset_result.watermark_deleted}"
    )
    return reset_result


def _init_instrument_definitions_report(
    *,
    product_id: str,
    mode: Mode,
    cost_cap_usd: float,
    reset: bool,
    reset_result: ResetFeedResult | None,
    watermark_before: str | None,
    context: InstrumentDefinitionsRunContext,
) -> InstrumentDefinitionsIngestReport:
    root = context.root

    return InstrumentDefinitionsIngestReport(
        product_id=product_id,
        feed=context.feed,
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        mode=mode,
        ts_utc=utc_now_run_ts(),
        reset_requested=reset,
        reset_result=reset_result,
        watermark_before=watermark_before,
        watermark_after=watermark_before,
        requested_end=context.requested_end,
        requested_end_raw=context.requested_end_raw,
        dataset_range_start=context.default_start,
        dataset_range_end=context.requested_end,
        windows_attempted=0,
        cost_cap_usd=float(cost_cap_usd),
        cost_usd_total=0.0,
        stopped_reason="",
    )


def _run_instrument_definitions_windows(
    *,
    store: InstrumentDefinitionsStore,
    product_id: str,
    client: InstrumentDefinitionsClient,
    mode: Mode,
    window_days: int,
    overlap: str,
    max_windows: int,
    cost_cap_usd: float,
    context: InstrumentDefinitionsRunContext,
    report: InstrumentDefinitionsIngestReport,
) -> None:
    _ = mode

    start = _initial_instrument_definitions_start(
        watermark=report.watermark_before,
        default_start=context.default_start,
        overlap=overlap,
        context=context,
    )
    last_watermark = report.watermark_before
    remaining_cap = float(cost_cap_usd)

    _print_defs_initial_window_state(
        watermark_before=report.watermark_before,
        default_start=context.default_start,
        start=start,
        requested_end=context.requested_end,
    )

    for _ in range(max_windows):
        if parse_ts(start) >= context.end_target_ts:
            report.stopped_reason = "reached_end"
            break

        window = _ingest_instrument_definitions_window(
            store=store,
            product_id=product_id,
            client=client,
            start=start,
            window_days=window_days,
            remaining_cap=remaining_cap,
            context=context,
            report=report,
        )

        _append_instrument_definitions_window(report=report, window=window)
        remaining_cap -= window.estimated_cost_usd

        if _stop_after_instrument_definitions_window(
            report=report,
            window=window,
            last_watermark=last_watermark,
            remaining_cap=remaining_cap,
            cost_cap_usd=cost_cap_usd,
        ):
            break

        last_watermark = window.watermark_after
        start = _next_instrument_definitions_start(
            watermark=window.watermark_after,
            default_start=context.default_start,
            overlap=overlap,
            context=context,
        )


def _initial_instrument_definitions_start(
    *,
    watermark: str | None,
    default_start: str,
    overlap: str,
    context: InstrumentDefinitionsRunContext,
) -> str:
    start = get_start_from_watermark(
        watermark=watermark,
        default_start=default_start,
        overlap=overlap,
    )
    return clamp_start(start=start, available=context.avail)


def _next_instrument_definitions_start(
    *,
    watermark: str | None,
    default_start: str,
    overlap: str,
    context: InstrumentDefinitionsRunContext,
) -> str:
    start = get_start_from_watermark(
        watermark=watermark,
        default_start=default_start,
        overlap=overlap,
    )
    return clamp_start(start=start, available=context.avail)


def _ingest_instrument_definitions_window(
    *,
    store: InstrumentDefinitionsStore,
    product_id: str,
    client: InstrumentDefinitionsClient,
    start: str,
    window_days: int,
    remaining_cap: float,
    context: InstrumentDefinitionsRunContext,
    report: InstrumentDefinitionsIngestReport,
) -> InstrumentDefinitionsWindowResult:
    root = context.root
    end_i = _instrument_definitions_window_end(
        start=start,
        window_days=window_days,
        end_target_ts=context.end_target_ts,
    )

    print(f"[defs][window {report.windows_attempted + 1}] start={start} end={end_i}")

    db_client = cast(db.Historical, client)
    est = estimate_cost_instrument_definition(
        client=db_client,
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
        estimated_cost_usd=est.estimated_cost_usd,
        cap_usd=remaining_cap,
    )

    df = pull_instrument_definitions(
        product_id=product_id,
        start=start,
        end=end_i,
        source="databento",
        extra=None,
    )

    wm_before_i = store.get_watermark(feed=context.feed)
    res = store.ingest_batch(feed=context.feed, df=df)
    wm_after_i = store.get_watermark(feed=context.feed)

    print(
        f"[defs][ingest] "
        f"events_seen={res.events_seen} "
        f"events_inserted={res.events_inserted} "
        f"watermark_before={wm_before_i} "
        f"watermark_after={wm_after_i}"
    )

    return InstrumentDefinitionsWindowResult(
        start=start,
        end=end_i,
        estimated_cost_usd=float(est.estimated_cost_usd),
        events_seen=int(res.events_seen),
        events_inserted=int(res.events_inserted),
        watermark_before=wm_before_i,
        watermark_after=wm_after_i,
    )


def _instrument_definitions_window_end(
    *,
    start: str,
    window_days: int,
    end_target_ts: pd.Timestamp,
) -> str:
    end_ts = parse_ts(start) + pd.Timedelta(days=window_days)
    if end_ts > end_target_ts:
        end_ts = end_target_ts
    return fmt_run_ts(end_ts)


def _append_instrument_definitions_window(
    *,
    report: InstrumentDefinitionsIngestReport,
    window: InstrumentDefinitionsWindowResult,
) -> None:
    report.windows_attempted += 1
    report.cost_usd_total += window.estimated_cost_usd
    report.watermark_after = window.watermark_after

    report.windows.append(
        WindowRun(
            start=window.start,
            end=window.end,
            estimated_cost_usd=window.estimated_cost_usd,
            events_seen=window.events_seen,
            events_inserted=window.events_inserted,
            watermark_before=window.watermark_before,
            watermark_after=window.watermark_after,
        )
    )


def _stop_after_instrument_definitions_window(
    *,
    report: InstrumentDefinitionsIngestReport,
    window: InstrumentDefinitionsWindowResult,
    last_watermark: str | None,
    remaining_cap: float,
    cost_cap_usd: float,
) -> bool:
    if window.watermark_after == last_watermark:
        return _stop_for_instrument_definitions_no_progress(
            report=report,
            watermark_after=window.watermark_after,
        )

    if remaining_cap <= 0:
        report.stopped_reason = "cost_cap"
        print(
            f"[defs][stop] cost_cap_exhausted "
            f"spent={report.cost_usd_total:.6f} "
            f"cap={cost_cap_usd:.6f}"
        )
        return True

    return False


def _stop_for_instrument_definitions_no_progress(
    *,
    report: InstrumentDefinitionsIngestReport,
    watermark_after: str | None,
) -> bool:
    if _is_vendor_final(
        watermark=watermark_after,
        dataset_end=report.dataset_range_end,
        tolerance="1D",
    ):
        report.stopped_reason = "vendor_final"
        report.watermark_after = watermark_after
        print(
            f"[defs][stop] vendor_final (watermark at dataset end: {watermark_after})"
        )
        return True

    report.stopped_reason = "no_progress"
    report.watermark_after = watermark_after
    print(f"[defs][stop] no_progress (watermark did not advance: {watermark_after})")
    return True


def _finalize_instrument_definitions_report(
    report: InstrumentDefinitionsIngestReport,
    *,
    max_windows: int,
) -> None:
    if report.stopped_reason == "":
        report.stopped_reason = "max_windows"

    _print_instrument_definitions_stop(report, max_windows=max_windows)
    _populate_instrument_definitions_job_surface(report)


def _print_instrument_definitions_stop(
    report: InstrumentDefinitionsIngestReport,
    *,
    max_windows: int,
) -> None:
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


def _populate_instrument_definitions_job_surface(
    report: InstrumentDefinitionsIngestReport,
) -> None:
    report.cost_used_usd = float(report.cost_usd_total)
    report.stop_reason = report.stopped_reason

    events_seen_total = int(sum(w.events_seen for w in report.windows))
    events_inserted_total = int(sum(w.events_inserted for w in report.windows))

    if report.stopped_reason in ("no_progress",):
        report.stage_status = "halted" if events_inserted_total == 0 else "ok"
    else:
        report.stage_status = "ok"

    report.counts = {
        "windows_attempted": int(report.windows_attempted),
        "events_seen_total": events_seen_total,
        "events_inserted_total": events_inserted_total,
        "watermark_before": report.watermark_before,
        "watermark_after": report.watermark_after,
        "dataset": report.dataset,
        "symbol": report.symbol,
        "stype_in": report.stype_in,
        "stopped_reason": report.stopped_reason,
    }


def _print_defs_start(
    *,
    product_id: str,
    feed: str,
    mode: Mode,
    reset: bool,
    cost_cap_usd: float,
) -> None:
    print(
        f"[defs] product_id={product_id} "
        f"feed={feed} "
        f"mode={mode} "
        f"reset={reset} "
        f"cost_cap_usd={cost_cap_usd:.2f}"
    )


def _print_defs_initial_window_state(
    *,
    watermark_before: str | None,
    default_start: str,
    start: str,
    requested_end: str,
) -> None:
    print(
        f"[defs][start] watermark_before={watermark_before} "
        f"default_start={default_start} "
        f"computed_start={start} "
        f"requested_end={requested_end}"
    )
