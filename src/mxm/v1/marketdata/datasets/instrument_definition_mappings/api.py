# mxm/v1/marketdata/datasets/instrument_definition_mappings/api.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

from mxm.v1.marketdata.datasets.instrument_definition_mappings.store import (
    InstrumentDefinitionMappingsStore,
)
from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    DatabentoInstrumentIdentity,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# Read models (API-level)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class MappingCoverageReport:
    """
    Read-only coverage summary for instrument_definition_mappings for one product.

    This is intentionally policy-neutral: it reports what exists in the mapping table,
    and how that compares to a caller-provided reference set (usually refdata).
    """

    product_id: str
    as_of_dt: datetime

    # total keys known by the caller (typically refdata maturities)
    ref_total: int

    # mapping-table facts
    mapped_total: int

    # derived deltas
    unmapped_total: int
    unmapped: list[tuple[int, int]]

    # optional diagnostics
    latest_mapping_created_at: Optional[str] = None


# ---------------------------------------------------------------------------
# Public read API
# ---------------------------------------------------------------------------


def resolve_latest_identity(
    *,
    store: InstrumentDefinitionMappingsStore,
    product_id: str,
    contract_year: int,
    contract_month: int,
) -> Optional[DatabentoInstrumentIdentity]:
    """
    Resolve the latest mapping row for (product_id, year, month) to a Databento identity.

    Returns None if no mapping exists. This is a thin wrapper; downstream policy should
    decide whether "None" is fatal.
    """
    row = store.get_latest_mapping_row(
        product_id=product_id,
        contract_year=contract_year,
        contract_month=contract_month,
    )
    if row is None:
        return None

    return DatabentoInstrumentIdentity(
        dataset=str(row["dataset"]),
        publisher_id=int(row["publisher_id"]),
        instrument_id=int(row["instrument_id"]),
        raw_symbol=str(row["raw_symbol"]),
    )


def list_mapped_maturities(
    *,
    store: InstrumentDefinitionMappingsStore,
    product_id: str,
) -> set[tuple[int, int]]:
    """
    Return the set of (year, month) keys that have at least one mapping row.
    """
    return set(store.list_mapped_maturities(product_id=product_id))


def get_mapping_coverage(
    *,
    store: InstrumentDefinitionMappingsStore,
    product_id: str,
    ref_maturities: Iterable[tuple[int, int]],
) -> MappingCoverageReport:
    """
    Compare mapping-table coverage to a caller-provided reference maturity set.

    Typical usage:
      ref_maturities = refdata maturities for product_id
      report = get_mapping_coverage(...)

    This is read-only: it never triggers ingestion or rebuild.
    """
    ref_set = set(ref_maturities)
    mapped = list_mapped_maturities(store=store, product_id=product_id)

    unmapped = sorted(ref_set - mapped)
    latest = store.get_latest_created_at(product_id=product_id)

    return MappingCoverageReport(
        product_id=product_id,
        as_of_dt=_utc_now(),
        ref_total=len(ref_set),
        mapped_total=len(mapped),
        unmapped_total=len(unmapped),
        unmapped=unmapped,
        latest_mapping_created_at=latest,
    )
