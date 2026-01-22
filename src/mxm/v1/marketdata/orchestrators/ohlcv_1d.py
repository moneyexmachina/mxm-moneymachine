from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Literal

import pandas as pd
from mxm_refdata.api.ref_data_api import RefDataAPI  # type: ignore
from mxm_refdata.models.contracts.futures_contract import (
    FuturesContract,  # type: ignore
)

from mxm.v1.marketdata.datasets.instrument_definitions.api import (
    make_instrument_definition_feed,
)
from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.api import (
    contract_window_utc_half_open,
    is_complete_level0,
)
from mxm.v1.marketdata.datasets.ohlcv_1d.store import OHLCV1DStore
from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    DatabentoInstrumentIdentity,
    contract_year_month,
    resolve_databento_instrument,
)
from mxm.v1.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.marketdata.vendors.databento.cost import (
    enforce_cost_cap,
    estimate_cost_ohlcv_1d,
)
from mxm.v1.marketdata.vendors.databento.dataset_range import get_dataset_range
from mxm.v1.marketdata.vendors.databento.normalize.ohlcv_1d import normalize_ohlcv_1d
from mxm.v1.marketdata.vendors.databento.pull import pull_ohlcv_1d_by_instrument_id

Mode = Literal["bootstrap", "update"]


@dataclass(frozen=True)
class GateResult:
    name: str
    ok: bool
    detail: str


@dataclass(frozen=True)
class ContractRun:
    contract_id: str
    contract_key: str
    target_start: str
    target_end: str
    stored_min: str | None
    stored_max: str | None
    stored_rows: int
    status: (
        str  # complete | ingested | unmapped | skipped_cost_cap | dry_run | incomplete
    )
    vendor_start: str | None = None
    vendor_end: str | None = None

    cost_usd: float = 0.0
    bars_path: str | None = None


@dataclass
class OHLCV1DOrchestratorReport:
    product_id: str
    mode: Mode
    ts_utc: str

    gates: list[GateResult] = field(default_factory=list)

    cost_cap_usd: float = 0.0
    cost_usd_total: float = 0.0

    contracts_total: int = 0
    contracts_mapped: int = 0
    complete_before: int = 0
    completed_this_run: int = 0
    incomplete_remaining: int = 0
    contracts_excluded_unavailable: int = 0
    contracts_considered: int = 0
    dataset_range_start: str | None = None
    dataset_range_end: str | None = None
    runs: list[ContractRun] = field(default_factory=list)

    stopped_reason: str = ""  # ok | cost_cap | max_contracts


def _utc_now_iso_z() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _dt_utc_from_iso_z(ts: str) -> datetime:
    # Databento may return nanoseconds; truncate to microseconds for datetime.
    # Example: 2026-01-22T01:35:01.776253000Z
    if not ts.endswith("Z"):
        raise ValueError(f"expected Z timestamp: {ts}")
    core = ts[:-1]
    if "." in core:
        left, frac = core.split(".", 1)
        frac6 = (frac + "000000")[:6]
        core = f"{left}.{frac6}"
    dt = datetime.fromisoformat(core)
    return dt.replace(tzinfo=timezone.utc)


def _contract_key(c: FuturesContract) -> str:
    y, m = contract_year_month(c)
    return f"{c.product_id}:{y:04d}-{m:02d}"


def _gate_definitions_available(
    *,
    backend: SQLiteBackend,
    product_id: str,
) -> GateResult:
    """
    Minimal gate: definitions watermark exists for the product's feed.
    This does NOT ensure “up-to-date”; it ensures the dataset is present at all.
    """
    root = get_databento_product_root(product_id)
    feed = make_instrument_definition_feed(
        source="databento",
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        schema="definition",
    ).key()

    store = InstrumentDefinitionsStore(backend=backend)
    wm = store.get_watermark(feed=feed)
    if wm is None:
        return GateResult(
            name="instrument_definitions_watermark_exists",
            ok=False,
            detail=f"missing watermark for feed={feed}",
        )
    return GateResult(
        name="instrument_definitions_watermark_exists",
        ok=True,
        detail=f"watermark={wm}",
    )


