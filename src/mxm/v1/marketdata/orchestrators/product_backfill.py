from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Optional, Sequence, Tuple

from mxm_refdata.api.ref_data_api import RefDataAPI  # type: ignore
from mxm_refdata.models.contracts.futures_contract import FuturesContract

from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    RefdataPeriodLookupError,
    period_by_id,
)

# ---------------------------------------------------------------------------
# PATCHABLE IMPORTS (atoms)
# ---------------------------------------------------------------------------
# You must patch these to match your existing Session 7–10 implementations.
#
# Required atoms:
# 1) Enumerate contracts for a product_id
# 2) Ensure instrument-definition coverage (bounded policy)
# 3) Build/update mappings for product
# 4) Resolve FuturesContract -> Databento identity (instrument_id)
# 5) Ingest OHLCV-1D by instrument_id (streaming)
# 6) Locate/read/merge-write parquet, and/or scan coverage for completeness
#
# The orchestrator should not implement these; it only coordinates them.


# You will likely have these from Sessions 8–10; patch accordingly:
def ensure_instrument_definitions_coverage(
    *, product_id: str, start: date, end: date
) -> "DefinitionCoverageResult":
    raise NotImplementedError(
        "Patch: ensure_instrument_definitions_coverage atom not wired yet."
    )


def rebuild_instrument_definition_mappings(
    *, product_id: str
) -> "MappingRebuildResult":
    raise NotImplementedError(
        "Patch: rebuild_instrument_definition_mappings atom not wired yet."
    )


def resolve_databento_instrument(
    *, futures_contract: "FuturesContract"
) -> "DatabentoInstrumentIdentity":
    raise NotImplementedError("Patch: resolve_databento_instrument atom not wired yet.")


def scan_ohlcv_1d_coverage(
    *, identity: "DatabentoInstrumentIdentity"
) -> "CoverageWindow":
    raise NotImplementedError("Patch: scan_ohlcv_1d_coverage atom not wired yet.")


def ingest_ohlcv_1d_stream(
    *,
    identity: "DatabentoInstrumentIdentity",
    start: date,
    end: date,
    cost_cap_usd_remaining: float,
    dry_run: bool,
) -> "IngestResult":
    raise NotImplementedError("Patch: ingest_ohlcv_1d_stream atom not wired yet.")


# ---------------------------------------------------------------------------
# Domain placeholders (types)
# ---------------------------------------------------------------------------
# These are “typing only” placeholders so the orchestrator skeleton is usable now.
# Replace these with your real types once you patch imports.
@dataclass(frozen=True)
class FuturesContract:
    product_id: str
    contract_year: int
    contract_month: int
    first_day_of_interest: date
    last_trading_day: date

    @property
    def contract_key(self) -> str:
        return f"{self.product_id}:{self.contract_year:04d}-{self.contract_month:02d}"


@dataclass(frozen=True)
class DatabentoInstrumentIdentity:
    dataset: str
    publisher_id: int
    instrument_id: int
    raw_symbol: str


@dataclass(frozen=True)
class CoverageWindow:
    """
    Coverage as observed in stored parquet.
    All fields optional to represent “no data”.
    """

    min_ts: Optional[date]
    max_ts: Optional[date]
    row_count: int


@dataclass(frozen=True)
class IngestResult:
    """
    Result of a single contract ingest attempt.
    """

    did_request: bool
    cost_usd: float
    rows_written: int


@dataclass(frozen=True)
class DefinitionCoverageResult:
    """
    Outcome of ensuring definition coverage.
    """

    required_start: date
    required_end: date
    had_coverage: bool
    extended: bool


@dataclass(frozen=True)
class MappingRebuildResult:
    """
    Outcome of mapping rebuild/audit.
    """

    total_contracts: int
    mapped_contracts: int
    unmapped_contracts: int
    unmapped_keys: Sequence[str] = ()


# ---------------------------------------------------------------------------
# Report model (what Proof 99 prints)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class ContractCoverageRow:
    contract_key: str
    target_start: date
    target_end: date
    stored_min: Optional[date]
    stored_max: Optional[date]
    row_count: int
    status: (
        str  # "complete" | "incomplete" | "unmapped" | "skipped_cost_cap" | "dry_run"
    )
    cost_usd: float = 0.0


