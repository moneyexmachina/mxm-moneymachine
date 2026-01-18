# src/mxm/v1/marketdata/databento/timeseries_api_adapter.py
from __future__ import annotations

import time
from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict, Mapping, Optional, Sequence, Union, cast

import pandas as pd
from mxm.dataio.adapters import Fetcher
from mxm.dataio.models import AdapterResult, Request

SymbolsT = Union[str, Sequence[str]]


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


@dataclass(frozen=True)
class DatabentoTimeseriesParams:
    """
    Canonical parameter set for Databento timeseries.get_range(...) calls.

    This is intentionally a thin, stable envelope. All parameters here should be
    safe to include in a Request key for caching.
    """

    dataset: str
    schema: str
    symbols: SymbolsT
    start: str
    end: str
    stype_in: str = "raw_symbol"

    # Optional passthrough kwargs. Keep this small and explicit over time.
    extra: Optional[Mapping[str, Any]] = None

    def to_request_params(self) -> Dict[str, Any]:
        """
        Convert to a JSON-serializable dict suitable for mxm-dataio Request.params.

        Note: sequences are normalized to lists for stable hashing/serialization.
        """
        symbols: Any
        if isinstance(self.symbols, str):
            symbols = self.symbols
        else:
            symbols = list(self.symbols)

        params: Dict[str, Any] = {
            "dataset": self.dataset,
            "schema": self.schema,
            "symbols": symbols,
            "stype_in": self.stype_in,
            "start": self.start,
            "end": self.end,
        }
        if self.extra:
            # Make a shallow copy and ensure it is a plain dict for serialization.
            params["extra"] = dict(self.extra)
        return params


def pull_timeseries_df_raw(
    *,
    client: Any,
    dataset: str,
    schema: str,
    symbols: SymbolsT,
    stype_in: str,
    start: str,
    end: str,
    extra: Optional[Mapping[str, Any]] = None,
) -> pd.DataFrame:
    """
    Raw vendor call to Databento timeseries.get_range(...). Returns a DataFrame.

    This function is intentionally storage-agnostic. Caching and persistence are
    handled by the DataIO adapter layer.
    """
    kwargs: Dict[str, Any] = {}
    if extra:
        kwargs.update(dict(extra))
    t0 = time.time()
    resp = client.timeseries.get_range(
        dataset=dataset,
        schema=schema,
        symbols=symbols,
        stype_in=stype_in,
        start=start,
        end=end,
        **kwargs,
    )
    print(f"[databento] fetched stream in {time.time() - t0:.2f}s; converting to df...")
    t1 = time.time()
    df = resp.to_df()

    print(f"[databento] to_df() in {time.time() - t1:.2f}s; rows={len(df)}")
    return df


@dataclass(frozen=True)
class DatabentoTimeseriesFetcher(Fetcher):
    """
    Unified DataIO Fetcher for Databento timeseries.get_range(...) requests.

    Invoked ONLY on cache miss.

    Expected request.params:
      - dataset: str
      - schema: str
      - symbols: str | list[str]
      - stype_in: str
      - start: str
      - end: str
      - extra: dict[str, Any] (optional)
    """

    client: Any
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
        # Databento Historical client typically does not require explicit close.
        # Keep as a no-op for now.
        return

    def fetch(self, request: Request) -> AdapterResult:
        params: Dict[str, Any] = dict(request.params)

        dataset = cast(str, params["dataset"])
        schema = cast(str, params["schema"])
        symbols = params["symbols"]
        stype_in = cast(str, params.get("stype_in", "raw_symbol"))
        start = cast(str, params["start"])
        end = cast(str, params["end"])
        extra = cast(Optional[Dict[str, Any]], params.get("extra"))

        # Definitive proof of vendor call (cache miss)
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

        adapter_meta: Dict[str, Any] = {
            "vendor": "databento",
            "dataset": dataset,
            "schema": schema,
            "symbols": symbols,
            "stype_in": stype_in,
            "start": str(start),
            "end": str(end),
        }
        if extra:
            adapter_meta["extra"] = dict(extra)

        return AdapterResult(
            data=payload,
            content_type="application/x-parquet",
            transport_status=200,
            adapter_meta=adapter_meta,
        )
