from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Any, Dict

import pandas as pd
from mxm.dataio.adapters import Fetcher
from mxm.dataio.models import AdapterResult, Request


def _ensure_ts_event_column(df: pd.DataFrame) -> pd.DataFrame:
    if "ts_event" in df.columns:
        return df
    if getattr(df.index, "name", None) == "ts_event":
        return df.reset_index()
    return df


def _df_to_parquet_bytes(df: pd.DataFrame) -> bytes:
    """
    Serialize a DataFrame to Parquet bytes for DataIO storage.
    """
    buf = BytesIO()
    df.to_parquet(buf, index=False)
    return buf.getvalue()


@dataclass(frozen=True)
class DatabentoOhlcv1dFetcher(Fetcher):
    """
    DataIO Fetcher for Databento ohlcv-1d requests.

    Invoked ONLY on cache miss.
    """

    client: Any
    source: str = "databento"

    def fetch(self, request: Request) -> AdapterResult:
        params: Dict[str, Any] = dict(request.params)

        dataset = params["dataset"]
        symbol = params["symbol"]
        stype_in = params["stype_in"]
        start = params["start"]
        end = params["end"]

        # Definitive proof of vendor call
        print(
            "[DATABENTO CALL] "
            f"dataset={dataset} symbol={symbol} "
            f"stype_in={stype_in} start={start} end={end}"
        )

        # Reuse the Session-4-proven pull implementation
        from mxm.v1.marketdata.databento.pull import pull_ohlcv_1d

        df = pull_ohlcv_1d(
            client=self.client,
            dataset=dataset,
            symbol=symbol,
            stype_in=stype_in,
            start=start,
            end=end,
        )
        print(
            "ts_event in columns?",
            "ts_event" in df.columns,
            "index.name=",
            df.index.name,
        )
        df = _ensure_ts_event_column(df)
        payload = _df_to_parquet_bytes(df)

        return AdapterResult(
            data=payload,
            content_type="application/x-parquet",
            transport_status=200,
            adapter_meta={
                "vendor": "databento",
                "schema": "ohlcv-1d",
                "dataset": dataset,
                "symbol": symbol,
                "stype_in": stype_in,
                "start": str(start),
                "end": str(end),
            },
        )