@dataclass
class ProductBackfillReport:
    product_id: str
    mode: str  # "backfill"
    ts_utc: str

    cost_cap_usd: float
    cost_usd_total: float = 0.0

    definitions: Optional[DefinitionCoverageResult] = None
    mappings: Optional[MappingRebuildResult] = None

    total_contracts: int = 0
    mapped_contracts: int = 0
    complete_before: int = 0
    completed_this_run: int = 0
    incomplete_remaining: int = 0

    rows: list[ContractCoverageRow] = field(default_factory=list)

    def to_summary_str(self) -> str:
        return (
            f"ProductBackfillReport(product_id={self.product_id}, mode={self.mode}, "
            f"cost_usd_total={self.cost_usd_total:.6f}/{self.cost_cap_usd:.6f}, "
            f"contracts(total={self.total_contracts}, mapped={self.mapped_contracts}, "
            f"complete_before={self.complete_before}, completed_this_run={self.completed_this_run}, "
            f"incomplete_remaining={self.incomplete_remaining}))"
        )


# ---------------------------------------------------------------------------
# Orchestrator API (public)
# ---------------------------------------------------------------------------
def backfill_product_ohlcv_1d(
    *,
    product_id: str,
    cost_cap_usd: float,
    definition_lookback_years: int = 20,
    dry_run: bool = False,
) -> ProductBackfillReport:
    """
    Backfill OHLCV-1D for all mapped futures contracts of a product over each contract's lifecycle window.

    Fixed constraints for Session 11:
    - Streaming (timeseries) ingestion only
    - instrument_id addressing only
    - Backfill mode only: target window = [first_day_of_interest, last_trading_day]
    - Completeness definition (MVP): stored_min<=target_start and stored_max>=target_end and row_count>0
    - Safe to re-run; should skip completed contracts

    This function MUST remain “thin orchestration glue”:
    no Databento API calls, no parsing, no persistence logic beyond calling atoms.
    """
    if cost_cap_usd <= 0:
        raise ValueError("cost_cap_usd must be > 0")

    report = ProductBackfillReport(
        product_id=product_id,
        mode="backfill",
        ts_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        cost_cap_usd=float(cost_cap_usd),
    )

    # ---------------------------------------------------------------------
    # Phase 0 — enumerate contracts (deterministic ordering)
    # ---------------------------------------------------------------------
    contracts = list(_enumerate_contracts_for_product(product_id))
    contracts.sort(key=lambda c: (c.contract_year, c.contract_month))
    report.total_contracts = len(contracts)

    if not contracts:
        # Nothing to do; still a valid report.
        return report

    # ---------------------------------------------------------------------
    # Phase 1 — ensure instrument definition coverage (bounded & deterministic)
    # ---------------------------------------------------------------------
    earliest = min(c.first_day_of_interest for c in contracts)
    latest = max(c.last_trading_day for c in contracts)

    required_start = _bounded_lookback_start(
        earliest, definition_lookback_years=definition_lookback_years
    )
    required_end = latest

    report.definitions = ensure_instrument_definitions_coverage(
        product_id=product_id,
        start=required_start,
        end=required_end,
    )

    # ---------------------------------------------------------------------
    # Phase 2 — rebuild mappings and audit
    # ---------------------------------------------------------------------
    report.mappings = rebuild_instrument_definition_mappings(product_id=product_id)
    report.mapped_contracts = report.mappings.mapped_contracts if report.mappings else 0

    # ---------------------------------------------------------------------
    # Phase 3 — contract loop
    # ---------------------------------------------------------------------
    remaining_cap = float(cost_cap_usd)

    for c in contracts:
        target_start = c.first_day_of_interest
        target_end = c.last_trading_day

        # 3.1 Resolve identity (instrument_id only)
        try:
            identity = resolve_databento_instrument(futures_contract=c)
        except Exception:
            # Treat as unmapped/unresolvable at orchestration level.
            report.rows.append(
                ContractCoverageRow(
                    contract_key=c.contract_key,
                    target_start=target_start,
                    target_end=target_end,
                    stored_min=None,
                    stored_max=None,
                    row_count=0,
                    status="unmapped",
                    cost_usd=0.0,
                )
            )
            continue

        # 3.2 Scan existing coverage from parquet (MVP acceptable)
        cov_before = scan_ohlcv_1d_coverage(identity=identity)

        is_complete_before = _is_complete_mvp(
            cov=cov_before,
            target_start=target_start,
            target_end=target_end,
        )
        if is_complete_before:
            report.complete_before += 1
            report.rows.append(
                ContractCoverageRow(
                    contract_key=c.contract_key,
                    target_start=target_start,
                    target_end=target_end,
                    stored_min=cov_before.min_ts,
                    stored_max=cov_before.max_ts,
                    row_count=cov_before.row_count,
                    status="complete",
                    cost_usd=0.0,
                )
            )
            continue

        # 3.3 If dry-run: do not ingest, just record incompleteness
        if dry_run:
            report.rows.append(
                ContractCoverageRow(
                    contract_key=c.contract_key,
                    target_start=target_start,
                    target_end=target_end,
                    stored_min=cov_before.min_ts,
                    stored_max=cov_before.max_ts,
                    row_count=cov_before.row_count,
                    status="dry_run",
                    cost_usd=0.0,
                )
            )
            continue

        # 3.4 Enforce cost cap
        if remaining_cap <= 0:
            report.rows.append(
                ContractCoverageRow(
                    contract_key=c.contract_key,
                    target_start=target_start,
                    target_end=target_end,
                    stored_min=cov_before.min_ts,
                    stored_max=cov_before.max_ts,
                    row_count=cov_before.row_count,
                    status="skipped_cost_cap",
                    cost_usd=0.0,
                )
            )
            continue

        # 3.5 Ingest
        ingest = ingest_ohlcv_1d_stream(
            identity=identity,
            start=target_start,
            end=target_end,
            cost_cap_usd_remaining=remaining_cap,
            dry_run=False,
        )
        report.cost_usd_total += float(ingest.cost_usd)
        remaining_cap -= float(ingest.cost_usd)

        # 3.6 Re-scan coverage after ingest (source of truth is storage)
        cov_after = scan_ohlcv_1d_coverage(identity=identity)
        is_complete_after = _is_complete_mvp(
            cov=cov_after, target_start=target_start, target_end=target_end
        )

        if is_complete_after and not is_complete_before:
            report.completed_this_run += 1

        report.rows.append(
            ContractCoverageRow(
                contract_key=c.contract_key,
                target_start=target_start,
                target_end=target_end,
                stored_min=cov_after.min_ts,
                stored_max=cov_after.max_ts,
                row_count=cov_after.row_count,
                status="complete" if is_complete_after else "incomplete",
                cost_usd=float(ingest.cost_usd),
            )
        )

    # ---------------------------------------------------------------------
    # Phase 4 — roll up incomplete count
    # ---------------------------------------------------------------------
    report.incomplete_remaining = sum(
        1
        for r in report.rows
        if r.status in ("incomplete", "dry_run", "skipped_cost_cap")
    )
    return report


