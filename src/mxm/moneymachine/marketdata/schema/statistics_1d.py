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

# TODO(mxm-v2):
# Consider replacing the parallel hand-written schema/coercion modules for
# ohlcv_1d, statistics_1d, daily_stats, and daily_mark with a shared dataframe
# schema layer, potentially Pandera-backed. These modules now repeat the same
# structure: required columns, dtype coercion, nullable semantics, categorical
# constraints, numeric parsing, column ordering, and dataset-specific semantic
# invariants.
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd

from mxm.moneymachine.utils.hashing import sha256_df_content
from mxm.moneymachine.utils.time_utils import ensure_utc_datetime_series

Statistics1DDType = Literal[
    "int16",
    "int32",
    "int64",
    "string",
    "boolean",
]


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
    dtype_targets: dict[str, Statistics1DDType] = field(
        default_factory=lambda: {
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
        }
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
    _validate_statistics_1d_required_columns(df)
    _validate_statistics_1d_timestamp_columns(df)
    _validate_statistics_1d_required_event_timestamps(df)
    _validate_statistics_1d_identity_columns(df)
    _validate_statistics_1d_rtype(df)
    _validate_statistics_1d_numeric_columns(df)
    _validate_statistics_1d_boolean_columns(df)


def _validate_statistics_1d_required_columns(df: pd.DataFrame) -> None:
    missing = _missing_columns(df, STATISTICS_1D.required)
    if missing:
        raise ValueError(f"statistics dataframe missing required columns: {missing}")


def _validate_statistics_1d_timestamp_columns(df: pd.DataFrame) -> None:
    for column_name in ("ts_recv", "ts_event", "ts_ref"):
        timestamp_series = df[column_name]

        if not pd.api.types.is_datetime64_any_dtype(timestamp_series):
            raise ValueError(
                f"statistics `{column_name}` must be datetime dtype, "
                f"got {timestamp_series.dtype}"
            )

        if not isinstance(timestamp_series.dtype, pd.DatetimeTZDtype):
            raise ValueError(
                f"statistics `{column_name}` must be timezone-aware (UTC). "
                "If you have naive timestamps, localize them to UTC."
            )

        if str(timestamp_series.dtype.tz) != "UTC":
            raise ValueError(
                f"statistics `{column_name}` must be UTC, "
                f"got tz={timestamp_series.dtype.tz}"
            )


def _validate_statistics_1d_required_event_timestamps(df: pd.DataFrame) -> None:
    for column_name in ("ts_recv", "ts_event"):
        if df[column_name].isna().any():
            raise ValueError(f"statistics `{column_name}` contains null values")


def _validate_statistics_1d_identity_columns(df: pd.DataFrame) -> None:
    for column_name in (
        "publisher_id",
        "channel_id",
        "instrument_id",
        "raw_symbol",
        "dataset",
        "schema",
        "rtype",
        "stat_type",
    ):
        if df[column_name].isna().any():
            raise ValueError(f"statistics `{column_name}` contains null values")


def _validate_statistics_1d_rtype(df: pd.DataFrame) -> None:
    bad_rtypes = df.loc[df["rtype"] != 24, "rtype"].unique()
    if len(bad_rtypes) > 0:
        raise ValueError(f"statistics `rtype` must be 24, saw {bad_rtypes}")


def _validate_statistics_1d_numeric_columns(df: pd.DataFrame) -> None:
    for column_name in ("price", "quantity", "sequence", "ts_in_delta"):
        column = df[column_name]
        if not pd.api.types.is_numeric_dtype(column):
            raise ValueError(
                f"statistics `{column_name}` must be numeric, got {column.dtype}"
            )


def _validate_statistics_1d_boolean_columns(df: pd.DataFrame) -> None:
    for column_name in (
        "is_final",
        "is_actual",
        "is_trading_tick",
        "is_intraday",
        "is_null_set",
    ):
        column = df[column_name]
        if column.dtype not in (bool, "bool") and str(column.dtype) != "boolean":
            raise ValueError(
                f"statistics `{column_name}` must be boolean dtype, got {column.dtype}"
            )


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
    - this function finalizes dtypes, UTC timestamps, and column ordering
    """
    out = df.copy()

    _coerce_statistics_1d_timestamps(out)
    _ensure_statistics_1d_trading_date(out)
    _set_statistics_1d_dataset_and_schema(out, dataset=dataset, schema=schema)
    _coerce_statistics_1d_dtype_targets(out)
    _coerce_statistics_1d_numeric_columns(out)

    if ensure_column_order:
        out = _order_statistics_1d_columns(out)

    validate_statistics_1d(out)

    return out


def _coerce_statistics_1d_timestamps(df: pd.DataFrame) -> None:
    for column_name in ("ts_recv", "ts_event", "ts_ref"):
        df[column_name] = ensure_utc_datetime_series(df[column_name])


def _ensure_statistics_1d_trading_date(df: pd.DataFrame) -> None:
    if "trading_date" not in df.columns:
        df["trading_date"] = df["ts_ref"].dt.date


def _set_statistics_1d_dataset_and_schema(
    df: pd.DataFrame,
    *,
    dataset: str | None,
    schema: str,
) -> None:
    if dataset is not None:
        df["dataset"] = dataset

    df["schema"] = schema


def _coerce_statistics_1d_dtype_targets(df: pd.DataFrame) -> None:
    for column_name, dtype_target in STATISTICS_1D.dtype_targets.items():
        _coerce_statistics_1d_optional_column(df, column_name, dtype_target)


def _coerce_statistics_1d_optional_column(
    df: pd.DataFrame,
    column_name: str,
    dtype_target: Statistics1DDType,
) -> None:
    if column_name not in df.columns:
        return

    try:
        if dtype_target == "int16":
            df[column_name] = df[column_name].astype("int16")
            return

        if dtype_target == "int32":
            df[column_name] = df[column_name].astype("int32")
            return

        if dtype_target == "int64":
            df[column_name] = df[column_name].astype("int64")
            return

        if dtype_target == "string":
            df[column_name] = df[column_name].astype(pd.StringDtype())
            return

        if dtype_target == "boolean":
            df[column_name] = df[column_name].astype(pd.BooleanDtype())
            return

    except Exception as exc:
        raise ValueError(
            f"failed to coerce `{column_name}` to {dtype_target}: {exc}"
        ) from exc


def _coerce_statistics_1d_numeric_columns(df: pd.DataFrame) -> None:
    for column_name in (
        "price",
        "quantity",
        "sequence",
        "ts_in_delta",
        "rtype",
        "stat_type",
    ):
        if column_name in df.columns and not pd.api.types.is_numeric_dtype(
            df[column_name]
        ):
            df[column_name] = pd.to_numeric(df[column_name], errors="raise")


def _order_statistics_1d_columns(df: pd.DataFrame) -> pd.DataFrame:
    missing = _missing_columns(df, STATISTICS_1D.required)
    if missing:
        raise ValueError(f"cannot coerce: missing required columns: {missing}")

    return df.loc[:, list(STATISTICS_1D.columns)]


def hash_statistics_1d_content(df: pd.DataFrame) -> str:
    """
    Stable content hash for idempotency checks (order-invariant).
    Hashes canonicalised statistics_1d event content, not file bytes.
    """
    return sha256_df_content(df, coerce=coerce_statistics_1d)
