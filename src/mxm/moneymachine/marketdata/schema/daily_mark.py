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

# TODO(mxm-v2):
# Evaluate migration of dataframe schema validation/coercion to Pandera.
#
# Motivation:
# - current validation logic is highly structured and increasingly declarative
# - substantial duplication exists across:
#     - required column checks
#     - dtype enforcement/coercion
#     - nullable handling
#     - categorical membership validation
#     - dataframe-level semantic invariants
# - pyright/pandas dtype interactions are verbose and fragile
#
# Potential benefits:
# - explicit dataframe schema objects
# - centralized dtype/coercion semantics
# - reusable schema composition across marketdata datasets
# - clearer separation between:
#     - column-level schema constraints
#     - MXM semantic state invariants
# - improved interoperability with parquet/dataframe tooling
#
# Important caveats:
# - MXM-specific semantic state rules (carry semantics, unavailable state,
#   business-session invariants, etc.) would still require custom dataframe
#   checks layered on top of declarative schema definitions
# - migration should only occur once common schema abstractions across:
#     - daily_mark
#     - daily_stats
#     - ohlcv_1d
#   have stabilized
# - avoid introducing Pandera dependency prematurely during v1 stabilization
#
# Likely future architecture:
# - Pandera handles:
#     - dtype coercion
#     - nullable semantics
#     - required/optional columns
#     - categorical constraints
#     - basic dataframe integrity checks
# - MXM semantic validators handle:
#     - cross-row temporal/business invariants
#     - carry-forward semantics
#     - provenance consistency
#     - dataset-specific market semantics
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import numpy as np
import pandas as pd

from mxm.moneymachine.utils.date_utils import coerce_np_day
from mxm.moneymachine.utils.hashing import sha256_df_content

DailyMarkDType = Literal[
    "int32",
    "Int32",
    "Int64",
    "string",
    "boolean",
]


@dataclass(frozen=True)
class DailyMarkSchema:
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

    optional: tuple[str, ...] = (
        "instrument_id",
        "source_trading_date",
        "source_dataset",
        "source_publisher_id",
        "source_raw_symbol",
    )

    dtype_targets: dict[str, DailyMarkDType] = field(
        default_factory=lambda: {
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
        }
    )

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


DAILY_MARK = DailyMarkSchema()


def _coerce_daily_mark_dtypes(df: pd.DataFrame) -> None:
    if "session_id" in df.columns and df["session_id"].isna().any():
        raise ValueError("daily_mark `session_id` contains null values.")
    for column_name, dtype_target in DAILY_MARK.dtype_targets.items():
        _coerce_daily_mark_optional_column(df, column_name, dtype_target)


