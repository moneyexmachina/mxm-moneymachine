from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
from mxm.dataio.api import CacheMode, DataIoSession
from mxm.dataio.models import Request, Response

from mxm.v1.marketdata.dataio_config import marketdata_dataio_cfg


def _parquet_bytes_to_df(payload: bytes) -> pd.DataFrame:
    buf = BytesIO(payload)
    df = pd.read_parquet(buf)
    if "ts_event" not in df.columns and getattr(df.index, "name", None) == "ts_event":
        df = df.reset_index()

    return df


def _canonical_params(
    *,
    dataset: str,
    symbol: str,
    stype_in: str,
    start: str,
    end: str,
) -> dict[str, str]:
    return {
        "schema": "ohlcv-1d",
        "dataset": str(dataset),
        "symbol": str(symbol),
        "stype_in": str(stype_in),
        "start": str(start),
        "end": str(end),
    }


def _read_payload_bytes(resp: Response) -> bytes:
    if resp.path is None:
        raise RuntimeError("DataIO Response has no path; cannot read payload bytes.")
    return Path(resp.path).read_bytes()


def pull_ohlcv_1d_via_dataio(
    *,
    dataset: str,
    symbol: str,
    stype_in: str,
    start: str,
    end: str,
    source: str = "databento",
) -> pd.DataFrame:
    """
    DataIO-backed pull for Databento ohlcv-1d.

    Important: the adapter for `source` must already be registered in the global
    mxm.dataio registry (e.g. via mxm.dataio.registry.register()).
    """
    dio_cfg = marketdata_dataio_cfg()

    params = _canonical_params(
        dataset=dataset,
        symbol=symbol,
        stype_in=stype_in,
        start=start,
        end=end,
    )

    with DataIoSession(
        source=source,
        cfg=dio_cfg,
        cache_mode=CacheMode.DEFAULT,
        ttl=None,
        as_of_bucket=None,
        cache_tag=None,
    ) as io:
        req: Request = io.request(kind="databento.ohlcv-1d", params=params)
        resp: Response = io.fetch(req)

    print(f"[dataio] request_hash={req.hash} response_id={resp.id} path={resp.path}")

    payload = _read_payload_bytes(resp)
    return _parquet_bytes_to_df(payload)
