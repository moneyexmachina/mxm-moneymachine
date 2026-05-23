"""
Databento Timeseries Pull Layer (DataIO-backed)

This module provides thin, canonical wrappers around Databento
`timeseries.get_range(...)` calls, routed through MXM's DataIO layer.

Design goals
------------
- All vendor requests flow through DataIO for:
    - deterministic request hashing
    - caching and replay
    - cost visibility
    - auditability
- Canonical request parameters are constructed in a stable form so that
  equivalent logical requests produce identical DataIO hashes.
- The module returns raw pandas DataFrames decoded from cached Parquet
  payload bytes. No schema-level normalization is performed here unless
  explicitly documented (e.g. instrument definitions).

Separation of concerns
----------------------
- This module:
    - builds canonical Databento request parameters
    - performs DataIO-backed fetches
    - decodes cached Parquet bytes to pandas DataFrame
- Dataset-specific normalization logic lives under:
    mxm.moneymachine.marketdata.vendors.databento.normalize.*
- Dataset-level orchestration (expected windows, attempts, coverage)
  lives under:
    mxm.moneymachine.marketdata.datasets.*

Supported schemas (current)
---------------------------
- "ohlcv_1d"
- "instrument_definition"
- "statistics_1d"

Extending to new schemas
------------------------
To add support for another Databento schema (e.g. statistics):

1. Add a thin wrapper similar to `pull_ohlcv_1d`.
2. Optionally add a `*_by_instrument_id` convenience wrapper.
3. Implement normalization under `vendors.databento.normalize`.
4. Keep request parameter construction consistent with
   `_canonical_timeseries_params(...)`.

Important invariants
--------------------
- All returned DataFrames are direct decodes of the Parquet payload
  provided by the DataIO adapter.
- The DataIO adapter for `source="databento"` must already be registered
  in the mxm.dataio registry before calling these functions.
- Request hashing depends only on canonical parameters; therefore
  parameter normalization must remain stable.

This module intentionally contains no dataset-specific business logic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from io import BytesIO
from pathlib import Path
from typing import Any

import pandas as pd

from mxm.dataio.api import CacheMode, DataIoSession
from mxm.dataio.models import Request, Response
from mxm.moneymachine.marketdata.config.dataio import marketdata_dataio_cfg
from mxm.moneymachine.marketdata.mapping.vendors.databento.product_roots import (
    get_databento_product_root,
)
from mxm.moneymachine.marketdata.vendors.databento.normalize.instrument_definitions import (
    normalize_instrument_definitions,
)

SymbolsT = str | Sequence[str]


def _parquet_bytes_to_df(payload: bytes) -> pd.DataFrame:
    buf = BytesIO(payload)
    df = pd.read_parquet(buf)
    return df


def _read_payload_bytes(resp: Response) -> bytes:
    if resp.path is None:
        raise RuntimeError("DataIO Response has no path; cannot read payload bytes.")
    return Path(resp.path).read_bytes()


def _canonical_timeseries_params(
    *,
    dataset: str,
    schema: str,
    symbols: SymbolsT,
    stype_in: str,
    start: str,
    end: str,
    extra: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Canonical params for *any* Databento timeseries.get_range(...) call.

    These params should be stable and safe to use as part of the DataIO request hash.
    """
    # Normalize symbols for stable hashing:
    # - keep str as str
    # - sequences become list[str]
    norm_symbols: Any

    if isinstance(symbols, str):
        norm_symbols = symbols
    elif isinstance(symbols, (int, float)):
        norm_symbols = str(symbols)
    else:
        norm_symbols = [str(s) for s in symbols]

    params: dict[str, Any] = {
        "dataset": str(dataset),
        "schema": str(schema),
        "symbols": norm_symbols,
        "stype_in": str(stype_in),
        "start": str(start),
        "end": str(end),
    }
    if extra:
        params["extra"] = dict(extra)

    return params


