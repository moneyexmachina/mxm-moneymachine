"""
MXM V1 Marketdata — Canonical schema and validation for derived `daily_stats`.

Intent (Session 22e):
- Freeze a minimal, opinionated schema for `daily_stats`, derived from `statistics_1d`.
- Validate loudly and early to prevent silent drift.
- Keep this module lightweight (no third-party schema frameworks).

Notes:
- `daily_stats` is a derived daily surface keyed by (instrument_id, session_date).
- `session_date` is a trading session label with day precision (datetime64[D]).
- Missing values are allowed for value columns (outer-join semantics).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd

from mxm.v1.utils.hashing import sha256_df_content


@dataclass(frozen=True)
class DailyStatsSchema:
    """
    Canonical schema for MXM `daily_stats` surfaces (derived, one row per session date).

    Contract between:
    - selection/derivation (`mxm.v1.marketdata.datasets.daily_stats.selection`)
    - storage (parquet writer/reader for daily_stats)
    - dataset-level serving/inspection utilities
    """

    # Canonical column order for persisted/served frames.
    # Identity columns are constant per instrument surface, but kept for self-description.
    columns: tuple[str, ...] = (
        "session_date",
        "instrument_id",
        "publisher_id",
        "dataset",
        "raw_symbol",
        "settle_px",
        "settle_px_is_final",
        "fix_px",
        "fix_px_is_final",
        "open_px",
        "high_px",
        "low_px",
        "open_interest_qty",
        "cleared_volume_qty",
    )

    # Required columns. We keep `raw_symbol` optional because selection passes it through
    # only if present in the input statistics frame.
    required: tuple[str, ...] = (
        "session_date",
        "instrument_id",
        "publisher_id",
        "dataset",
        # raw_symbol optional
        "settle_px",
        "settle_px_is_final",
        "fix_px",
        "fix_px_is_final",
        "open_px",
        "high_px",
        "low_px",
        "open_interest_qty",
        "cleared_volume_qty",
    )

    optional: tuple[str, ...] = ("raw_symbol",)

    dtype_targets: dict[str, str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dtype_targets",
            {
                "dataset": "string",
                "publisher_id": "int32",
                "instrument_id": "int64",
                "raw_symbol": "string",
                "settle_px_is_final": "boolean",
                "fix_px_is_final": "boolean",
            },
        )


DAILY_STATS = DailyStatsSchema()


def _missing_columns(df: pd.DataFrame, required: Iterable[str]) -> list[str]:
    cols = set(df.columns)
    return [c for c in required if c not in cols]


def _coerce_session_date_series(s: pd.Series) -> pd.Series:
    """
    Coerce session_date-like values into tz-aware UTC midnight timestamps.

    Contract:
      - dtype: datetime64[ns, UTC]
      - invariant: all values are UTC-midnight aligned
    """
    if s.empty:
        return pd.Series([], dtype="datetime64[ns, UTC]")

    dt = pd.to_datetime(s, errors="coerce", utc=True)
    out = dt.dt.normalize()  # UTC midnight
    return out


def validate_daily_stats(df: pd.DataFrame) -> None:
    """
    Validate that `df` conforms to the canonical daily_stats surface schema.

    Contract (MXM V1)
    -----------------
    - session_date is a *day label* represented as a tz-aware UTC timestamp
      aligned to UTC midnight (00:00:00Z).
    - One row per (instrument_id, session_date).
    - Surfaces are per-instrument (instrument_id constant within a file/surface).

    Raises:
        ValueError: if the dataframe fails validation.
    """
    missing = _missing_columns(df, DAILY_STATS.required)
    if missing:
        raise ValueError(f"daily_stats dataframe missing required columns: {missing}")

    # session_date must be datetime64[ns, UTC] and UTC-midnight aligned
    if "session_date" not in df.columns:
        raise ValueError("daily_stats missing session_date")

    s = df["session_date"]
    if not pd.api.types.is_datetime64_any_dtype(s):
        raise ValueError(
            f"daily_stats `session_date` must be datetime dtype, got {s.dtype}"
        )
    if not isinstance(s.dtype, pd.DatetimeTZDtype):
        raise ValueError(
            "daily_stats `session_date` must be tz-aware UTC (datetime64[ns, UTC])"
        )
    if str(s.dtype.tz) != "UTC":
        raise ValueError(f"daily_stats `session_date` must be UTC, got tz={s.dtype.tz}")

    if s.isna().any():
        raise ValueError("daily_stats `session_date` contains null values")

    # Require UTC-midnight alignment (day-label semantics)
    midnight = (
        (s.dt.hour == 0)
        & (s.dt.minute == 0)
        & (s.dt.second == 0)
        & (s.dt.microsecond == 0)
    )
    if not bool(midnight.all()):
        raise ValueError(
            "daily_stats `session_date` must be UTC-midnight aligned (00:00:00Z)"
        )

    # Identity/provenance must be non-null
    for col in ("instrument_id", "publisher_id", "dataset"):
        if df[col].isna().any():
            raise ValueError(f"daily_stats `{col}` contains null values")

    # raw_symbol: optional column, but if present it must be non-null
    if "raw_symbol" in df.columns and df["raw_symbol"].isna().any():
        raise ValueError("daily_stats `raw_symbol` contains null values")

    # One row per (instrument_id, session_date)
    if df.duplicated(subset=["instrument_id", "session_date"]).any():
        raise ValueError(
            "daily_stats contains duplicate (instrument_id, session_date) rows"
        )

    # Per-instrument surface invariant
    if df["instrument_id"].nunique(dropna=False) != 1:
        raise ValueError("daily_stats surface must contain exactly one instrument_id")

    # Sorted by session_date
    if not df["session_date"].is_monotonic_increasing:
        raise ValueError("daily_stats `session_date` must be sorted increasing")

    # Booleans (nullable allowed)
    for col in ("settle_px_is_final", "fix_px_is_final"):
        if col in df.columns and str(df[col].dtype) != "boolean":
            raise ValueError(
                f"daily_stats `{col}` must be pandas boolean dtype, got {df[col].dtype}"
            )

    # Numeric constraints (lightweight): allow NaNs, but must be numeric dtype if present
    for col in (
        "settle_px",
        "fix_px",
        "open_px",
        "high_px",
        "low_px",
        "open_interest_qty",
        "cleared_volume_qty",
    ):
        if col in df.columns and not pd.api.types.is_numeric_dtype(df[col]):
            raise ValueError(
                f"daily_stats `{col}` must be numeric, got {df[col].dtype}"
            )


def coerce_daily_stats(
    df: pd.DataFrame,
    *,
    ensure_column_order: bool = True,
) -> pd.DataFrame:
    """
    Coerce a dataframe into canonical daily_stats surface form.

    Intended use:
    - selection step produces an outer-joined daily surface
    - this function finalizes dtypes, session_date precision, and column ordering

    Returns:
        A new dataframe coerced into canonical form (copy).
    """
    out = df.copy()

    # session_date -> datetime64[D]
    out["session_date"] = _coerce_session_date_series(out["session_date"])

    # Coerce identity/provenance and boolean dtypes where applicable
    for col, dtype in DAILY_STATS.dtype_targets.items():
        if col not in out.columns:
            continue
        try:
            out[col] = out[col].astype(dtype)
        except Exception as e:
            raise ValueError(f"failed to coerce `{col}` to {dtype}: {e}") from e

    # Keep numeric columns numeric (do not force float/int, just ensure parseable)
    for col in (
        "settle_px",
        "fix_px",
        "open_px",
        "high_px",
        "low_px",
        "open_interest_qty",
        "cleared_volume_qty",
    ):
        if col in out.columns and not pd.api.types.is_numeric_dtype(out[col]):
            out[col] = pd.to_numeric(out[col], errors="raise")

    # Canonical sort
    out = out.sort_values(["session_date"], kind="mergesort").reset_index(drop=True)

    if ensure_column_order:
        # We only require the required columns; optional ones may be absent.
        missing = _missing_columns(out, DAILY_STATS.required)
        if missing:
            raise ValueError(
                f"cannot coerce daily_stats: missing required columns: {missing}"
            )

        # Keep canonical order, dropping optional columns not present.
        cols = [c for c in DAILY_STATS.columns if c in out.columns]
        out = out.loc[:, cols]

    # Final validation
    validate_daily_stats(out)

    return out


def hash_daily_stats_content(df: pd.DataFrame) -> str:
    return sha256_df_content(df, coerce=coerce_daily_stats)
