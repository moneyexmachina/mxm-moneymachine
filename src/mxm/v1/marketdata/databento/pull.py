from __future__ import annotations

import databento as db
import pandas as pd


def pull_ohlcv_1d(
    *,
    client: db.Historical,
    dataset: str,
    symbol: str,
    stype_in: str = "raw_symbol",
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    Pull Databento `ohlcv-1d` daily bars for a single symbol over [start, end).

    Returns the raw dataframe as provided by Databento (still needs normalization).
    """
    df = client.timeseries.get_range(
        dataset=dataset,
        schema="ohlcv-1d",
        symbols=symbol,
        stype_in=stype_in,
        start=start,
        end=end,
    ).to_df()

    # Ensure ts_event is the index (Databento sometimes returns it as index already; we standardize later)
    return df
