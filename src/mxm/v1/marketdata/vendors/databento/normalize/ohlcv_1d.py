from __future__ import annotations

import pandas as pd

from mxm.v1.marketdata.schema import coerce_ohlcv_1d


def normalize_ohlcv_1d(
    df_raw: pd.DataFrame,
    *,
    dataset: str,
    raw_symbol: str | None = None,
) -> pd.DataFrame:
    """
    Normalize a Databento `ohlcv-1d` dataframe into MXM canonical schema.

    Databento typically returns:
    - index: ts_event (UTC midnight)
    - columns: open/high/low/close/volume plus identity fields (publisher_id, instrument_id, symbol)

    We standardize to:
    - explicit ts_event column
    - canonical names and ordering
    - enforced UTC tz-aware timestamps
    """
    df = df_raw.copy()

    # Databento often sets ts_event as index; make it an explicit column
    if df.index.name == "ts_event":
        df = df.reset_index()

    # Handle symbol naming differences
    if "symbol" in df.columns and "raw_symbol" not in df.columns:
        df = df.rename(columns={"symbol": "raw_symbol"})

    if raw_symbol is not None:
        df["raw_symbol"] = raw_symbol

    # Keep only what we need + ensure required columns exist
    keep_cols = [
        "ts_event",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "publisher_id",
        "instrument_id",
        "raw_symbol",
    ]
    missing = [c for c in keep_cols if c not in df.columns]
    if missing:
        raise ValueError(
            f"Databento raw df missing expected columns: {missing}. Present columns: {list(df.columns)}"
        )

    df = df.loc[:, keep_cols]

    # Add dataset/schema + coerce/validate + reorder
    return coerce_ohlcv_1d(
        df, dataset=dataset, schema="ohlcv-1d", ensure_column_order=True
    )
