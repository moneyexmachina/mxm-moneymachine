"""
MXM V1 Marketdata — Canonical schemas and validation.

Session 4 intent:
- Freeze a minimal, opinionated schema for Databento `ohlcv-1d` daily bars.
- Validate loudly and early to prevent silent drift.
- Keep this module lightweight (no third-party schema frameworks).

Notes:
- We treat `ts_event` as the canonical bar timestamp label provided by Databento.
- All timestamps must be timezone-aware UTC.
- We do not over-constrain price/volume dtypes in Session 4; we only require they are numeric.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import pandas as pd

from mxm.v1.utils.time_utils import ensure_utc_datetime_series


@dataclass(frozen=True)
class Ohlcv1dSchema:
    """
    Canonical schema for daily OHLCV bars (`ohlcv-1d`) used within MXM V1.

    This schema is the contract between:
    - vendor normalization (`mxm.v1.marketdata.vendors.databento.normalize.ohlcv_1d`)
    - storage (`mxm.v1.marketdata.stores.parquet.daily_bars`)
    - serving API (`mxm.v1.marketdata.datasets.ohlcv_1d.api`)
    """

    # Canonical column order for persisted/served frames
    columns: tuple[str, ...] = (
        "ts_event",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "dataset",
        "schema",
        "publisher_id",
        "instrument_id",
        "raw_symbol",
    )

    # Required columns (for validation). Same as columns for now, but kept separate for future flexibility.
    required: tuple[str, ...] = columns

    # Dtype targets for identity/provenance fields.
    # Prices and volume are validated as numeric but not forcibly downcast.
    dtype_targets: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dtype_targets",
            {
                "dataset": "string",
                "schema": "string",
                "publisher_id": "int32",
                "instrument_id": "int64",
                "raw_symbol": "string",
            },
        )


OHLCV_1D = Ohlcv1dSchema()


def _missing_columns(df: pd.DataFrame, required: Iterable[str]) -> list[str]:
    cols = set(df.columns)
    return [c for c in required if c not in cols]


def validate_ohlcv_1d(df: pd.DataFrame) -> None:
    """
    Validate that `df` conforms to the MXM canonical daily bar schema.

    Raises:
        ValueError: if the dataframe fails validation.
    """
    if df is None:
        raise ValueError("ohlcv-1d dataframe is None")

    missing = _missing_columns(df, OHLCV_1D.required)
    if missing:
        raise ValueError(f"ohlcv-1d dataframe missing required columns: {missing}")

    # ts_event must be datetime64 and tz-aware UTC
    ts = df["ts_event"]
    if not pd.api.types.is_datetime64_any_dtype(ts):
        raise ValueError(f"ohlcv-1d `ts_event` must be datetime dtype, got {ts.dtype}")

    # Pandas stores tz-aware as DatetimeTZDtype
    if not isinstance(ts.dtype, pd.DatetimeTZDtype):
        raise ValueError(
            "ohlcv-1d `ts_event` must be timezone-aware (UTC). "
            "If you have naive timestamps, localize them to UTC."
        )

    if str(ts.dtype.tz) != "UTC":
        raise ValueError(f"ohlcv-1d `ts_event` must be UTC, got tz={ts.dtype.tz}")

    # Identity fields must be non-null and stable types
    for col in ("publisher_id", "instrument_id", "raw_symbol", "dataset", "schema"):
        if df[col].isna().any():
            raise ValueError(f"ohlcv-1d `{col}` contains null values")

    # Numeric constraints (lightweight)
    for col in ("open", "high", "low", "close", "volume"):
        if not pd.api.types.is_numeric_dtype(df[col]):
            raise ValueError(f"ohlcv-1d `{col}` must be numeric, got {df[col].dtype}")

    # Sane OHLC inequalities (warn-level elsewhere; hard error is too strict for MVP)
    # We do not enforce this here to avoid blocking on vendor quirks.
    # If you want a hard check later, introduce validate_ohlcv_sanity(strict: bool).

    # If we got here, schema is acceptable.


def coerce_ohlcv_1d(
    df: pd.DataFrame,
    *,
    dataset: str | None = None,
    schema: str = "ohlcv-1d",
    ensure_column_order: bool = True,
) -> pd.DataFrame:
    """
    Coerce a dataframe into canonical `ohlcv-1d` form.

    Intended use:
    - vendor normalization step creates/renames fields
    - this function finalizes dtypes, utc timestamps, and column ordering

    Args:
        df: dataframe that already contains the required columns (or will after light coercion)
        dataset: if provided, set/override `dataset` column
        schema: set/override `schema` column (defaults to `ohlcv-1d`)
        ensure_column_order: reorder columns to canonical order if True

    Returns:
        A new dataframe coerced into canonical form (copy).
    """
    if df is None:
        raise ValueError("cannot coerce: df is None")

    out = df.copy()

    # Ensure ts_event is tz-aware UTC
    # If already tz-aware, convert; if naive, localize.
    out["ts_event"] = ensure_utc_datetime_series(out["ts_event"])

    if dataset is not None:
        out["dataset"] = dataset
    out["schema"] = schema

    # Coerce identity/provenance dtypes
    for col, dtype in OHLCV_1D.dtype_targets.items():
        if col not in out.columns:
            continue
        try:
            out[col] = out[col].astype(dtype)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"failed to coerce `{col}` to {dtype}: {e}") from e

    # Keep numeric columns numeric (do not force float/int, just ensure parseable)
    for col in ("open", "high", "low", "close", "volume"):
        if col in out.columns and not pd.api.types.is_numeric_dtype(out[col]):
            out[col] = pd.to_numeric(out[col], errors="raise")

    if ensure_column_order:
        # Ensure required columns exist before reordering to avoid KeyError surprises.
        missing = _missing_columns(out, OHLCV_1D.required)
        if missing:
            raise ValueError(f"cannot coerce: missing required columns: {missing}")
        out = out.loc[:, list(OHLCV_1D.columns)]

    # Final validation (loud fail if something is off)
    validate_ohlcv_1d(out)

    return out
