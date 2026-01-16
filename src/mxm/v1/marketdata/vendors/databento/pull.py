# src/mxm/v1/marketdata/databento/pull.py
from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

import pandas as pd
from mxm.dataio.api import CacheMode, DataIoSession
from mxm.dataio.models import Request, Response

from mxm.v1.marketdata.config.dataio import marketdata_dataio_cfg

SymbolsT = Union[str, Sequence[str]]


def _parquet_bytes_to_df(payload: bytes) -> pd.DataFrame:
    buf = BytesIO(payload)
    df = pd.read_parquet(buf)

    # Standardize: ensure ts_event is a column, not an index.
    if "ts_event" not in df.columns and getattr(df.index, "name", None) == "ts_event":
        df = df.reset_index()

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
    extra: Optional[Mapping[str, Any]] = None,
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
    extra: Optional[Mapping[str, Any]] = None,
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
        cache_mode=CacheMode.DEFAULT,
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
    extra: Optional[Mapping[str, Any]] = None,
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


def pull_instrument_definitions(
    *,
    dataset: str,
    symbols: SymbolsT,
    stype_in: str,
    start: str,
    end: str,
    source: str = "databento",
    extra: Optional[Mapping[str, Any]] = None,
) -> pd.DataFrame:
    """
    DataIO-backed pull for Databento instrument definition events (schema="definition").
    Thin wrapper around pull_timeseries_via_dataio(...).
    """
    return pull_timeseries(
        dataset=dataset,
        schema="definition",
        symbols=symbols,
        stype_in=stype_in,
        start=start,
        end=end,
        source=source,
        extra=extra,
    )
