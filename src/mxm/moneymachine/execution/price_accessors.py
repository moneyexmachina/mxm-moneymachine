"""
MXM V1 — Price accessors for execution and mark-to-market valuation.

This module defines the boundary between execution / PnL layers and the
market-data layer for retrieval of contract prices.

V1 temporal policy
------------------
This module is fully session-native.

Both accessor roles consume a trading-session label, not an execution
timestamp. In MXM V1, the canonical session-label representation is
`np.datetime64[D]`.

The current concrete accessors are backed by the `daily_stats` dataset.
That dataset stores its session-level lookup key in the column
`trading_date`, represented as a UTC-normalized midnight pandas
Timestamp. This is treated here as a storage representation of the
session label, not as a true event timestamp.

Semantic accessor roles
-----------------------
Two semantic accessor roles are defined here:

1. ExecutionPriceAccessor

   Used by executors to obtain the execution reference price for a
   contract for a given trading session.

   Interface:

       (contract_id, session) -> execution_price

2. MarkPriceAccessor

   Used by PnL and valuation logic to obtain the mark price for a
   contract for a given trading session.

   Interface:

       (contract_id, session) -> mark_price

At the current stage of the implementation, both accessors are backed by
the same underlying daily_stats market-data surface and may resolve the
same price field (for example 'settle'). However, the semantic roles are
kept distinct because execution pricing and mark-to-market valuation are
architecturally different concerns.

The first concrete implementations provided here are lazy-loading,
product-cached accessors built on top of the daily_stats dataset.

Design principles
-----------------
- accessor-facing APIs remain small and semantically explicit
- loading is lazy and cached by product_id
- in-memory lookup is normalised once per loaded product
- session handling is deterministic and explicit
- missing prices fail loudly
- execution and mark-price semantics remain distinct even when backed by
  the same dataset

Performance notes
-----------------
The current implementation is designed to avoid repeated filesystem /
SQLite access during hot loops by:

1. loading daily_stats only on first need for a given product_id
2. normalising the chosen price field into an in-memory lookup object
3. serving subsequent scalar lookups from that cached structure

If later profiling shows these accessors to be a bottleneck, the
internal lookup representation can be replaced without changing the
public accessor interfaces.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from mxm.moneymachine.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.moneymachine.marketdata.datasets.daily_mark.api import read_daily_mark_product
from mxm.moneymachine.marketdata.datasets.daily_stats.api import (
    read_daily_stats_product,
)
from mxm.moneymachine.utils.date_utils import coerce_np_day
from mxm.refdata.api.ref_data_api import RefDataAPI


class ExecutionPriceAccessor(ABC):
    """
    Abstract accessor for execution reference prices.

    Executors use this interface to resolve the execution price for a
    contract for a given trading session.

    In MXM V1, execution is modelled at session resolution rather than at
    timestamp/event resolution.
    """

    @abstractmethod
    def get_execution_price(
        self,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        """
        Return the execution reference price for a contract for the given
        trading session.
        """
        raise NotImplementedError


class MarkPriceAccessor(ABC):
    """
    Abstract accessor for session mark prices.

    PnL and valuation logic use this interface to resolve the mark price
    for a contract for a given trading session.
    """

    @abstractmethod
    def get_mark_price(
        self,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        """
        Return the mark price for a contract for the given trading
        session.
        """
        raise NotImplementedError


class MissingDailyStatsPriceError(ValueError):
    """Raised when no daily_stats price exists for a contract/day key."""


@dataclass(frozen=True, slots=True)
class _ProductDailyStatsPriceLookup:
    """
    In-memory price lookup for one product.

    Parameters
    ----------
    product_id:
        Product identifier whose contracts are represented in this
        lookup.

    price_field:
        Name of the daily_stats column used as the resolved price.

    prices:
        MultiIndex Series indexed by (contract_id, trading_date) and
        containing float prices.

        Here `trading_date` is the stored representation of the session
        label used by the daily_stats dataset:
            pd.Timestamp at 00:00:00+00:00
    """

    product_id: str
    price_field: str
    prices: pd.Series

    def __post_init__(self) -> None:
        self._validate_prices()

    def _validate_prices(self) -> None:
        prices = self.prices

        if not isinstance(prices.index, pd.MultiIndex):
            raise ValueError(
                "_ProductDailyStatsPriceLookup.prices must have a MultiIndex."
            )

        if prices.index.nlevels != 2:
            raise ValueError(
                "_ProductDailyStatsPriceLookup.prices must have exactly two index levels."
            )

        expected_names = ["contract_id", "trading_date"]
        if list(prices.index.names) != expected_names:
            raise ValueError(
                f"_ProductDailyStatsPriceLookup.prices index names must be "
                f"{expected_names}, got {list(prices.index.names)!r}."
            )

        if prices.index.has_duplicates:
            raise ValueError(
                "_ProductDailyStatsPriceLookup.prices must not contain duplicate "
                "(contract_id, trading_date) keys."
            )

        if prices.isna().any():
            raise ValueError(
                "_ProductDailyStatsPriceLookup.prices must not contain missing values."
            )

        if not pd.api.types.is_numeric_dtype(prices):
            raise TypeError(
                "_ProductDailyStatsPriceLookup.prices must contain numeric values."
            )

    def get_price(
        self,
        contract_id: str,
        trading_date: pd.Timestamp,
    ) -> float:
        """
        Return the price for a contract on a given stored trading-date key.

        Parameters
        ----------
        contract_id:
            Contract identifier.

        trading_date:
            UTC-normalized midnight pandas Timestamp used by daily_stats
            as the stored representation of the session label.

        Raises
        ------
        ValueError
            If no price exists for the given (contract_id, trading_date).
        """
        key = (contract_id, trading_date)

        try:
            value = self.prices.loc[key]
        except KeyError as exc:
            raise MissingDailyStatsPriceError(
                "Missing price in daily_stats lookup for "
                f"product_id={self.product_id!r}, contract_id={contract_id!r}, "
                f"trading_date={trading_date!r}, price_field={self.price_field!r}."
            ) from exc

        return float(value)


def _empty_product_lookup_cache() -> dict[str, _ProductDailyStatsPriceLookup]:
    return {}


def _session_to_trading_date_key(session: Any) -> pd.Timestamp:
    """
    Convert a V1 session label into the stored daily_stats lookup key.

    Parameters
    ----------
    session:
        Session label, expected to be coercible to `np.datetime64[D]`.

    Returns
    -------
    pd.Timestamp
        UTC-normalized midnight Timestamp used by daily_stats as the
        storage representation of the session label.
    """
    session_day = coerce_np_day(session)
    return pd.Timestamp(session_day, tz="UTC")


@dataclass(slots=True)
class _DailyStatsPriceAccessorBase:
    """
    Shared lazy-loading daily_stats-backed price accessor base.

    Parameters
    ----------
    price_field:
        Name of the daily_stats column used as the resolved price.
        Typical choices are 'settle' or 'close'.

    root:
        Optional MXM root used by the market-data read surface.

    ref_data_api:
        Reference-data API used to resolve contract_id -> product_id.
        If omitted, a default RefDataAPI() instance is constructed.

    Notes
    -----
    This base class loads daily_stats product-by-product on first use and
    caches each product's price lookup in memory.
    """

    price_field: str
    root: Path | None = None
    ref_data_api: RefDataAPI = field(default_factory=RefDataAPI)
    _cache: dict[str, _ProductDailyStatsPriceLookup] = field(
        default_factory=_empty_product_lookup_cache,
        init=False,
        repr=False,
    )

    def _get_price_for_session(
        self,
        *,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        """
        Resolve a daily_stats price for a contract for a given session.

        Semantics
        ---------
        The input `session` is a V1 session label (`np.datetime64[D]`).
        It is converted to the stored daily_stats lookup-key
        representation:

            session label -> UTC-midnight pandas Timestamp

        Raises
        ------
        ValueError
            If the contract cannot be resolved, the relevant product
            cannot be loaded, or no price exists for the given
            contract/session key.
        """
        contract = self.ref_data_api.get_contract_by_id(contract_id)

        product_id = contract.product_id
        trading_date = _session_to_trading_date_key(session)

        lookup = self._get_or_load_product_lookup(product_id)
        return lookup.get_price(contract_id=contract_id, trading_date=trading_date)

    def _get_or_load_product_lookup(
        self,
        product_id: str,
    ) -> _ProductDailyStatsPriceLookup:
        """
        Return cached per-product price lookup, loading it on first use.
        """
        if product_id in self._cache:
            return self._cache[product_id]

        lookup = self._load_product_lookup(product_id)
        self._cache[product_id] = lookup
        return lookup

    def _load_product_lookup(
        self,
        product_id: str,
    ) -> _ProductDailyStatsPriceLookup:
        """
        Load and normalise daily_stats prices for one product.
        """
        df = read_daily_stats_product(
            product_id=product_id,
            root=self.root,
        )

        if df.empty:
            raise ValueError(
                f"No daily_stats rows available for product_id={product_id!r}."
            )

        required_columns = {"contract_id", "trading_date", self.price_field}
        missing_columns = required_columns.difference(df.columns)
        if missing_columns:
            raise ValueError(
                f"daily_stats for product_id={product_id!r} is missing required columns "
                f"{sorted(missing_columns)!r}."
            )

        out = df.loc[:, ["contract_id", "trading_date", self.price_field]].copy()

        if out["contract_id"].isna().any():
            raise ValueError(
                f"daily_stats for product_id={product_id!r} contains null contract_id."
            )

        if out["trading_date"].isna().any():
            raise ValueError(
                f"daily_stats for product_id={product_id!r} contains null trading_date."
            )

        out = out.loc[out[self.price_field].notna()].copy()

        if out.empty:
            raise ValueError(
                f"daily_stats for product_id={product_id!r} has no non-null values in "
                f"price_field={self.price_field!r}."
            )

        if not pd.api.types.is_numeric_dtype(out[self.price_field]):
            raise TypeError(
                f"daily_stats for product_id={product_id!r} has non-numeric values in "
                f"price_field={self.price_field!r}."
            )

        if not isinstance(out["trading_date"].dtype, pd.DatetimeTZDtype):
            raise TypeError(
                f"daily_stats for product_id={product_id!r} trading_date must be tz-aware."
            )

        prices = (
            out.set_index(["contract_id", "trading_date"])[self.price_field]
            .astype("float64")
            .sort_index()
        )

        return _ProductDailyStatsPriceLookup(
            product_id=product_id,
            price_field=self.price_field,
            prices=prices,
        )


@dataclass(slots=True)
class DailyStatsExecutionPriceAccessor(
    _DailyStatsPriceAccessorBase, ExecutionPriceAccessor
):
    """
    Lazy-loading execution-price accessor backed by daily_stats.

    In MXM V1, this accessor is session-native and resolves an execution
    reference price for a contract for a given trading session.
    """

    def get_execution_price(
        self,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        try:
            return self._get_price_for_session(
                contract_id=contract_id,
                session=session,
            )
        except MissingDailyStatsPriceError as exc:
            raise ValueError(
                "Missing execution price for "
                f"contract_id={contract_id!r}, "
                f"session={session!r}, "
                f"price_field={self.price_field!r}."
            ) from exc


@dataclass(slots=True)
class DailyStatsMarkPriceAccessor(_DailyStatsPriceAccessorBase, MarkPriceAccessor):
    """
    Lazy-loading mark-price accessor backed by daily_stats.

    This accessor is intended for mark-to-market valuation and PnL
    construction, for example session settlement lookup in the PnL layer.
    """

    def get_mark_price(
        self,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        try:
            return self._get_price_for_session(
                contract_id=contract_id,
                session=session,
            )
        except MissingDailyStatsPriceError as exc:
            raise ValueError(
                "Missing mark price for "
                f"contract_id={contract_id!r}, "
                f"session={session!r}, "
                f"price_field={self.price_field!r}."
            ) from exc


class MissingDailyMarkPriceError(ValueError):
    """Raised when no daily_mark price exists for a contract/session key."""


@dataclass(frozen=True, slots=True)
class _ProductDailyMarkPriceLookup:
    """
    In-memory price lookup for one product under one MXM business calendar.

    Parameters
    ----------
    product_id:
        Product identifier whose contracts are represented in this
        lookup.

    calendar_id:
        MXM business calendar identity under which the daily_mark surface
        was read.

    prices:
        MultiIndex Series indexed by (contract_id, session_id) and
        containing float mark prices.
    """

    product_id: str
    calendar_id: str
    prices: pd.Series

    def __post_init__(self) -> None:
        self._validate_prices()

    def _validate_prices(self) -> None:
        prices = self.prices

        if not isinstance(prices.index, pd.MultiIndex):
            raise ValueError(
                "_ProductDailyMarkPriceLookup.prices must have a MultiIndex."
            )

        if prices.index.nlevels != 2:
            raise ValueError(
                "_ProductDailyMarkPriceLookup.prices must have exactly two index levels."
            )

        expected_names = ["contract_id", "session_id"]
        if list(prices.index.names) != expected_names:
            raise ValueError(
                f"_ProductDailyMarkPriceLookup.prices index names must be "
                f"{expected_names}, got {list(prices.index.names)!r}."
            )

        if prices.index.has_duplicates:
            raise ValueError(
                "_ProductDailyMarkPriceLookup.prices must not contain duplicate "
                "(contract_id, session_id) keys."
            )

        if prices.isna().any():
            raise ValueError(
                "_ProductDailyMarkPriceLookup.prices must not contain missing values."
            )

        if not pd.api.types.is_numeric_dtype(prices):
            raise TypeError(
                "_ProductDailyMarkPriceLookup.prices must contain numeric values."
            )

    def get_price(
        self,
        contract_id: str,
        session_id: int,
    ) -> float:
        """
        Return the price for a contract on a given session_id key.

        Parameters
        ----------
        contract_id:
            Contract identifier.

        session_id:
            MXM business-session id.

        Raises
        ------
        ValueError
            If no price exists for the given (contract_id, session_id).
        """
        key = (contract_id, session_id)

        try:
            value = self.prices.loc[key]
        except KeyError as exc:
            raise MissingDailyMarkPriceError(
                "Missing price in daily_mark lookup for "
                f"calendar_id={self.calendar_id!r}, "
                f"product_id={self.product_id!r}, "
                f"contract_id={contract_id!r}, "
                f"session_id={session_id!r}."
            ) from exc

        return float(value)


def _empty_daily_mark_product_lookup_cache() -> dict[str, _ProductDailyMarkPriceLookup]:
    return {}


@dataclass(slots=True)
class _DailyMarkPriceAccessorBase:
    """
    Shared lazy-loading daily_mark-backed price accessor base.

    Parameters
    ----------
    mxm_business_calendar:
        MXM business calendar used to resolve session labels to
        session_ids and to supply the calendar_id used by daily_mark.

    root:
        Optional MXM root used by the market-data read surface.

    ref_data_api:
        Reference-data API used to resolve contract_id -> product_id.
        If omitted, a default RefDataAPI() instance is constructed.

    Notes
    -----
    This base class loads daily_mark product-by-product on first use and
    caches each product's price lookup in memory.
    """

    mxm_business_calendar: MXMBusinessCalendar
    root: Path | None = None
    ref_data_api: RefDataAPI = field(default_factory=RefDataAPI)
    _cache: dict[str, _ProductDailyMarkPriceLookup] = field(
        default_factory=_empty_daily_mark_product_lookup_cache,
        init=False,
        repr=False,
    )

    def _get_price_for_session(
        self,
        *,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        """
        Resolve a daily_mark price for a contract for a given session.

        Semantics
        ---------
        The input `session` is a V1 session label (`np.datetime64[D]`).
        It is converted to the MXM business-session identity used by
        daily_mark:

            session label -> session_id

        Raises
        ------
        ValueError
            If the contract cannot be resolved, the relevant product
            cannot be loaded, the session label is not present in the
            configured business calendar, or no price exists for the
            given contract/session key.
        """
        contract = self.ref_data_api.get_contract_by_id(contract_id)

        product_id = contract.product_id
        session_day = coerce_np_day(session)
        session_id = self.mxm_business_calendar.session_id_from_label(session_day)

        lookup = self._get_or_load_product_lookup(product_id)
        return lookup.get_price(contract_id=contract_id, session_id=session_id)

    def _get_or_load_product_lookup(
        self,
        product_id: str,
    ) -> _ProductDailyMarkPriceLookup:
        """
        Return cached per-product price lookup, loading it on first use.
        """
        if product_id in self._cache:
            return self._cache[product_id]

        lookup = self._load_product_lookup(product_id)
        self._cache[product_id] = lookup
        return lookup

    def _load_product_lookup(
        self,
        product_id: str,
    ) -> _ProductDailyMarkPriceLookup:
        """
        Load and normalise daily_mark prices for one product.
        """
        df = read_daily_mark_product(
            calendar_id=self.mxm_business_calendar.calendar_id,
            product_id=product_id,
            root=self.root,
        )

        if df.empty:
            raise ValueError(
                "No daily_mark rows available for "
                f"calendar_id={self.mxm_business_calendar.calendar_id!r}, "
                f"product_id={product_id!r}."
            )

        required_columns = {"contract_id", "session_id", "mark_px", "is_markable"}
        missing_columns = required_columns.difference(df.columns)
        if missing_columns:
            raise ValueError(
                f"daily_mark for calendar_id={self.mxm_business_calendar.calendar_id!r}, "
                f"product_id={product_id!r} is missing required columns "
                f"{sorted(missing_columns)!r}."
            )

        out = df.loc[:, ["contract_id", "session_id", "mark_px", "is_markable"]].copy()

        if out["contract_id"].isna().any():
            raise ValueError(
                f"daily_mark for product_id={product_id!r} contains null contract_id."
            )

        if out["session_id"].isna().any():
            raise ValueError(
                f"daily_mark for product_id={product_id!r} contains null session_id."
            )

        if not pd.api.types.is_integer_dtype(out["session_id"]):
            raise TypeError(
                f"daily_mark for product_id={product_id!r} session_id must be integer-typed."
            )

        if not pd.api.types.is_bool_dtype(out["is_markable"]):
            raise TypeError(
                f"daily_mark for product_id={product_id!r} is_markable must be boolean-typed."
            )

        out = out.loc[out["is_markable"]].copy()

        if out.empty:
            raise ValueError(
                "daily_mark for "
                f"calendar_id={self.mxm_business_calendar.calendar_id!r}, "
                f"product_id={product_id!r} has no markable rows."
            )

        if out["mark_px"].isna().any():
            raise ValueError(
                f"daily_mark for product_id={product_id!r} contains null mark_px in markable rows."
            )

        if not pd.api.types.is_numeric_dtype(out["mark_px"]):
            raise TypeError(
                f"daily_mark for product_id={product_id!r} has non-numeric values in mark_px."
            )

        prices = (
            out.set_index(["contract_id", "session_id"])["mark_px"]
            .astype("float64")
            .sort_index()
        )

        return _ProductDailyMarkPriceLookup(
            product_id=product_id,
            calendar_id=self.mxm_business_calendar.calendar_id,
            prices=prices,
        )


@dataclass(slots=True)
class DailyMarkExecutionPriceAccessor(
    _DailyMarkPriceAccessorBase, ExecutionPriceAccessor
):
    """
    Lazy-loading execution-price accessor backed by daily_mark.

    In current MXM V1 MVP semantics, this accessor resolves the execution
    reference price for a contract for a given trading session from the
    authoritative daily_mark surface.
    """

    def get_execution_price(
        self,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        try:
            return self._get_price_for_session(
                contract_id=contract_id,
                session=session,
            )
        except MissingDailyMarkPriceError as exc:
            raise ValueError(
                "Missing execution price for "
                f"contract_id={contract_id!r}, "
                f"session={session!r}, "
                f"calendar_id={self.mxm_business_calendar.calendar_id!r}."
            ) from exc


@dataclass(slots=True)
class DailyMarkPriceAccessor(_DailyMarkPriceAccessorBase, MarkPriceAccessor):
    """
    Lazy-loading mark-price accessor backed by daily_mark.

    This accessor is intended for mark-to-market valuation and PnL
    construction against the authoritative MXM business-session mark
    surface.
    """

    def get_mark_price(
        self,
        contract_id: str,
        session: np.datetime64,
    ) -> float:
        try:
            return self._get_price_for_session(
                contract_id=contract_id,
                session=session,
            )
        except MissingDailyMarkPriceError as exc:
            raise ValueError(
                "Missing mark price for "
                f"contract_id={contract_id!r}, "
                f"session={session!r}, "
                f"calendar_id={self.mxm_business_calendar.calendar_id!r}."
            ) from exc
