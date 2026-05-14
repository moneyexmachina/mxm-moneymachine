from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache

from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.refdata.models.contracts.futures_contract import FuturesContract
from mxm.refdata.models.periods import Period
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.utils.time_utils import utc_now_ts


@dataclass(frozen=True)
class DatabentoInstrumentIdentity:
    dataset: str
    publisher_id: int
    instrument_id: int
    raw_symbol: str


# ---------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------


class DatabentoInstrumentResolutionError(RuntimeError):
    """Base class for Databento instrument resolution errors."""


@dataclass(frozen=True)
class InstrumentNotMappedError(DatabentoInstrumentResolutionError):
    product_id: str
    period_id: str
    contract_year: int
    contract_month: int
    as_of_dt: datetime

    def __str__(self) -> str:
        return (
            "No Databento instrument mapping found for "
            f"(product_id={self.product_id}, period_id={self.period_id}, "
            f"contract={self.contract_year:04d}-{self.contract_month:02d}) "
            f"as_of_dt={self.as_of_dt.isoformat()}."
        )


@dataclass(frozen=True)
class InstrumentAmbiguityError(DatabentoInstrumentResolutionError):
    product_id: str
    period_id: str
    contract_year: int
    contract_month: int
    as_of_dt: datetime
    row_count: int

    def __str__(self) -> str:
        return (
            "Ambiguous Databento instrument mapping for "
            f"(product_id={self.product_id}, period_id={self.period_id}, "
            f"contract={self.contract_year:04d}-{self.contract_month:02d}) "
            f"as_of_dt={self.as_of_dt.isoformat()}: {self.row_count} candidate rows."
        )


@dataclass(frozen=True)
class RefdataPeriodLookupError(DatabentoInstrumentResolutionError):
    period_id: str

    def __str__(self) -> str:
        return f"Unable to resolve FuturesContract.period_id={self.period_id!r} to a refdata Period."


# ---------------------------------------------------------------------
# Period lookup (cached)
# ---------------------------------------------------------------------


@lru_cache(maxsize=1)
def period_by_id() -> dict[str, Period]:
    """
    Cache Period objects by period_id for this process lifetime.
    Uses RefDataAPI().get_periods(), as in Proof 96.
    """
    api = RefDataAPI()
    periods = api.get_periods()
    return {p.period_id: p for p in periods}


def contract_year_month(contract: FuturesContract) -> tuple[int, int]:
    """
    MVP mapping key extraction:
      FuturesContract.period_id -> Period.first_date.year/month
    """
    period = period_by_id().get(contract.period_id)
    if period is None:
        raise RefdataPeriodLookupError(period_id=contract.period_id)

    return (int(period.first_date.year), int(period.first_date.month))


# ---------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------


def resolve_databento_instrument(
    backend: SQLiteBackend,
    contract: FuturesContract,
    *,
    as_of_dt: datetime | None = None,
) -> DatabentoInstrumentIdentity:
    """
    Resolve a FuturesContract to Databento's tradable identity.

    Returns:
        (dataset, publisher_id, instrument_id)

    Resolution rules (MVP):
      - Key: (product_id, contract_year, contract_month) where y/m derived from period_id
      - Authoritative mapping: ignore validity windows by default.
        The mapping table is an append-only record of our mapping assertions.
      - Exactly one mapping row must exist for this key; otherwise raise explicit errors.

    Note:
      - valid_from/valid_to currently represent instrument lifecycle (activation/expiration) for MVP.
        Mapping supersession semantics will be introduced later. Until then, `as_of_dt` is ignored.

    Hard boundary:
      - no raw_symbol fallback
      - no vendor calls
      - uses only instrument_definition_mappings
    """
    # For MVP, as_of_dt is intentionally ignored (see note above).
    # Keep it in the signature to avoid churn; later it will support time-travel resolution
    # once we introduce true mapping-regime semantics.
    _ = as_of_dt
    as_of_dt_utc = utc_now_ts()
    y, m = contract_year_month(contract)

    tx = getattr(backend, "transaction_no_migrate", backend.transaction)
    with tx() as conn:
        rows = conn.execute(
            """
            SELECT dataset, publisher_id, instrument_id, raw_symbol
            FROM instrument_definition_mappings
            WHERE product_id = ?
              AND contract_year = ?
              AND contract_month = ?
            ORDER BY created_at DESC
            LIMIT 2;
            """,
            (contract.product_id, y, m),
        ).fetchall()

    if len(rows) == 0:
        # Keep as_of_dt in error for now; use "now" only for message completeness.
        raise InstrumentNotMappedError(
            product_id=contract.product_id,
            period_id=contract.period_id,
            contract_year=y,
            contract_month=m,
            as_of_dt=as_of_dt_utc,
        )

    if len(rows) > 1:
        raise InstrumentAmbiguityError(
            product_id=contract.product_id,
            period_id=contract.period_id,
            contract_year=y,
            contract_month=m,
            as_of_dt=as_of_dt_utc,
            row_count=len(rows),
        )

    row = rows[0]
    result = DatabentoInstrumentIdentity(
        dataset=str(row["dataset"]),
        publisher_id=int(row["publisher_id"]),
        instrument_id=int(row["instrument_id"]),
        raw_symbol=str(row["raw_symbol"]),
    )
    return result
