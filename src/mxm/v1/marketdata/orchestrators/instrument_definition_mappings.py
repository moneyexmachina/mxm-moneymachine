from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

from mxm_refdata.api.ref_data_api import RefDataAPI  # type: ignore

from mxm.v1.marketdata.datasets.instrument_definition_mappings.store import (
    BuildResult,
    InstrumentDefinitionMappingsStore,
    ResetProductResult,
)
from mxm.v1.marketdata.datasets.instrument_definitions.api import (
    make_instrument_definition_feed,
)
from mxm.v1.marketdata.datasets.instrument_definitions.store import (
    InstrumentDefinitionsStore,
)
from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    RefdataPeriodLookupError,
    period_by_id,
)
from mxm.v1.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)
from mxm.v1.marketdata.time_utils import utc_now_run_ts

Mode = Literal["bootstrap", "update"]


# ---------------------------------------------------------------------------
# Report model
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GateCheck:
    """
    Captures one gate's decision and diagnostic details.
    """

    name: str
    ok: bool
    detail: str


@dataclass()
class InstrumentDefinitionMappingsOrchestratorReport:
    product_id: str
    mode: Mode
    ts_utc: str

    # Upstream scope identity (vendor-scoped)
    feed: str
    dataset: str
    symbol: str
    stype_in: str

    # Requested actions
    reset_requested: bool
    reset_result: ResetProductResult | None

    # Gates (the orchestrator refuses to mutate other datasets)
    gates: list[GateCheck] = field(default_factory=list)
    definitions_watermark: str | None = None
    # Contract universe stats
    refdata_contracts_total: int = 0
    refdata_maturities_total: int = 0
    vendor_maturities_total: int = 0
    overlap_attempted: int = 0

    # Build outcome
    build_result: BuildResult | None = None

    stopped_reason: str = ""  # "ok" | "gate_failed" | "no_overlap" | "no_contracts"
    # --- meta-orchestrator surface (Session 13) ---
    cost_used_usd: float = 0.0
    stage_status: str = ""
    stop_reason: str = ""
    mapping_ready_for_ohlcv: bool = False
    counts: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Public orchestration entrypoint
# ---------------------------------------------------------------------------