# ---------------------------------------------------------------------------
# Internal helpers (pure logic only)
# ---------------------------------------------------------------------------


def _enumerate_contracts_for_product(product_id: str) -> list[FuturesContract]:
    """
    Enumerate MXM FuturesContracts for product_id (refdata truth set) and return them
    in deterministic chronological order by Period.

    Ordering policy (Session 11):
    - primary: Period ordering (Period.__lt__)
    - secondary: stable tie-breaker (contract_id/id/period_id)
    """
    api = RefDataAPI()
    contracts = list(api.get_contracts_for_product(product_id))

    periods = period_by_id()

    def _tie_breaker(c: FuturesContract) -> str:
        return str(c.contract_id)

    def _sort_key(c: FuturesContract) -> tuple[object, str]:
        p = periods.get(c.period_id)
        if p is None:
            raise RefdataPeriodLookupError(period_id=c.period_id)
        return (p, _tie_breaker(c))

    contracts.sort(key=_sort_key)
    return contracts


def _bounded_lookback_start(start: date, *, definition_lookback_years: int) -> date:
    """
    Deterministic bounded policy: do not request infinite history.
    """
    if definition_lookback_years <= 0:
        raise ValueError("definition_lookback_years must be > 0")
    return date(start.year - definition_lookback_years, 1, 1)


def _is_complete_mvp(
    *, cov: CoverageWindow, target_start: date, target_end: date
) -> bool:
    """
    Completion definition (Level 0, MVP):
      - stored_min <= target_start
      - stored_max >= target_end
      - row_count > 0
    """
    if cov.row_count <= 0:
        return False
    if cov.min_ts is None or cov.max_ts is None:
        return False
    return (cov.min_ts <= target_start) and (cov.max_ts >= target_end)
