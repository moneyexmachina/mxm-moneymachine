# src/mxm/v1/marketdata/vendor_mapping/models.py
"""
Vendor mapping models.

This module defines the *internal contract* for mapping MXM futures contracts
(product_id + period_id) onto vendor-stable identifiers (e.g., Databento instrument_id).

Design notes:
- No vendor SDK imports here.
- No RefData imports here.
- These types are intentionally small and stable; keep runtime dependencies minimal.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Iterable, Mapping, Optional


class MappingStatus(str, Enum):
    """
    Status of a mapping row produced by reconciliation.

    - ok: a single deterministic mapping exists
    - missing: no vendor instrument could be matched to the MXM period
    - duplicate: multiple vendor instruments match the same MXM period
    - conflict: mapping differs from an existing persisted mapping for the same key
    """

    OK = "ok"
    MISSING = "missing"
    DUPLICATE = "duplicate"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class VendorContractKey:
    """
    Canonical key for a mapping entry.

    This is the stable join between MXM and vendor translation metadata.
    """

    vendor: str
    product_id: str
    period_id: str


@dataclass(frozen=True, slots=True)
class VendorContractMappingRow:
    """
    A single mapping row suitable for persistence.

    Fields are deliberately simple to support storage in SQLite/Parquet/JSON.

    `instrument_id` is vendor-specific, but we store it as an int because the intended
    initial target is Databento instrument_id. If a future vendor uses a non-int ID,
    we can extend to `instrument_key: str` or make this Union[int, str] later.
    """

    key: VendorContractKey

    instrument_id: Optional[int] = None
    raw_symbol: Optional[str] = None

    # Period anchor on the vendor side (e.g., expiration or contract month anchor).
    # Store both an ISO date string (if available) and month/year for easy joins.
    expiration_date: Optional[str] = None  # ISO-8601 "YYYY-MM-DD"
    exp_year: Optional[int] = None
    exp_month: Optional[int] = None

    status: MappingStatus = MappingStatus.OK
    mapped_at: Optional[str] = None  # ISO-8601 timestamp string

    # Optional free-form diagnostics for operator visibility.
    notes: Optional[str] = None

    # Extra metadata (kept small; do not abuse).
    meta: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MappingReport:
    """
    Summary of a reconciliation / refresh run for one (vendor, product_id).

    Intended for CLI output and basic logging/alerting.
    """

    vendor: str
    product_id: str
    scope: str  # e.g. "active" or "all"
    as_of: Optional[str] = None  # ISO date used for active selection (if any)

    total_mxm_contracts: int = 0
    total_vendor_instruments: int = 0

    ok: int = 0
    missing: int = 0
    duplicate: int = 0
    conflict: int = 0

    rows: tuple[VendorContractMappingRow, ...] = ()

    def is_clean(self) -> bool:
        return (self.missing + self.duplicate + self.conflict) == 0

    def problem_rows(self) -> tuple[VendorContractMappingRow, ...]:
        return tuple(r for r in self.rows if r.status != MappingStatus.OK)

    @classmethod
    def from_rows(
        cls,
        *,
        vendor: str,
        product_id: str,
        scope: str,
        as_of: Optional[str],
        total_mxm_contracts: int,
        total_vendor_instruments: int,
        rows: Iterable[VendorContractMappingRow],
    ) -> "MappingReport":
        rows_t = tuple(rows)
        counts = {
            MappingStatus.OK: 0,
            MappingStatus.MISSING: 0,
            MappingStatus.DUPLICATE: 0,
            MappingStatus.CONFLICT: 0,
        }
        for r in rows_t:
            counts[r.status] += 1

        return cls(
            vendor=vendor,
            product_id=product_id,
            scope=scope,
            as_of=as_of,
            total_mxm_contracts=total_mxm_contracts,
            total_vendor_instruments=total_vendor_instruments,
            ok=counts[MappingStatus.OK],
            missing=counts[MappingStatus.MISSING],
            duplicate=counts[MappingStatus.DUPLICATE],
            conflict=counts[MappingStatus.CONFLICT],
            rows=rows_t,
        )
