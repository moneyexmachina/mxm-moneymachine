from __future__ import annotations

"""
MXM V1 — Execution price accessors.

This module defines the boundary between the execution layer and the
market-data layer for retrieval of execution reference prices.

At the current stage of the execution design, executors need a simple
interface:

    (contract_id, submission_timestamp) -> execution_price

The first concrete implementation provided here is a lazy-loading,
product-cached accessor built on top of the daily_stats market-data
surface.

Design principles
-----------------
- execution-facing API remains small and stable
- loading is lazy and cached by product_id
- in-memory lookup is normalised once per loaded product
- timestamp handling is UTC-normalised and deterministic
- missing execution prices fail loudly

Current assumptions
-------------------
- submission timestamps are already aligned to the intended trading
  session semantics of the backtest
- daily_stats trading_date is therefore the correct lookup key after
  UTC-day normalisation
- the execution reference price field (for example 'settle' or 'close')
  is explicitly selected by configuration

Performance notes
-----------------
The current implementation is designed to avoid repeated filesystem /
SQLite access during the hot execution loop by:

1. loading daily_stats only on first need for a given product_id
2. normalising the chosen price field into an in-memory lookup object
3. serving subsequent scalar lookups from that cached structure

If later profiling shows this accessor to be a bottleneck, the internal
lookup representation can be replaced without changing the executor
interface.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from mxm_refdata.api.ref_data_api import RefDataAPI

from mxm.v1.marketdata.datasets.daily_stats.api import read_daily_stats_product
from mxm.v1.utils.time_utils import to_utc_day


class ExecutionPriceAccessor(ABC):
    """
    Abstract accessor for execution reference prices.

    Executors use this interface to resolve the execution price for a
    contract at a given submission timestamp.

    The submission timestamp is assumed to already represent the intended
    session context of the execution step.
    """

    @abstractmethod
    def get_execution_price(
        self,
        contract_id: str,
        submission_timestamp: pd.Timestamp,
    ) -> float:
        """
        Return the execution reference price for a contract at the given
        submission timestamp.
        """
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _ProductDailyStatsPriceLookup:
    """
    In-memory execution-price lookup for one product.

    Parameters
    ----------
    product_id:
        Product identifier whose contracts are represented in this
        lookup.

    price_field:
        Name of the daily_stats column used as execution price.

    prices:
        MultiIndex Series indexed by (contract_id, trading_date) and
        containing float execution prices.
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
        Return the execution price for a contract on a given trading day.

        Raises
        ------
        ValueError
            If no price exists for the given (contract_id, trading_date).
        """
        key = (contract_id, trading_date)

        try:
            value = self.prices.loc[key]
        except KeyError as exc:
            raise ValueError(
                "Missing execution price in daily_stats lookup for "
                f"product_id={self.product_id!r}, contract_id={contract_id!r}, "
                f"trading_date={trading_date!r}, price_field={self.price_field!r}."
            ) from exc

        return float(value)


def _empty_product_lookup_cache() -> dict[str, _ProductDailyStatsPriceLookup]:
    return {}


@dataclass(slots=True)
class DailyStatsExecutionPriceAccessor(ExecutionPriceAccessor):
    """
    Lazy-loading execution-price accessor backed by daily_stats.

    Parameters
    ----------
    price_field:
        Name of the daily_stats column used as the execution price.
        Typical choices are 'settle' or 'close'.

    root:
        Optional MXM root used by the market-data read surface.

    ref_data_api:
        Reference-data API used to resolve contract_id -> product_id.
        If omitted, a default RefDataAPI() instance is constructed.

    Notes
    -----
    This accessor loads daily_stats product-by-product on first use and
    caches each product's execution-price lookup in memory.
    """

    price_field: str
    root: Path | None = None
    ref_data_api: RefDataAPI = field(default_factory=RefDataAPI)
    _cache: dict[str, _ProductDailyStatsPriceLookup] = field(
        default_factory=_empty_product_lookup_cache,
        init=False,
        repr=False,
    )

    def get_execution_price(
        self,
        contract_id: str,
        submission_timestamp: pd.Timestamp,
    ) -> float:
        """
        Return the execution reference price for a contract at the given
        submission timestamp.

        Semantics
        ---------
        The submission timestamp is normalised to UTC day and used as the
        daily_stats trading_date lookup key.

        Raises
        ------
        ValueError
            If the contract cannot be resolved, the relevant product
            cannot be loaded, or no execution price exists for the given
            contract/day.
        """
        contract = self.ref_data_api.get_contract_by_id(contract_id)
        if contract is None:
            raise ValueError(
                f"Unknown contract_id={contract_id!r}: could not resolve contract in refdata."
            )

        product_id = contract.product_id
        trading_date = to_utc_day(submission_timestamp)

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
        Load and normalise daily_stats execution prices for one product.
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

        if out[self.price_field].isna().any():
            raise ValueError(
                f"daily_stats for product_id={product_id!r} contains null values in "
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