def pull_timeseries(
    *,
    dataset: str,
    schema: str,
    symbols: SymbolsT,
    stype_in: str,
    start: str,
    end: str,
    source: str = "databento",
    kind: str = "databento.timeseries.get_range",
    extra: Mapping[str, Any] | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Generic DataIO-backed pull for Databento timeseries.get_range(...) calls.

    Important:
    - The DataIO adapter for `source` must already be registered in the global
      mxm.dataio registry (mxm.dataio.registry.register()).
    - The registered Fetcher must understand the canonical params produced here.

    Returns a raw DataFrame decoded from cached Parquet bytes.
    """
    dio_cfg = marketdata_dataio_cfg()

    params = _canonical_timeseries_params(
        dataset=dataset,
        schema=schema,
        symbols=symbols,
        stype_in=stype_in,
        start=start,
        end=end,
        extra=extra,
    )

    with DataIoSession(
        source=source,
        cfg=dio_cfg,
        cache_mode=CacheMode.BYPASS if force_refresh else CacheMode.DEFAULT,
        ttl=None,
        as_of_bucket=None,
        cache_tag=None,
    ) as io:
        req: Request = io.request(kind=kind, params=params)
        resp: Response = io.fetch(req)

    print(f"[dataio] request_hash={req.hash} response_id={resp.id} path={resp.path}")

    payload = _read_payload_bytes(resp)
    return _parquet_bytes_to_df(payload)


def pull_ohlcv_1d(
    *,
    dataset: str,
    symbol: str,
    stype_in: str,
    start: str,
    end: str,
    source: str = "databento",
    extra: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """
    DataIO-backed pull for Databento ohlcv-1d.
    Thin wrapper around pull_timeseries_via_dataio(...).
    """
    return pull_timeseries(
        dataset=dataset,
        schema="ohlcv-1d",
        symbols=symbol,
        stype_in=stype_in,
        start=start,
        end=end,
        source=source,
        extra=extra,
    )


def pull_ohlcv_1d_by_instrument_id(
    *,
    dataset: str,
    instrument_id: int,
    start: str,
    end: str,
    source: str = "databento",
    extra: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    return pull_ohlcv_1d(
        dataset=dataset,
        symbol=str(instrument_id),
        stype_in="instrument_id",
        start=start,
        end=end,
        source=source,
        extra=extra,
    )


def pull_statistics_1d(
    *,
    dataset: str,
    symbol: str,
    stype_in: str,
    start: str,
    end: str,
    source: str = "databento",
    extra: Mapping[str, Any] | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    DataIO-backed pull for Databento statistics (rtype=24) over a time range.

    Notes:
    - The returned DataFrame is a raw decode of the cached Parquet payload.
    - Dataset-specific normalization (e.g. trading_date derivation, sentinel
      handling, price scaling) is handled elsewhere.
    """
    return pull_timeseries(
        dataset=dataset,
        schema="statistics",
        symbols=symbol,
        stype_in=stype_in,
        start=start,
        end=end,
        source=source,
        extra=extra,
        force_refresh=force_refresh,
    )


def pull_statistics_1d_by_instrument_id(
    *,
    dataset: str,
    instrument_id: int,
    start: str,
    end: str,
    source: str = "databento",
    extra: Mapping[str, Any] | None = None,
    force_refresh: bool = False,
) -> pd.DataFrame:
    """
    Convenience wrapper to pull statistics by Databento `instrument_id`.
    """
    return pull_statistics_1d(
        dataset=dataset,
        symbol=str(instrument_id),
        stype_in="instrument_id",
        start=start,
        end=end,
        source=source,
        extra=extra,
        force_refresh=force_refresh,
    )


def pull_instrument_definitions(
    *,
    product_id: str,
    start: str,
    end: str,
    source: str = "databento",
    extra: Mapping[str, Any] | None = None,
) -> pd.DataFrame:
    """
    DataIO-backed pull for Databento instrument definition events (schema="definition").

    This fetches the full event history for all instruments belonging to the
    Databento product root associated with `product_id` (e.g. ES.FUT),
    using stype_in="parent".

    The result is an append-only event stream suitable for reconstructing
    instrument state and building stable mappings.
    """
    product_root = get_databento_product_root(product_id)
    df = pull_timeseries(
        dataset=product_root.dataset,
        schema="definition",
        symbols=product_root.parent,
        stype_in=product_root.stype_in,
        start=start,
        end=end,
        source=source,
        extra=extra,
    )

    df = normalize_instrument_definitions(df)
    return df