def rebuild_instrument_definition_mappings(
    *,
    defs_store: InstrumentDefinitionsStore,
    mappings_store: InstrumentDefinitionMappingsStore,
    product_id: str,
    mode: Mode,
    reset: bool = False,
) -> InstrumentDefinitionMappingsOrchestratorReport:
    """
    Orchestrate instrument_definition_mappings rebuild/update for a single product_id.

    Key invariants:
    - This orchestrator does NOT ingest instrument definitions.
      It only checks readiness gates and refuses to proceed if upstream is insufficient.
    - It does NOT call vendor APIs.
    - It uses refdata to enumerate the internal contract maturities we want to map.
    - It uses instrument_definition_current to source vendor candidate maturities.
    - It writes only to instrument_definition_mappings.

    Modes:
    - bootstrap: typically used after reset or first-time mapping creation
    - update: append-only upsert behaviour (still safe to run repeatedly)
      (Implementation is identical; mode is for operator intent and reporting.)
    """
    root = get_databento_product_root(product_id)

    feed = make_instrument_definition_feed(
        source="databento",
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        schema="definition",
    ).key()

    report = InstrumentDefinitionMappingsOrchestratorReport(
        product_id=product_id,
        mode=mode,
        ts_utc=utc_now_run_ts(),
        feed=feed,
        dataset=root.dataset,
        symbol=root.parent,
        stype_in=root.stype_in,
        reset_requested=bool(reset),
        reset_result=None,
        stopped_reason="",
    )

    print(f"[idmap] product_id={product_id} feed={feed} mode={mode} reset={reset}")

    # ---------------------------------------------------------------------
    # Phase 0 — optional reset (only affects mappings dataset)
    # ---------------------------------------------------------------------
    if reset:
        report.reset_result = mappings_store.reset_product(product_id=product_id)
        print(
            f"[idmap][reset] product_id={product_id} "
            f"rows_deleted={report.reset_result.rows_deleted}"
        )

    # ---------------------------------------------------------------------
    # Phase 1 — gates: upstream definitions readiness
    # ---------------------------------------------------------------------
    # Gate 1: watermark must exist for feed (definitions have been ingested at least once)
    wm = defs_store.get_watermark(feed=feed)
    report.definitions_watermark = wm
    if wm is None:
        report.gates.append(
            GateCheck(
                name="definitions_watermark_exists",
                ok=False,
                detail=f"no watermark for feed={feed}; run ops/instrument_definitions.py first",
            )
        )
        report.stopped_reason = "gate_failed"
        _print_gate_fail(report)
        return report

    report.gates.append(
        GateCheck(
            name="definitions_watermark_exists",
            ok=True,
            detail=f"watermark={wm}",
        )
    )

    # Gate 2: current view must contain outrights for this feed
    vendor_maturities = mappings_store.list_vendor_maturities_from_current(feed=feed)
    report.vendor_maturities_total = len(vendor_maturities)

    if not vendor_maturities:
        report.gates.append(
            GateCheck(
                name="definitions_current_has_outrights",
                ok=False,
                detail=(
                    "instrument_definition_current has no FUT/F outrights for this feed; "
                    "definitions window likely too narrow or ingest not run"
                ),
            )
        )
        report.stopped_reason = "gate_failed"
        _print_gate_fail(report)
        return report

    report.gates.append(
        GateCheck(
            name="definitions_current_has_outrights",
            ok=True,
            detail=f"vendor_outright_maturities={len(vendor_maturities)}",
        )
    )

    # ---------------------------------------------------------------------
    # Phase 2 — enumerate refdata contracts and maturities (deterministic)
    # ---------------------------------------------------------------------
    api = RefDataAPI()
    contracts = list(api.get_contracts_for_product(product_id))
    report.refdata_contracts_total = len(contracts)
    ref_pairs = _load_refdata_maturities(product_id=product_id)
    report.refdata_maturities_total = len(ref_pairs)

    if not ref_pairs:
        report.stopped_reason = "no_contracts"
        print(f"[idmap][stop] no refdata maturities for product_id={product_id}")
        return report

    # Overlap is the safe attempt set (do not try to map maturities vendor does not have in current)
    overlap = [ym for ym in ref_pairs if ym in vendor_maturities]
    report.overlap_attempted = len(overlap)

    if not overlap:
        report.stopped_reason = "no_overlap"
        print(
            "[idmap][stop] no overlap between refdata maturities and vendor current maturities; "
            "extend instrument definitions ingest window forward"
        )
        return report

    print(
        f"[idmap][scope] refdata_maturities={len(ref_pairs)} "
        f"vendor_maturities={len(vendor_maturities)} "
        f"overlap={len(overlap)}"
    )

    # ---------------------------------------------------------------------
    # Phase 3 — build mappings (append-only, deterministic, idempotent)
    # ---------------------------------------------------------------------
    build = mappings_store.build_from_current_definitions(
        product_id=product_id,
        feed=feed,
        dataset=root.dataset,
        contracts=overlap,
    )
    report.build_result = build

    print(
        f"[idmap][build] attempted={build.contracts_attempted} "
        f"inserted={build.inserted} ignored={build.ignored} "
        f"unmapped={len(build.unmapped)}"
    )

    report.stopped_reason = "ok"
    return _finalize_report(report)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _finalize_report(
    report: InstrumentDefinitionMappingsOrchestratorReport,
) -> InstrumentDefinitionMappingsOrchestratorReport:
    report.cost_used_usd = 0.0
    report.stop_reason = report.stopped_reason
    report.mapping_ready_for_ohlcv = report.stopped_reason == "ok"

    if report.stopped_reason == "ok":
        report.stage_status = "ok"
    else:
        report.stage_status = "halted"

    br = report.build_result
    report.counts = {
        "definitions_watermark": report.definitions_watermark,
        "refdata_contracts_total": int(report.refdata_contracts_total),
        "refdata_maturities_total": int(report.refdata_maturities_total),
        "vendor_maturities_total": int(report.vendor_maturities_total),
        "overlap_attempted": int(report.overlap_attempted),
        "build_attempted": int(br.contracts_attempted) if br else 0,
        "build_inserted": int(br.inserted) if br else 0,
        "build_ignored": int(br.ignored) if br else 0,
        "build_unmapped": int(len(br.unmapped)) if br else 0,
        "stopped_reason": report.stopped_reason,
        "mapping_ready_for_ohlcv": report.mapping_ready_for_ohlcv,
    }
    return report


def _print_gate_fail(report: InstrumentDefinitionMappingsOrchestratorReport) -> None:
    # Keep a stable operator-readable gate failure print.
    fails = [g for g in report.gates if not g.ok]
    if not fails:
        return
    print("[idmap][gate_fail]")
    for g in fails:
        print(f"  - {g.name}: {g.detail}")


def _load_refdata_maturities(*, product_id: str) -> list[tuple[int, int]]:
    """
    Enumerate contract maturities (year, month) for a product using refdata:
      FuturesContract.period_id -> Period.first_date.year/month

    Determinism:
    - stable sorted output (y,m)
    - if missing periods exist, raise (this is a refdata integrity issue)
      (you can relax to warn-only later)
    """
    api = RefDataAPI()
    contracts = list(api.get_contracts_for_product(product_id))
    # For reporting only:
    # (We do not store this in the report in detail to keep it compact.)
    # But we preserve determinism and correctness here.
    periods = period_by_id()

    pairs: set[tuple[int, int]] = set()
    missing: list[str] = []

    for c in contracts:
        p = periods.get(c.period_id)
        if p is None:
            missing.append(str(c.period_id))
            continue
        pairs.add((int(p.first_date.year), int(p.first_date.month)))

    if missing:
        # This should be rare; treat as integrity error for MVP.
        # If you prefer warn-only, change this to print + continue.
        missing_sorted = sorted(missing)
        raise RefdataPeriodLookupError(period_id=missing_sorted[0])

    return sorted(pairs)
