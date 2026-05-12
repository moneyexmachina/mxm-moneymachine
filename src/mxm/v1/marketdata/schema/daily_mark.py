"""
MXM V1 Marketdata — Canonical schema and validation for curated `daily_mark`.

Intent (Session 33)
-------------------
- Freeze a minimal, opinionated schema for `daily_mark`.
- Represent one authoritative daily valuation mark per
  (contract_id, session_id), where `session_id` is an MXM business-session
  coordinate in a specific MXM business calendar.
- Keep source / quality / provenance explicit without overcommitting to a
  single upstream raw field layout.
- Validate loudly and early to prevent silent semantic drift.

Notes
-----
- `daily_mark` is a curated daily valuation surface keyed by
  (contract_id, session_id).
- `session_id` is the primary business-time coordinate in MXM.
- `calendar_id` is part of dataset identity and is expected to be carried in
  path / metadata, not as a parquet row column in v1.
- Rows should exist for all session_ids in the constructed business-session range.
- `mark_px` may be missing before the first valid markable observation.
- This schema is for storage / persisted columnar surfaces.
  Downstream API usage may expose alternative indexed views as needed.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

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
    - dataset-level serving / inspection utilities

    Semantic intent:
    - one authoritative daily valuation mark per (contract_id, session_id)
    - `session_id` is the primary MXM business-time coordinate
    - `mark_px` is the value downstream valuation / PnL systems should consume
    """

    # Canonical column order for persisted / served frames.
    columns: tuple[str, ...] = (
        "session_id",
        "contract_id",
        "instrument_id",
        "mark_px",
        "mark_source",
        "mark_quality",
        "is_markable",
        "is_carried",
        "carry_streak",
        "source_trading_date",
        "source_dataset",
        "source_publisher_id",
        "source_raw_symbol",
    )

    # Required columns for a valid v1 daily_mark surface.
    required: tuple[str, ...] = (
        "session_id",
        "contract_id",
        "mark_px",
        "mark_source",
        "mark_quality",
        "is_markable",
        "is_carried",
        "carry_streak",
    )

    # Optional provenance / debug fields.
    optional: tuple[str, ...] = (
        "instrument_id",
        "source_trading_date",
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
                "session_id": "int32",
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
    Coerce date-like values into canonical day-label storage form.

    Contract:
      - dtype: pandas datetime64[ns] (timezone-naive)
      - invariant: all values are normalized to day precision (00:00:00)
      - semantic meaning: a day-label field equivalent to np.datetime64[D]

    This helper is intended for source-side provenance fields such as
    `source_trading_date`. It is not used for MXM business-session identity,
    which is carried by `session_id`.
    """
    if s.empty:
        return pd.Series([], index=s.index, dtype="datetime64[ns]", name=s.name)

    values = np.array([coerce_np_day(v) for v in s.to_list()], dtype="datetime64[D]")
    out = pd.Series(
        pd.to_datetime(values, errors="raise"),
        index=s.index,
        name=s.name,
    )
    out = out.dt.normalize()
    return out


def _validate_day_label_series(s: pd.Series, *, column_name: str) -> None:
    """
    Validate a pandas Series as a canonical day-label series.

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

    try:
        roundtrip = np.array(
            [coerce_np_day(v) for v in s.to_numpy()],
            dtype="datetime64[D]",
        )
    except Exception as e:
        raise ValueError(
            f"daily_mark `{column_name}` contains values not coercible to "
            f"np.datetime64[D]: {e}"
        ) from e

    back = pd.Series(
        pd.to_datetime(roundtrip),
        index=s.index,
        name=s.name,
    ).dt.normalize()

    if not np.array_equal(
        s.to_numpy(dtype="datetime64[ns]"),
        back.to_numpy(dtype="datetime64[ns]"),
    ):
        raise ValueError(
            f"daily_mark `{column_name}` must represent canonical day labels "
            f"equivalent to np.datetime64[D]"
        )


def validate_daily_mark(df: pd.DataFrame) -> None:
    """
    Validate that `df` conforms to the canonical daily_mark surface schema.

    Contract (MXM V1)
    -----------------
    - `session_id` is the primary MXM business-session coordinate.
    - One row per (contract_id, session_id).
    - Surfaces are per-contract (contract_id constant within a file / surface).
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

    if df["session_id"].isna().any():
        raise ValueError("daily_mark `session_id` contains null values")

    if not pd.api.types.is_integer_dtype(df["session_id"]):
        raise ValueError(
            f"daily_mark `session_id` must be integer dtype, got {df['session_id'].dtype}"
        )

    if (df["session_id"] < 0).any():
        raise ValueError("daily_mark `session_id` must be non-negative")

    if df["contract_id"].isna().any():
        raise ValueError("daily_mark `contract_id` contains null values")

    if df.duplicated(subset=["contract_id", "session_id"]).any():
        raise ValueError("daily_mark contains duplicate (contract_id, session_id) rows")

    if df["contract_id"].nunique(dropna=False) != 1:
        raise ValueError("daily_mark surface must contain exactly one contract_id")

    if not df["session_id"].is_monotonic_increasing:
        raise ValueError("daily_mark `session_id` must be sorted increasing")

    if "source_trading_date" in df.columns:
        non_null = df["source_trading_date"].dropna()
        if not non_null.empty:
            _validate_day_label_series(
                df.loc[non_null.index, "source_trading_date"],
                column_name="source_trading_date",
            )

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
    - this function finalizes dtypes, provenance day-label semantics,
      and column ordering

    Returns:
        A new dataframe coerced into canonical form (copy).
    """
    out = df.copy()

    if "source_trading_date" in out.columns:
        src = out["source_trading_date"].copy()

        # Start from an empty target column with the canonical storage dtype.
        out["source_trading_date"] = pd.Series(
            pd.NaT,
            index=out.index,
            dtype="datetime64[ns]",
        )

        non_null = src.notna()
        if bool(non_null.any()):
            try:
                coerced = _coerce_day_label_series(src.loc[non_null])
            except Exception as e:
                raise ValueError(f"failed to coerce `source_trading_date`: {e}") from e

            out.loc[non_null, "source_trading_date"] = coerced.to_numpy()

        out["source_trading_date"] = pd.to_datetime(
            out["source_trading_date"],
            errors="coerce",
        ).dt.normalize()
    if "session_id" in out.columns:
        if out["session_id"].isna().any():
            raise ValueError("daily_mark `session_id` contains null values.")
        out["session_id"] = out["session_id"].astype("int32")

    if "contract_id" in out.columns:
        out["contract_id"] = out["contract_id"].astype("string")

    if "instrument_id" in out.columns:
        out["instrument_id"] = out["instrument_id"].astype("Int64")

    if "mark_source" in out.columns:
        out["mark_source"] = out["mark_source"].astype("string")

    if "mark_quality" in out.columns:
        out["mark_quality"] = out["mark_quality"].astype("string")

    if "is_markable" in out.columns:
        out["is_markable"] = out["is_markable"].astype("boolean")

    if "is_carried" in out.columns:
        out["is_carried"] = out["is_carried"].astype("boolean")

    if "carry_streak" in out.columns:
        out["carry_streak"] = out["carry_streak"].astype("int32")

    if "source_dataset" in out.columns:
        out["source_dataset"] = out["source_dataset"].astype("string")

    if "source_publisher_id" in out.columns:
        out["source_publisher_id"] = out["source_publisher_id"].astype("Int32")

    if "source_raw_symbol" in out.columns:
        out["source_raw_symbol"] = out["source_raw_symbol"].astype("string")

    if "mark_px" in out.columns and not pd.api.types.is_numeric_dtype(out["mark_px"]):
        out["mark_px"] = pd.to_numeric(out["mark_px"], errors="raise")

    out = out.sort_values(["session_id"], kind="mergesort").reset_index(drop=True)

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
