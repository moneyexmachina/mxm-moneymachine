"""
MXM V1 Marketdata — Canonical schema and validation for curated `daily_mark`.

Intent (Session 33):
- Freeze a minimal, opinionated schema for `daily_mark`.
- Represent one authoritative daily valuation mark per (contract_id, session),
  where `session` is an MXM business-session label.
- Keep source/quality/provenance explicit without overcommitting to a single
  upstream raw field layout.
- Validate loudly and early to prevent silent semantic drift.

Notes:
- `daily_mark` is a curated daily valuation surface keyed by
  (contract_id, session).
- `session` is an MXM business-session day label with day precision.
- Rows should exist for all sessions in the constructed business-session range.
- `mark_px` may be missing before the first valid markable observation.
- This schema is for storage / persisted columnar surfaces.
  Downstream API usage may expose a MultiIndex form on (session, contract_id).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

from mxm.v1.utils.date_utils import coerce_np_day
from mxm.v1.utils.hashing import sha256_df_content


@dataclass(frozen=True)
class DailyMarkSchema:
    """
    Canonical schema for MXM `daily_mark` surfaces.

    Contract between:
    - policy/build logic (`mxm.v1.marketdata.datasets.daily_mark.*`)
    - storage (parquet writer/reader for daily_mark)
    - dataset-level serving/inspection utilities

    Semantic intent:
    - one authoritative daily valuation mark per (contract_id, session)
    - `session` lives on the MXM business calendar
    - `mark_px` is the value downstream valuation/PnL systems should consume
    """

    # Canonical column order for persisted/served frames.
    columns: tuple[str, ...] = (
        "session",
        "contract_id",
        "instrument_id",
        "mark_px",
        "mark_source",
        "mark_quality",
        "is_markable",
        "is_carried",
        "carry_streak",
        "source_session",
        "source_dataset",
        "source_publisher_id",
        "source_raw_symbol",
    )

    # Required columns for a valid v1 daily_mark surface.
    required: tuple[str, ...] = (
        "session",
        "contract_id",
        "mark_px",
        "mark_source",
        "mark_quality",
        "is_markable",
        "is_carried",
        "carry_streak",
    )

    # Optional provenance/debug fields.
    optional: tuple[str, ...] = (
        "instrument_id",
        "source_session",
        "source_dataset",
        "source_publisher_id",
        "source_raw_symbol",
    )

    dtype_targets: dict[str, str] = None  # type: ignore[assignment]

    allowed_mark_sources: tuple[str, ...] = (
        "observed_settle",
        "observed_close",
        "carry_forward",
        "unavailable",
    )

    allowed_mark_qualities: tuple[str, ...] = (
        "final",
        "observed_fallback",
        "carried",
        "unavailable",
    )

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "dtype_targets",
            {
                "contract_id": "string",
                "instrument_id": "Int64",
                "mark_source": "string",
                "mark_quality": "string",
                "is_markable": "boolean",
                "is_carried": "boolean",
                "carry_streak": "int32",
                "source_dataset": "string",
                "source_publisher_id": "Int32",
                "source_raw_symbol": "string",
            },
        )


DAILY_MARK = DailyMarkSchema()


def _missing_columns(df: pd.DataFrame, required: Iterable[str]) -> list[str]:
    cols = set(df.columns)
    return [c for c in required if c not in cols]


def _coerce_day_label_series(s: pd.Series) -> pd.Series:
    """
    Coerce session-like values into canonical MXM day-label semantics.

    Contract:
      - dtype: pandas datetime64[ns] (timezone-naive)
      - invariant: all values are normalized to day precision (00:00:00)
      - semantic meaning: session day labels, equivalent to np.datetime64[D]
    """
    if s.empty:
        return pd.Series([], dtype="datetime64[ns]")

    values = [coerce_np_day(v) for v in s.to_list()]
    out = pd.to_datetime(pd.Series(values), errors="raise")
    out = out.dt.normalize()
    return out


def _validate_day_label_series(s: pd.Series, *, column_name: str) -> None:
    """
    Validate a pandas Series as an MXM day-label series.

    We store day labels in pandas datetime64[ns] form for practical dataframe /
    parquet interoperability, but semantically they must correspond to
    np.datetime64[D] labels.
    """
    if not pd.api.types.is_datetime64_any_dtype(s):
        raise ValueError(
            f"daily_mark `{column_name}` must be datetime dtype, got {s.dtype}"
        )

    if isinstance(s.dtype, pd.DatetimeTZDtype):
        raise ValueError(
            f"daily_mark `{column_name}` must be timezone-naive day labels, "
            f"got tz-aware dtype {s.dtype}"
        )

    if s.isna().any():
        raise ValueError(f"daily_mark `{column_name}` contains null values")

    midnight = (
        (s.dt.hour == 0)
        & (s.dt.minute == 0)
        & (s.dt.second == 0)
        & (s.dt.microsecond == 0)
        & (s.dt.nanosecond == 0)
    )
    if not bool(midnight.all()):
        raise ValueError(
            f"daily_mark `{column_name}` must be normalized to day labels (00:00:00)"
        )

    # Enforce day-label semantics by roundtripping through coerce_np_day.
    # This also protects against weird non-normalized object coercions sneaking in.
    try:
        roundtrip = np.array(
            [coerce_np_day(v) for v in s.to_numpy()], dtype="datetime64[D]"
        )
    except Exception as e:  # noqa: BLE001
        raise ValueError(
            f"daily_mark `{column_name}` contains values not coercible to "
            f"np.datetime64[D]: {e}"
        ) from e

    back = pd.to_datetime(pd.Series(roundtrip)).dt.normalize()
    if not s.reset_index(drop=True).equals(back.reset_index(drop=True)):
        raise ValueError(
            f"daily_mark `{column_name}` must represent canonical day labels "
            f"equivalent to np.datetime64[D]"
        )


def validate_daily_mark(df: pd.DataFrame) -> None:
    """
    Validate that `df` conforms to the canonical daily_mark surface schema.

    Contract (MXM V1)
    -----------------
    - `session` is an MXM business-session day label.
    - One row per (contract_id, session).
    - Surfaces are per-contract (contract_id constant within a file/surface).
    - `mark_px` may be null only when:
        - `mark_source='unavailable'`
        - `mark_quality='unavailable'`
        - `is_markable=False`

    Raises:
        ValueError: if the dataframe fails validation.
    """
    missing = _missing_columns(df, DAILY_MARK.required)
    if missing:
        raise ValueError(f"daily_mark dataframe missing required columns: {missing}")

    if "session" not in df.columns:
        raise ValueError("daily_mark missing session")
    _validate_day_label_series(df["session"], column_name="session")

    if "source_session" in df.columns:
        non_null = df["source_session"].dropna()
        if not non_null.empty:
            _validate_day_label_series(
                df.loc[non_null.index, "source_session"],
                column_name="source_session",
            )

    if df["contract_id"].isna().any():
        raise ValueError("daily_mark `contract_id` contains null values")

    if df.duplicated(subset=["contract_id", "session"]).any():
        raise ValueError("daily_mark contains duplicate (contract_id, session) rows")

    if df["contract_id"].nunique(dropna=False) != 1:
        raise ValueError("daily_mark surface must contain exactly one contract_id")

    if not df["session"].is_monotonic_increasing:
        raise ValueError("daily_mark `session` must be sorted increasing")

    if str(df["mark_source"].dtype) != "string":
        raise ValueError(
            f"daily_mark `mark_source` must be pandas string dtype, "
            f"got {df['mark_source'].dtype}"
        )

    if str(df["mark_quality"].dtype) != "string":
        raise ValueError(
            f"daily_mark `mark_quality` must be pandas string dtype, "
            f"got {df['mark_quality'].dtype}"
        )

    bad_sources = sorted(
        set(df["mark_source"].dropna()) - set(DAILY_MARK.allowed_mark_sources)
    )
    if bad_sources:
        raise ValueError(
            f"daily_mark `mark_source` contains invalid values: {bad_sources}"
        )

    bad_qualities = sorted(
        set(df["mark_quality"].dropna()) - set(DAILY_MARK.allowed_mark_qualities)
    )
    if bad_qualities:
        raise ValueError(
            f"daily_mark `mark_quality` contains invalid values: {bad_qualities}"
        )

    for col in ("is_markable", "is_carried"):
        if str(df[col].dtype) != "boolean":
            raise ValueError(
                f"daily_mark `{col}` must be pandas boolean dtype, got {df[col].dtype}"
            )

    if not pd.api.types.is_integer_dtype(df["carry_streak"]):
        raise ValueError(
            f"daily_mark `carry_streak` must be integer dtype, got {df['carry_streak'].dtype}"
        )

    if (df["carry_streak"] < 0).any():
        raise ValueError("daily_mark `carry_streak` must be non-negative")

    if not pd.api.types.is_numeric_dtype(df["mark_px"]):
        raise ValueError(
            f"daily_mark `mark_px` must be numeric, got {df['mark_px'].dtype}"
        )

    unavailable_mask = df["mark_source"] == "unavailable"

    mismatch_unavailable_quality = unavailable_mask != (
        df["mark_quality"] == "unavailable"
    )
    if bool(mismatch_unavailable_quality.any()):
        raise ValueError(
            "daily_mark inconsistent unavailable state: `mark_source` and "
            "`mark_quality` must agree on unavailable rows"
        )

    if bool(df.loc[unavailable_mask, "is_markable"].fillna(True).any()):
        raise ValueError("daily_mark unavailable rows must have `is_markable=False`")

    if bool(df.loc[unavailable_mask, "is_carried"].fillna(True).any()):
        raise ValueError("daily_mark unavailable rows must have `is_carried=False`")

    if bool((df.loc[unavailable_mask, "carry_streak"] != 0).any()):
        raise ValueError("daily_mark unavailable rows must have `carry_streak=0`")

    if bool(df.loc[unavailable_mask, "mark_px"].notna().any()):
        raise ValueError("daily_mark unavailable rows must have null `mark_px`")

    available_mask = ~unavailable_mask
    if bool(df.loc[available_mask, "mark_px"].isna().any()):
        raise ValueError("daily_mark available rows must have non-null `mark_px`")

    if bool((~df.loc[available_mask, "is_markable"].fillna(False)).any()):
        raise ValueError("daily_mark available rows must have `is_markable=True`")

    carried_mask = df["is_carried"] == True  # noqa: E712
    if bool((df.loc[carried_mask, "mark_source"] != "carry_forward").any()):
        raise ValueError(
            "daily_mark carried rows must have `mark_source='carry_forward'`"
        )

    if bool((df.loc[carried_mask, "mark_quality"] != "carried").any()):
        raise ValueError("daily_mark carried rows must have `mark_quality='carried'`")

    if bool((df.loc[carried_mask, "carry_streak"] <= 0).any()):
        raise ValueError("daily_mark carried rows must have `carry_streak > 0`")

    non_carried_available = available_mask & (~carried_mask)
    if bool((df.loc[non_carried_available, "carry_streak"] != 0).any()):
        raise ValueError(
            "daily_mark non-carried available rows must have `carry_streak=0`"
        )

    if "instrument_id" in df.columns:
        if not pd.api.types.is_integer_dtype(df["instrument_id"]):
            raise ValueError(
                f"daily_mark `instrument_id` must be integer dtype if present, "
                f"got {df['instrument_id'].dtype}"
            )

    if "source_publisher_id" in df.columns:
        if not pd.api.types.is_integer_dtype(df["source_publisher_id"]):
            raise ValueError(
                f"daily_mark `source_publisher_id` must be integer dtype if present, "
                f"got {df['source_publisher_id'].dtype}"
            )

    for col in ("source_dataset", "source_raw_symbol"):
        if col in df.columns and str(df[col].dtype) != "string":
            raise ValueError(
                f"daily_mark `{col}` must be pandas string dtype if present, "
                f"got {df[col].dtype}"
            )


def coerce_daily_mark(
    df: pd.DataFrame,
    *,
    ensure_column_order: bool = True,
) -> pd.DataFrame:
    """
    Coerce a dataframe into canonical daily_mark surface form.

    Intended use:
    - builder step constructs a per-contract business-session mark surface
    - this function finalizes dtypes, day-label semantics, and column ordering

    Returns:
        A new dataframe coerced into canonical form (copy).
    """
    out = df.copy()

    out["session"] = _coerce_day_label_series(out["session"])

    if "source_session" in out.columns:
        non_null = out["source_session"].notna()
        if bool(non_null.any()):
            out.loc[non_null, "source_session"] = _coerce_day_label_series(
                out.loc[non_null, "source_session"]
            )
        out["source_session"] = pd.to_datetime(
            out["source_session"], errors="coerce"
        ).dt.normalize()

    for col, dtype in DAILY_MARK.dtype_targets.items():
        if col not in out.columns:
            continue
        try:
            out[col] = out[col].astype(dtype)
        except Exception as e:  # noqa: BLE001
            raise ValueError(f"failed to coerce `{col}` to {dtype}: {e}") from e

    if "mark_px" in out.columns and not pd.api.types.is_numeric_dtype(out["mark_px"]):
        out["mark_px"] = pd.to_numeric(out["mark_px"], errors="raise")

    out = out.sort_values(["session"], kind="mergesort").reset_index(drop=True)

    if ensure_column_order:
        missing = _missing_columns(out, DAILY_MARK.required)
        if missing:
            raise ValueError(
                f"cannot coerce daily_mark: missing required columns: {missing}"
            )

        cols = [c for c in DAILY_MARK.columns if c in out.columns]
        out = out.loc[:, cols]

    validate_daily_mark(out)
    return out


def hash_daily_mark_content(df: pd.DataFrame) -> str:
    return sha256_df_content(df, coerce=coerce_daily_mark)
