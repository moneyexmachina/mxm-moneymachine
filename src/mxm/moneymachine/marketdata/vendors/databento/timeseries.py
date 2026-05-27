from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from io import BytesIO
from typing import cast

import databento as db
import pandas as pd

from mxm.dataio.adapters import Fetcher
from mxm.dataio.models import AdapterResult, Request
from mxm.types import JSONMap, JSONObj, JSONValue

SymbolsT = str | Sequence[str]
# TODO(mxm-moneymachine):
# Add dedicated tests for databento.timeseries adapter semantics:
#
# - Request parameter normalization and validation:
#     - required params
#     - symbols parsing
#     - extra parsing
#     - invalid JSON surface rejection
#
# - Index materialization semantics:
#     - RangeIndex passthrough
#     - named Index preservation
#     - MultiIndex materialization
#     - duplicate column/index-name handling
#
# - Parquet roundtrip stability:
#     - dataframe -> parquet bytes -> dataframe
#     - timezone-aware timestamps
#     - nullable extension dtypes
#
# - Adapter metadata stability:
#     - deterministic adapter_meta structure
#     - symbols serialization consistency
#
# - Fetcher integration:
#     - cache-miss fetch path
#     - mock Databento client protocol
#     - payload generation invariants
#
# This module is infrastructure-critical because it forms the typed boundary
# between:
#     Request(JSON)
#         ->
#     vendor API invocation
#         ->
#     parquet cache persistence.
#
# Pyright cleanup significantly tightened these semantics; tests should now
# lock them in.


# TODO(mxm-v2):
# Consider extracting vendor raw-data acquisition into a dedicated package
# such as mxm-datakraken.
#
# Motivation:
# - make external vendor trust boundaries explicit
# - separate raw acquisition/caching from MXM semantic transformation
# - centralize Databento protocols, request models, payload metadata, checksums,
#   entitlement/range discovery, and vendor API drift tests
# - allow mxm-moneymachine to depend on captured/validated raw material rather than on
#   live vendor client surfaces directly
#
# Proposed layering:
#     vendor API
#         -> mxm-datakraken acquisition adapter
#         -> mxm-dataio cache/result substrate
#         -> mxm-moneymachine normalization and curated marketdata datasets
#
# Deferred during mxm-moneymachine publication cleanup to avoid scope expansion.


@dataclass(frozen=True)
class DatabentoTimeseriesParams:
    dataset: str
    schema: str
    symbols: SymbolsT
    start: str
    end: str
    stype_in: str = "raw_symbol"
    extra: JSONObj | None = None

    def to_request_params(self) -> JSONMap:
        symbols: JSONValue
        if isinstance(self.symbols, str):
            symbols = self.symbols
        else:
            symbols = list(self.symbols)

        params: JSONMap = {
            "dataset": self.dataset,
            "schema": self.schema,
            "symbols": symbols,
            "stype_in": self.stype_in,
            "start": self.start,
            "end": self.end,
        }

        if self.extra is not None:
            params["extra"] = dict(self.extra)

        return params


def _materialise_index(df: pd.DataFrame) -> pd.DataFrame:
    """
    Make the DataFrame index explicit as columns (single index or MultiIndex).

    Rationale: cached Parquet payloads should be self-contained and not depend on
    implicit index round-tripping.
    """
    # If it's already a trivial RangeIndex, nothing to do.
    if isinstance(df.index, pd.RangeIndex):
        return df

    # If it's a named single index and already present as a column, nothing to do.
    if not isinstance(df.index, pd.MultiIndex):
        idx_name = getattr(df.index, "name", None)
        if idx_name is not None and idx_name in df.columns:
            return df

    # MultiIndex: if all level names are already columns, nothing to do.
    if isinstance(df.index, pd.MultiIndex):
        names = [n for n in df.index.names if n is not None]
        if names and all(n in df.columns for n in names):
            return df

    return df.reset_index()


def _df_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    """
    Serialize a DataFrame to Parquet bytes for DataIO storage.
    """
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


def df_from_parquet_bytes(payload: bytes) -> pd.DataFrame:
    """
    Deserialize Parquet bytes (as written by this adapter) back into a DataFrame.
    """
    bio = BytesIO(payload)
    return pd.read_parquet(bio)


def _require_request_params(request: Request) -> JSONObj:
    params = request.params
    if params is None:
        raise ValueError("Databento timeseries request params are required")
    return params