def _coerce_daily_mark_optional_column(
    df: pd.DataFrame,
    column_name: str,
    dtype_target: DailyMarkDType,
) -> None:
    if column_name not in df.columns:
        return

    if dtype_target == "int32":
        df[column_name] = df[column_name].astype("int32")
        return

    if dtype_target == "Int32":
        df[column_name] = df[column_name].astype(pd.Int32Dtype())
        return

    if dtype_target == "Int64":
        df[column_name] = df[column_name].astype(pd.Int64Dtype())
        return

    if dtype_target == "string":
        df[column_name] = df[column_name].astype(pd.StringDtype())
        return

    if dtype_target == "boolean":
        df[column_name] = df[column_name].astype(pd.BooleanDtype())
        return


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

    Raises:
        ValueError: if the dataframe fails validation.
    """
    _validate_daily_mark_required_columns(df)
    _validate_daily_mark_session_id(df)
    _validate_daily_mark_contract_id(df)
    _validate_daily_mark_source_trading_date(df)
    _validate_daily_mark_mark_taxonomy(df)
    _validate_daily_mark_boolean_columns(df)
    _validate_daily_mark_carry_streak(df)
    _validate_daily_mark_price_column(df)
    _validate_daily_mark_unavailable_state(df)
    _validate_daily_mark_available_state(df)
    _validate_daily_mark_carried_state(df)
    _validate_daily_mark_optional_provenance_columns(df)


def _validate_daily_mark_required_columns(df: pd.DataFrame) -> None:
    missing = _missing_columns(df, DAILY_MARK.required)
    if missing:
        raise ValueError(f"daily_mark dataframe missing required columns: {missing}")


def _validate_daily_mark_session_id(df: pd.DataFrame) -> None:
    if df["session_id"].isna().any():
        raise ValueError("daily_mark `session_id` contains null values")

    if not pd.api.types.is_integer_dtype(df["session_id"]):
        raise ValueError(
            f"daily_mark `session_id` must be integer dtype, "
            f"got {df['session_id'].dtype}"
        )

    if (df["session_id"] < 0).any():
        raise ValueError("daily_mark `session_id` must be non-negative")

    if not df["session_id"].is_monotonic_increasing:
        raise ValueError("daily_mark `session_id` must be sorted increasing")


def _validate_daily_mark_contract_id(df: pd.DataFrame) -> None:
    if df["contract_id"].isna().any():
        raise ValueError("daily_mark `contract_id` contains null values")

    if df.duplicated(subset=["contract_id", "session_id"]).any():
        raise ValueError("daily_mark contains duplicate (contract_id, session_id) rows")

    if df["contract_id"].nunique(dropna=False) != 1:
        raise ValueError("daily_mark surface must contain exactly one contract_id")


def _validate_daily_mark_source_trading_date(df: pd.DataFrame) -> None:
    if "source_trading_date" not in df.columns:
        return

    non_null = df["source_trading_date"].dropna()
    if not non_null.empty:
        _validate_day_label_series(
            df.loc[non_null.index, "source_trading_date"],
            column_name="source_trading_date",
        )


def _validate_daily_mark_mark_taxonomy(df: pd.DataFrame) -> None:
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


def _validate_daily_mark_boolean_columns(df: pd.DataFrame) -> None:
    for column_name in ("is_markable", "is_carried"):
        if str(df[column_name].dtype) != "boolean":
            raise ValueError(
                f"daily_mark `{column_name}` must be pandas boolean dtype, "
                f"got {df[column_name].dtype}"
            )


def _validate_daily_mark_carry_streak(df: pd.DataFrame) -> None:
    if not pd.api.types.is_integer_dtype(df["carry_streak"]):
        raise ValueError(
            f"daily_mark `carry_streak` must be integer dtype, "
            f"got {df['carry_streak'].dtype}"
        )

    if (df["carry_streak"] < 0).any():
        raise ValueError("daily_mark `carry_streak` must be non-negative")


def _validate_daily_mark_price_column(df: pd.DataFrame) -> None:
    if not pd.api.types.is_numeric_dtype(df["mark_px"]):
        raise ValueError(
            f"daily_mark `mark_px` must be numeric, got {df['mark_px'].dtype}"
        )


def _validate_daily_mark_unavailable_state(df: pd.DataFrame) -> None:
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


def _validate_daily_mark_available_state(df: pd.DataFrame) -> None:
    available_mask = df["mark_source"] != "unavailable"

    if bool(df.loc[available_mask, "mark_px"].isna().any()):
        raise ValueError("daily_mark available rows must have non-null `mark_px`")

    if bool((~df.loc[available_mask, "is_markable"].fillna(False)).any()):
        raise ValueError("daily_mark available rows must have `is_markable=True`")


def _validate_daily_mark_carried_state(df: pd.DataFrame) -> None:
    unavailable_mask = df["mark_source"] == "unavailable"
    available_mask = ~unavailable_mask
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


def _validate_daily_mark_optional_provenance_columns(df: pd.DataFrame) -> None:
    if "instrument_id" in df.columns:
        if not pd.api.types.is_integer_dtype(df["instrument_id"]):
            raise ValueError(
                "daily_mark `instrument_id` must be integer dtype if present, "
                f"got {df['instrument_id'].dtype}"
            )

    if "source_publisher_id" in df.columns:
        if not pd.api.types.is_integer_dtype(df["source_publisher_id"]):
            raise ValueError(
                "daily_mark `source_publisher_id` must be integer dtype if present, "
                f"got {df['source_publisher_id'].dtype}"
            )

    for column_name in ("source_dataset", "source_raw_symbol"):
        if column_name in df.columns and str(df[column_name].dtype) != "string":
            raise ValueError(
                f"daily_mark `{column_name}` must be pandas string dtype if present, "
                f"got {df[column_name].dtype}"
            )


def coerce_daily_mark(
    df: pd.DataFrame,
    *,
    ensure_column_order: bool = True,
) -> pd.DataFrame:
    """
    Coerce a dataframe into canonical daily_mark surface form.

    Returns:
        A new dataframe coerced into canonical form.
    """
    out = df.copy()

    _coerce_daily_mark_source_trading_date(out)
    _coerce_daily_mark_dtypes(out)
    _coerce_daily_mark_price(out)
    out = _sort_daily_mark_rows(out)

    if ensure_column_order:
        out = _order_daily_mark_columns(out)

    validate_daily_mark(out)

    return out


def _coerce_daily_mark_source_trading_date(df: pd.DataFrame) -> None:
    if "source_trading_date" not in df.columns:
        return

    source_trading_date = df["source_trading_date"].copy()

    df["source_trading_date"] = pd.Series(
        pd.NaT,
        index=df.index,
        dtype="datetime64[ns]",
    )

    non_null = source_trading_date.notna()
    if bool(non_null.any()):
        try:
            coerced = _coerce_day_label_series(source_trading_date.loc[non_null])
        except Exception as exc:
            raise ValueError(f"failed to coerce `source_trading_date`: {exc}") from exc

        df.loc[non_null, "source_trading_date"] = coerced.to_numpy()

    df["source_trading_date"] = pd.to_datetime(
        df["source_trading_date"],
        errors="coerce",
    ).dt.normalize()


def _coerce_daily_mark_price(df: pd.DataFrame) -> None:
    if "mark_px" not in df.columns:
        return

    if not pd.api.types.is_numeric_dtype(df["mark_px"]):
        df["mark_px"] = pd.to_numeric(df["mark_px"], errors="raise")


def _order_daily_mark_columns(df: pd.DataFrame) -> pd.DataFrame:
    missing = _missing_columns(df, DAILY_MARK.required)
    if missing:
        raise ValueError(
            f"cannot coerce daily_mark: missing required columns: {missing}"
        )

    ordered_columns = [
        column_name for column_name in DAILY_MARK.columns if column_name in df.columns
    ]
    return df.loc[:, ordered_columns]


def _sort_daily_mark_rows(df: pd.DataFrame) -> pd.DataFrame:
    if "session_id" not in df.columns:
        return df

    return df.sort_values(["session_id"], kind="mergesort").reset_index(drop=True)


def hash_daily_mark_content(df: pd.DataFrame) -> str:
    return sha256_df_content(df, coerce=coerce_daily_mark)
