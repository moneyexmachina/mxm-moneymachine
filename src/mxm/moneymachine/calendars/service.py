from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mxm.moneymachine.calendars.loader import load_calendar
from mxm.moneymachine.calendars.models import TradingCalendar
from mxm.moneymachine.calendars.registry import CalendarRegistryError
from mxm.refdata import RefDataReader


class CalendarForProductError(RuntimeError):
    """Base error for product→calendar bridge failures."""


class UnknownProductId(CalendarForProductError):
    """Raised when refdata cannot resolve a product_id."""


class MissingProductCalendar(CalendarForProductError):
    """Raised when the product has no trading_calendar mapping."""


class UnknownCalendarForProduct(CalendarForProductError):
    """Raised when the mapped calendar_id cannot be loaded from artifacts."""


def canonical_calendar_id(value: str) -> str:
    """
    Canonicalise calendar ids for MXM V1 runtime.

    Policy:
      - strip whitespace
      - lower-case

    Rationale:
      - refdata may use venue-style ids like 'CMES'
      - calendar registry ids and directory names use lower-case (e.g. 'cmes')
    """
    return value.strip().lower()


def _empty_cache() -> dict[str, TradingCalendar]:
    return {}


@dataclass(slots=True)
class TradingCalendarService:
    """
    Runtime bridge: product_id -> TradingCalendar.

    - Refdata resolves product_id -> FuturesProduct
    - FuturesProduct.trading_calendar identifies the calendar (e.g. 'CMES')
    - Loader resolves calendar_id -> artifacts -> TradingCalendar

    This is read-side runtime code:
    - no builder logic
    - no persistence / mutation
    - optional in-memory cache
    """

    refdata_reader: RefDataReader
    calendars_root: Path | None = None
    _cache: dict[str, TradingCalendar] = field(default_factory=_empty_cache)

    def calendar_for_product(self, product_id: str) -> TradingCalendar:
        """
        Return TradingCalendar for `product_id`.

        Raises:
          - UnknownProductId
          - MissingProductCalendar
          - UnknownCalendarForProduct
        """
        try:
            product = self.refdata_reader.get_product_by_id(product_id)
        except Exception as e:
            raise UnknownProductId(f"Unknown product_id {product_id!r}") from e

        cal_raw = getattr(product, "trading_calendar", None)
        if cal_raw is None or not str(cal_raw).strip():
            raise MissingProductCalendar(
                f"Product {product_id!r} has no trading_calendar mapping in refdata"
            )

        cal_id = canonical_calendar_id(str(cal_raw))

        cached = self._cache.get(cal_id)
        if cached is not None:
            return cached

        try:
            cal = load_calendar(cal_id, root=self.calendars_root)
        except CalendarRegistryError as e:
            raise UnknownCalendarForProduct(
                f"Product {product_id!r} maps to calendar {cal_raw!r} -> {cal_id!r}, "
                "but that calendar could not be loaded from refdata artifacts"
            ) from e

        self._cache[cal_id] = cal
        return cal