def _require_str_param(params: JSONObj, key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError(f"Databento timeseries request param `{key}` must be str")
    return value


def _optional_str_param(
    params: JSONObj,
    key: str,
    *,
    default: str,
) -> str:
    value = params.get(key)
    if value is None:
        return default
    if not isinstance(value, str) or not value:
        raise ValueError(f"Databento timeseries request param `{key}` must be str")
    return value


def _optional_str_extra(extra: JSONObj | None, key: str) -> str | None:
    if extra is None:
        return None
    value = extra.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Databento extra `{key}` must be str")
    return value


def _optional_int_extra(extra: JSONObj | None, key: str) -> int | None:
    if extra is None:
        return None
    value = extra.get(key)
    if value is None:
        return None
    if not isinstance(value, int):
        raise ValueError(f"Databento extra `{key}` must be int")
    return value


def _require_symbols_param(params: JSONObj) -> SymbolsT:
    value = params.get("symbols")

    if isinstance(value, str):
        return value

    if isinstance(value, list) and all(isinstance(v, str) for v in value):
        return cast(list[str], value)

    raise ValueError(
        "Databento timeseries request param `symbols` must be str or list[str]"
    )


def _optional_extra_param(params: JSONObj) -> JSONObj | None:
    value = params.get("extra")

    if value is None:
        return None

    if not isinstance(value, dict):
        raise ValueError("Databento timeseries request param `extra` must be mapping")

    return value


def pull_timeseries_df_raw(
    *,
    client: db.Historical,
    dataset: str,
    schema: str,
    symbols: SymbolsT,
    stype_in: str,
    start: str,
    end: str,
    extra: JSONObj | None = None,
) -> pd.DataFrame:
    t0 = time.time()

    stype_out = _optional_str_extra(extra, "stype_out")
    limit = _optional_int_extra(extra, "limit")
    path = _optional_str_extra(extra, "path")

    if stype_out is not None and limit is not None and path is not None:
        resp = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            stype_out=stype_out,
            start=start,
            end=end,
            limit=limit,
            path=path,
        )
    elif stype_out is not None and limit is not None:
        resp = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            stype_out=stype_out,
            start=start,
            end=end,
            limit=limit,
        )
    elif stype_out is not None and path is not None:
        resp = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            stype_out=stype_out,
            start=start,
            end=end,
            path=path,
        )
    elif limit is not None and path is not None:
        resp = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            start=start,
            end=end,
            limit=limit,
            path=path,
        )
    elif stype_out is not None:
        resp = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            stype_out=stype_out,
            start=start,
            end=end,
        )
    elif limit is not None:
        resp = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            start=start,
            end=end,
            limit=limit,
        )
    elif path is not None:
        resp = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            start=start,
            end=end,
            path=path,
        )
    else:
        resp = client.timeseries.get_range(
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            start=start,
            end=end,
        )

    print(f"[databento] fetched stream in {time.time() - t0:.2f}s; converting to df...")

    t1 = time.time()
    df = resp.to_df()

    print(f"[databento] to_df() in {time.time() - t1:.2f}s; rows={len(df)}")
    return df


@dataclass(frozen=True)
class DatabentoTimeseriesFetcher(Fetcher):
    client: db.Historical
    source: str = "databento"

    def describe(self) -> str:
        return (
            "DatabentoTimeseriesFetcher("
            "vendor=databento, "
            "endpoint=timeseries.get_range, "
            "schemas=ohlcv-1d|definition, "
            "cache=dataio"
            ")"
        )

    def close(self) -> None:
        return

    def fetch(self, request: Request) -> AdapterResult:
        params = _require_request_params(request)

        dataset = _require_str_param(params, "dataset")
        schema = _require_str_param(params, "schema")
        symbols = _require_symbols_param(params)
        stype_in = _optional_str_param(params, "stype_in", default="raw_symbol")
        start = _require_str_param(params, "start")
        end = _require_str_param(params, "end")
        extra = _optional_extra_param(params)

        print(
            "[DATABENTO CALL] "
            f"dataset={dataset} schema={schema} symbols={symbols} "
            f"stype_in={stype_in} start={start} end={end}"
        )

        df = pull_timeseries_df_raw(
            client=self.client,
            dataset=dataset,
            schema=schema,
            symbols=symbols,
            stype_in=stype_in,
            start=start,
            end=end,
            extra=extra,
        )

        df = _materialise_index(df)
        payload = _df_to_parquet_bytes(df)

        adapter_meta: JSONMap = {
            "vendor": "databento",
            "dataset": dataset,
            "schema": schema,
            "symbols": symbols if isinstance(symbols, str) else list(symbols),
            "stype_in": stype_in,
            "start": start,
            "end": end,
        }

        if extra:
            adapter_meta["extra"] = dict(extra)

        return AdapterResult(
            data=payload,
            content_type="application/x-parquet",
            transport_status=200,
            adapter_meta=adapter_meta,
        )
