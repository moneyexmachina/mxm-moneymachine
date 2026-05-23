from __future__ import annotations

import pandas as pd

from mxm.moneymachine.marketdata.schema.statistics_1d import coerce_statistics_1d

# ---------------------------------------------------------------------
# Bit masks for CME SettlPriceType (tag 731) as normalized by Databento
# into `stat_flags` for settlement (stat_type == 3).
# ---------------------------------------------------------------------

FINAL_MASK = 1 << 0  # 1
ACTUAL_MASK = 1 << 1  # 2
TRADING_TICK_MASK = 1 << 2  # 4
INTRADAY_MASK = 1 << 3  # 8
NULL_SET_MASK = 1 << 7  # 128

SETTLEMENT_STAT_TYPE = 3


def normalize_statistics_1d(
    df_raw: pd.DataFrame,
    *,
    dataset: str,
    raw_symbol: str | None = None,
) -> pd.DataFrame:
    """
    Normalize a Databento `statistics` (rtype=24) dataframe into MXM canonical schema.

    This dataset is an event stream of daily and session statistics.
    For daily statistics, CME provides a trading session date label (tag 5796),
    normalized by Databento to `ts_ref`. CME may publish multiple messages for
    the same (ts_ref, stat_type) as values progress from preliminary -> final.

    Normalization policy (V1):
    - Keep the full event stream (do not filter stat_type).
    - Ensure required identity and timestamp columns exist.
    - Derive a canonical `trading_date` column from `ts_ref` (UTC date).
    - Decode settlement `stat_flags` (tag 731) into boolean convenience fields
      for stat_type == 3. For other stat types, these fields are False.
    - Add dataset/schema metadata and enforce dtypes/column order via schema coercion.

    Notes:
    - We do not attempt to select a single “final” settlement per day here.
      That is a curated view concern, not raw normalization.
    - `ts_ref` is a date-precision trading session label normalized into a timestamp.
      Avoid localizing it to non-UTC timezones.
    """
    df = df_raw.copy()

    # Databento timeseries adapters sometimes set ts_event as index; make it explicit.
    if df.index.name == "ts_event":
        df = df.reset_index()

    # Handle symbol naming differences (match ohlcv convention).
    if "symbol" in df.columns and "raw_symbol" not in df.columns:
        df = df.rename(columns={"symbol": "raw_symbol"})

    if raw_symbol is not None:
        df["raw_symbol"] = raw_symbol

    # Required columns for the canonical raw event stream.
    # (Based on your observed df columns; keep this strict.)
    required = [
        "ts_recv",
        "ts_event",
        "ts_ref",
        "rtype",
        "publisher_id",
        "instrument_id",
        "stat_type",
        "channel_id",
        "update_action",
        "stat_flags",
        "sequence",
        "ts_in_delta",
        "price",
        "quantity",
        "raw_symbol",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(
            f"Databento raw df missing expected columns: {missing}. "
            f"Present columns: {list(df.columns)}"
        )

    # Keep only canonical columns (no silent extra columns).
    df = df.loc[:, required]

    # Sanity: statistics is rtype 24.
    # Keep it as a hard error to catch wrong schema pulls early.
    bad_rtypes = df.loc[df["rtype"] != 24, "rtype"].unique()
    if len(bad_rtypes) > 0:
        raise ValueError(
            f"Expected rtype==24 for statistics; saw rtype(s) {bad_rtypes}."
        )

    # Derive trading_date from ts_ref.
    # ts_ref is tz-aware datetime64[ns, UTC] in your observed df.
    df["trading_date"] = df[
        "ts_ref"
    ].dt.date  # object dtype (python date); schema coercion may refine

    # Settlement flag decoding (only meaningful for settlement stat_type == 3).
    is_settlement = df["stat_type"] == SETTLEMENT_STAT_TYPE

    # Default False for non-settlement stats.
    df["is_final"] = False
    df["is_actual"] = False
    df["is_trading_tick"] = False
    df["is_intraday"] = False
    df["is_null_set"] = False

    # Apply bit decoding to settlement rows only.
    # Use astype("uint16") defensively in case pandas treats small ints oddly.
    flags = df.loc[is_settlement, "stat_flags"].astype("uint16")

    df.loc[is_settlement, "is_final"] = (flags & FINAL_MASK) != 0
    df.loc[is_settlement, "is_actual"] = (flags & ACTUAL_MASK) != 0
    df.loc[is_settlement, "is_trading_tick"] = (flags & TRADING_TICK_MASK) != 0
    df.loc[is_settlement, "is_intraday"] = (flags & INTRADAY_MASK) != 0
    df.loc[is_settlement, "is_null_set"] = (flags & NULL_SET_MASK) != 0

    # Coerce/validate + add metadata + reorder
    return coerce_statistics_1d(
        df,
        dataset=dataset,
        schema="statistics",
        ensure_column_order=True,
    )
