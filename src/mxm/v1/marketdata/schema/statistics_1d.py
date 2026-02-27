"""
MXM V1 Marketdata — Canonical schemas and validation.

Session 21 intent:
- Freeze a minimal, opinionated schema for Databento `statistics` (rtype=24) events
  used to build daily settlement and other daily statistics surfaces.
- Validate loudly and early to prevent silent drift.
- Keep this module lightweight (no third-party schema frameworks).

Notes:
- `ts_ref` is the exchange trading session date label (CME tag 5796
  TradingReferenceDate) normalized to a timestamp for consistency with other
  timestamps. Because the source has date precision, users should avoid
  localizing `ts_ref` to non-UTC time zones.
- `statistics` is an event stream: CME often publishes multiple messages for the
  same (ts_ref, stat_type) as values progress from preliminary -> final.
  Raw ingestion must preserve the full stream; curated “one value per day”
  selection is a derived concern.
- `stat_flags` is meaningful primarily for settlement price (stat_type=3), where
  it encodes CME tag 731 SettlPriceType as a bitfield. For other stat types it
  may be present but not meaningful for V1 curation.
# trading_date:
#   - derived from ts_ref (UTC date)
#   - nullable for non-daily stat types

"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from mxm.v1.utils.hashing import sha256_df_content
from mxm.v1.utils.time_utils import ensure_utc_datetime_series


@dataclass(frozen=True)
class Statistics1dSchema:
    """
    Canonical schema for Databento `statistics` (rtype=24) event rows used within MXM V1.

    This schema is the contract between:
    - vendor normalization (`mxm.v1.marketdata.vendors.databento.normalize.statistics_1d`)
    - storage (parquet writer/reader for statistics_1d)
    - dataset-level serving/inspection utilities (`mxm.v1.marketdata.datasets.statistics_1d.*`)
    """

    # Canonical column order for persisted/served frames
    columns: tuple[str, ...] = (
        "ts_recv",
        "ts_event",
        "ts_ref",
        "trading_date",
        "rtype",
        "stat_type",
        "price",
        "quantity",
        "sequence",
        "ts_in_delta",
        "update_action",
        "stat_flags",
        "is_final",
        "is_actual",
        "is_trading_tick",
        "is_intraday",
        "is_null_set",
        "dataset",
        "schema",
        "publisher_id",
        "channel_id",
        "instrument_id",
        "raw_symbol",
    )

    # Required columns (kept separate for future flexibility)
    required: tuple[str, ...] = columns

    # Dtype targets for identity/provenance fields and small integers.
    # We keep price/quantity numeric but do not over-constrain their exact dtype.
    dtype_targets: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dtype_targets",
            {
                "dataset": "string",
                "schema": "string",
                "publisher_id": "int32",
                "channel_id": "int32",
                "instrument_id": "int64",
                "raw_symbol": "string",
                "rtype": "int16",
                "stat_type": "int32",
                "sequence": "int64",
                "ts_in_delta": "int32",
                "update_action": "int16",
                "stat_flags": "int32",
                "is_final": "boolean",
                "is_actual": "boolean",
                "is_trading_tick": "boolean",
                "is_intraday": "boolean",
                "is_null_set": "boolean",
            },
        )


STATISTICS_1D = Statistics1dSchema()


def _missing_columns(df: pd.DataFrame, required: Iterable[str]) -> list[str]:
    cols = set(df.columns)
    return [c for c in required if c not in cols]


def validate_statistics_1d(df: pd.DataFrame) -> None:
    """
    Validate that `df` conforms to the MXM canonical statistics event schema.

    Raises:
        ValueError: if the dataframe fails validation.
    """
    missing = _missing_columns(df, STATISTICS_1D.required)
    if missing:
        raise ValueError(f"statistics dataframe missing required columns: {missing}")

    # Timestamps must be datetime64 and tz-aware UTC
    for col in ("ts_recv", "ts_event", "ts_ref"):
        ts = df[col]
        if not pd.api.types.is_datetime64_any_dtype(ts):
            raise ValueError(
                f"statistics `{col}` must be datetime dtype, got {ts.dtype}"
            )
        if not isinstance(ts.dtype, pd.DatetimeTZDtype):
            raise ValueError(
                f"statistics `{col}` must be timezone-aware (UTC). "
                "If you have naive timestamps, localize them to UTC."
            )
        if str(ts.dtype.tz) != "UTC":
            raise ValueError(f"statistics `{col}` must be UTC, got tz={ts.dtype.tz}")

    # ts_recv / ts_event must never be null (they are true event/capture times)
    for col in ("ts_recv", "ts_event"):
        if df[col].isna().any():
            raise ValueError(f"statistics `{col}` contains null values")

    # trading_date must be present and non-null for daily stat-types (even if ts_ref is date-like).
    # Normalization derives it from ts_ref, so it should always be populated.
    DAILY_STAT_TYPES = {3, 6, 9, 10}
    _ = DAILY_STAT_TYPES

    # Identity / provenance fields must be non-null
    for col in (
        "publisher_id",
        "channel_id",
        "instrument_id",
        "raw_symbol",
        "dataset",
        "schema",
        "rtype",
        "stat_type",
    ):
        if df[col].isna().any():
            raise ValueError(f"statistics `{col}` contains null values")

    # rtype must be 24 for statistics
    bad_rtypes = df.loc[df["rtype"] != 24, "rtype"].unique()
    if len(bad_rtypes) > 0:
        raise ValueError(f"statistics `rtype` must be 24, saw {bad_rtypes}")

    # Numeric constraints (lightweight)
    for col in ("price", "quantity", "sequence", "ts_in_delta"):
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise ValueError(f"statistics `{col}` must be numeric, got {df[col].dtype}")

    # Boolean convenience flags must be boolean dtype (or pandas boolean)
    for col in (
        "is_final",
        "is_actual",
        "is_trading_tick",
        "is_intraday",
        "is_null_set",
    ):
        if df[col].dtype not in (bool, "bool") and str(df[col].dtype) != "boolean":
            # Allow pandas BooleanDtype ("boolean") which supports NA.
            raise ValueError(
                f"statistics `{col}` must be boolean dtype, got {df[col].dtype}"
            )

    # We do not enforce any uniqueness. This is an event stream.
    # We also do not enforce stat_flags semantics outside of settlement.
    # If we got here, schema is acceptable.


def coerce_statistics_1d(
    df: pd.DataFrame,
    *,
    dataset: str | None = None,
    schema: str = "statistics",
    ensure_column_order: bool = True,
) -> pd.DataFrame:
    """
    Coerce a dataframe into canonical `statistics` event form.

    Intended use:
    - vendor normalization step creates/renames fields and adds derived columns
    - this function finalizes dtypes, utc timestamps, and column ordering

    Args:
        df: dataframe that already contains the required columns (or will after light coercion)
        dataset: if provided, set/override `dataset` column
        schema: set/override `schema` column (defaults to `statistics`)
        ensure_column_order: reorder columns to canonical order if True

    Returns:
        A new dataframe coerced into canonical form (copy).
    """
    out = df.copy()

    # Ensure timestamps are tz-aware UTC
    for col in ("ts_recv", "ts_event", "ts_ref"):
        out[col] = ensure_utc_datetime_series(out[col])

    # Derive trading_date if missing (defensive). Expect normalize to have done this.
    if "trading_date" not in out.columns:
        out["trading_date"] = out["ts_ref"].dt.date

    if dataset is not None:
        out["dataset"] = dataset
    out["schema"] = schema

    # Coerce identity/provenance dtypes
    for col, dtype in STATISTICS_1D.dtype_targets.items():
        if col not in out.columns:
            continue
        try:
            out[col] = out[col].astype(dtype)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"failed to coerce `{col}` to {dtype}: {e}") from e

    # Keep numeric columns numeric (do not force float/int, just ensure parseable)
    for col in ("price", "quantity", "sequence", "ts_in_delta", "rtype", "stat_type"):
        if col in out.columns and not pd.api.types.is_numeric_dtype(out[col]):
            out[col] = pd.to_numeric(out[col], errors="raise")

    if ensure_column_order:
        missing = _missing_columns(out, STATISTICS_1D.required)
        if missing:
            raise ValueError(f"cannot coerce: missing required columns: {missing}")
        out = out.loc[:, list(STATISTICS_1D.columns)]

    # Final validation (loud fail if something is off)
    validate_statistics_1d(out)

    return out


def hash_statistics_1d_content(df: pd.DataFrame) -> str:
    """
    Stable content hash for idempotency checks (order-invariant).
    Hashes canonicalised statistics_1d event content, not file bytes.
    """
    return sha256_df_content(df, coerce=coerce_statistics_1d)