def _enumerate_contracts(product_id: str, *, mode: Mode) -> list[FuturesContract]:
    """
    Deterministic enumeration of refdata contracts.

    For now:
      - bootstrap: all contracts for product
      - update: contracts whose last_trading_day is within a recent horizon
               (simple, conservative; avoids reprocessing deep history)
    """
    api = RefDataAPI()
    contracts = list(api.get_contracts_for_product(product_id))

    # Deterministic ordering
    contracts.sort(key=lambda c: (*contract_year_month(c), str(c.contract_id)))

    if mode == "bootstrap":
        return contracts

    # mode == "update"
    today = date.today()
    # Conservative: only touch contracts that could plausibly still be “live/recent”.
    # You can refine later using an explicit refdata "active" query.
    cutoff = today.replace(year=today.year - 1)
    return [c for c in contracts if c.last_trading_day >= cutoff]


def ingest_ohlcv_1d_for_product(
    *,
    backend: SQLiteBackend,
    store: OHLCV1DStore,
    product_id: str,
    mode: Mode,
    cost_cap_usd: float,
    client,  # databento.Historical; untyped to avoid hard dependency
    max_contracts: int | None = None,
    dry_run: bool = False,
    reset_local: bool = False,
) -> OHLCV1DOrchestratorReport:
    """
    Orchestrate ohlcv-1d persistence for a product_id.

    Hard boundaries:
    - No instrument_definitions ingest.
    - No instrument_definition_mappings rebuild.
    - Uses mapping table only to resolve contract -> instrument identity.

    Completeness:
    - Level 0, half-open windows as defined in datasets/ohlcv_1d/api.py.
    """
    if cost_cap_usd <= 0:
        raise ValueError("cost_cap_usd must be > 0")

    report = OHLCV1DOrchestratorReport(
        product_id=product_id,
        mode=mode,
        ts_utc=_utc_now_iso_z(),
        cost_cap_usd=float(cost_cap_usd),
        cost_usd_total=0.0,
        stopped_reason="",
    )

    # -------------------------
    # Gates (read-only)
    # -------------------------
    g_defs = _gate_definitions_available(backend=backend, product_id=product_id)
    report.gates.append(g_defs)
    if not g_defs.ok:
        raise RuntimeError(
            "ohlcv_1d orchestrator gate failed: instrument_definitions not present. "
            "Run ops/instrument_definitions.py first."
        )

    root = get_databento_product_root(product_id)

    avail = get_dataset_range(
        client=client,
        dataset=root.dataset,
        schema="ohlcv-1d",
    )
    report.dataset_range_start = avail.start
    report.dataset_range_end = avail.end

    report.gates.append(
        GateResult(
            name="databento_dataset_range_ohlcv_1d",
            ok=True,
            detail=f"start={avail.start} end={avail.end} (end exclusive)",
        )
    )

    # Convert dataset range to pandas timestamps (UTC) once; do all math in pd.Timestamp.
    avail_start_ts = pd.Timestamp(avail.start)
    avail_end_ts = pd.Timestamp(avail.end)
    if avail_start_ts.tzinfo is None:
        avail_start_ts = avail_start_ts.tz_localize("UTC")
    else:
        avail_start_ts = avail_start_ts.tz_convert("UTC")
    if avail_end_ts.tzinfo is None:
        avail_end_ts = avail_end_ts.tz_localize("UTC")
    else:
        avail_end_ts = avail_end_ts.tz_convert("UTC")

    # -------------------------
    # Contract enumeration + eligibility filter
    # -------------------------
    contracts_all = _enumerate_contracts(product_id, mode=mode)

    eligible: list[FuturesContract] = []
    excluded = 0
    for c in contracts_all:
        w = contract_window_utc_half_open(
            start_date=c.first_day_of_interest,
            end_date_inclusive=c.last_trading_day,
        )
        # w.start / w.end are expected to be tz-aware UTC, but normalise defensively.
        w_start = (
            w.start.tz_convert("UTC") if w.start.tzinfo else w.start.tz_localize("UTC")
        )
        w_end = w.end.tz_convert("UTC") if w.end.tzinfo else w.end.tz_localize("UTC")

        # Overlap test between [w_start, w_end) and [avail_start_ts, avail_end_ts)
        if w_end <= avail_start_ts or w_start >= avail_end_ts:
            excluded += 1
            continue
        eligible.append(c)

    report.contracts_excluded_unavailable = excluded
    report.contracts_considered = len(eligible)

    contracts = eligible
    report.contracts_total = len(contracts)

    if max_contracts is not None:
        if max_contracts <= 0:
            raise ValueError("max_contracts must be > 0")
        contracts = contracts[: int(max_contracts)]
        report.stopped_reason = "max_contracts"

    remaining = float(cost_cap_usd)

    # -------------------------
    # Main loop
    # -------------------------
    for c in contracts:
        window = contract_window_utc_half_open(
            start_date=c.first_day_of_interest,
            end_date_inclusive=c.last_trading_day,
        )
        w_start = (
            window.start.tz_convert("UTC")
            if window.start.tzinfo
            else window.start.tz_localize("UTC")
        )
        w_end = (
            window.end.tz_convert("UTC")
            if window.end.tzinfo
            else window.end.tz_localize("UTC")
        )

        # Clamp contract window to dataset range
        effective_start = max(w_start, avail_start_ts)
        effective_end = min(w_end, avail_end_ts)  # avail_end is exclusive

        # If nothing remains after clamping, skip cleanly (half-open: require start < end)
        if effective_end <= effective_start:
            report.runs.append(
                ContractRun(
                    contract_id=str(c.contract_id),
                    contract_key=_contract_key(c),
                    target_start=str(w_start),
                    target_end=str(w_end),
                    vendor_start=None,
                    vendor_end=None,
                    stored_min=None,
                    stored_max=None,
                    stored_rows=0,
                    status="skipped_unavailable_range",
                )
            )
            continue

        start_s = effective_start.strftime("%Y-%m-%dT%H:%M:%SZ")
        end_s = effective_end.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Resolve mapping (no vendor calls)
        try:
            ident: DatabentoInstrumentIdentity = resolve_databento_instrument(
                backend, c
            )
            report.contracts_mapped += 1
        except Exception:
            report.runs.append(
                ContractRun(
                    contract_id=str(c.contract_id),
                    contract_key=_contract_key(c),
                    target_start=str(w_start),
                    target_end=str(w_end),
                    vendor_start=start_s,
                    vendor_end=end_s,
                    stored_min=None,
                    stored_max=None,
                    stored_rows=0,
                    status="unmapped",
                )
            )
            continue

        # Optional: local reset for this identity (parquet only)
        if reset_local:
            store.delete(
                dataset=ident.dataset,
                publisher_id=ident.publisher_id,
                instrument_id=ident.instrument_id,
            )

        cov_before = store.scan_coverage(
            dataset=ident.dataset,
            publisher_id=ident.publisher_id,
            instrument_id=ident.instrument_id,
        )
        complete_before = is_complete_level0(
            stored_min=cov_before.min_ts,
            stored_max=cov_before.max_ts,
            row_count=cov_before.row_count,
            target_start=effective_start,
            target_end=effective_end,
        )

        if complete_before:
            report.complete_before += 1
            report.runs.append(
                ContractRun(
                    contract_id=str(c.contract_id),
                    contract_key=_contract_key(c),
                    target_start=str(w_start),
                    target_end=str(w_end),
                    vendor_start=start_s,
                    vendor_end=end_s,
                    stored_min=(
                        str(cov_before.min_ts)
                        if cov_before.min_ts is not None
                        else None
                    ),
                    stored_max=(
                        str(cov_before.max_ts)
                        if cov_before.max_ts is not None
                        else None
                    ),
                    stored_rows=int(cov_before.row_count),
                    status="complete",
                    bars_path=str(cov_before.bars_path),
                )
            )
            continue

        if dry_run:
            report.runs.append(
                ContractRun(
                    contract_id=str(c.contract_id),
                    contract_key=_contract_key(c),
                    target_start=str(w_start),
                    target_end=str(w_end),
                    vendor_start=start_s,
                    vendor_end=end_s,
                    stored_min=(
                        str(cov_before.min_ts)
                        if cov_before.min_ts is not None
                        else None
                    ),
                    stored_max=(
                        str(cov_before.max_ts)
                        if cov_before.max_ts is not None
                        else None
                    ),
                    stored_rows=int(cov_before.row_count),
                    status="dry_run",
                    bars_path=str(cov_before.bars_path),
                )
            )
            continue

        if remaining <= 0:
            report.runs.append(
                ContractRun(
                    contract_id=str(c.contract_id),
                    contract_key=_contract_key(c),
                    target_start=str(w_start),
                    target_end=str(w_end),
                    vendor_start=start_s,
                    vendor_end=end_s,
                    stored_min=(
                        str(cov_before.min_ts)
                        if cov_before.min_ts is not None
                        else None
                    ),
                    stored_max=(
                        str(cov_before.max_ts)
                        if cov_before.max_ts is not None
                        else None
                    ),
                    stored_rows=int(cov_before.row_count),
                    status="skipped_cost_cap",
                    bars_path=str(cov_before.bars_path),
                )
            )
            report.stopped_reason = "cost_cap"
            break

        # -------------------------
        # Vendor call + normalise + persist
        # -------------------------
        est = estimate_cost_ohlcv_1d(
            client=client,
            dataset=ident.dataset,
            symbols=str(ident.instrument_id),
            stype_in="instrument_id",
            start=start_s,
            end=end_s,
        )
        enforce_cost_cap(estimated_cost_usd=est.estimated_cost_usd, cap_usd=remaining)

        df_raw = pull_ohlcv_1d_by_instrument_id(
            dataset=ident.dataset,
            instrument_id=ident.instrument_id,
            start=start_s,
            end=end_s,
            source="databento",
        )
        df = normalize_ohlcv_1d(
            df_raw, dataset=ident.dataset, raw_symbol=ident.raw_symbol
        )

        store.write(
            dataset=ident.dataset,
            publisher_id=ident.publisher_id,
            instrument_id=ident.instrument_id,
            df_new=df,
        )

        report.cost_usd_total += float(est.estimated_cost_usd)
        remaining -= float(est.estimated_cost_usd)

        cov_after = store.scan_coverage(
            dataset=ident.dataset,
            publisher_id=ident.publisher_id,
            instrument_id=ident.instrument_id,
        )
        complete_after = is_complete_level0(
            stored_min=cov_after.min_ts,
            stored_max=cov_after.max_ts,
            row_count=cov_after.row_count,
            target_start=effective_start,
            target_end=effective_end,
        )

        status = "ingested" if complete_after else "incomplete"
        if complete_after:
            report.completed_this_run += 1

        report.runs.append(
            ContractRun(
                contract_id=str(c.contract_id),
                contract_key=_contract_key(c),
                target_start=str(w_start),
                target_end=str(w_end),
                vendor_start=start_s,
                vendor_end=end_s,
                stored_min=(
                    str(cov_after.min_ts) if cov_after.min_ts is not None else None
                ),
                stored_max=(
                    str(cov_after.max_ts) if cov_after.max_ts is not None else None
                ),
                stored_rows=int(cov_after.row_count),
                status=status,
                cost_usd=float(est.estimated_cost_usd),
                bars_path=str(cov_after.bars_path),
            )
        )

    report.incomplete_remaining = sum(
        1
        for r in report.runs
        if r.status in ("incomplete", "dry_run", "skipped_cost_cap")
    )

    if report.stopped_reason == "":
        report.stopped_reason = "ok"

    return report
