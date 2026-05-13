"""
Proof 4 — Minimal daily OHLCV pull (one explicit contract)

Goal:
- Pull ~10 days of daily bars for a single, explicit futures contract (ESZ5)
  from GLBX.MDP3 using schema ohlcv-1d.
- Inspect returned dataframe shape, columns, dtypes, timestamp semantics,
  and identity fields.
- Keep the script small, deterministic, and paste-friendly for databento_notes.md.

Non-goals:
- No symbol discovery / refdata enumeration.
- No persistence or ingestion architecture.
- No backfills beyond the tiny sample window.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import databento as db
import pandas as pd

from mxm.secrets import get_secret

API_KEY_SECRET = "mxm/dev/databento/api-key"

DATASET = "GLBX.MDP3"
SCHEMA = "ohlcv-1d"
STYPE_IN = "raw_symbol"

SYMBOL = "ESH6"

# Use the same window that you cost-gated in Proof 3.
START_DATE = "2026-01-03"
END_DATE = "2026-01-13"  # exclusive per Databento conventions for most endpoints


@dataclass(frozen=True)
class DataFrameInspection:
    columns: list[str]
    dtypes: dict[str, str]
    index_name: Any
    index_type: str
    row_count: int
    min_ts: str | None
    max_ts: str | None
    identity_fields: list[str]
    identity_sample: dict[str, list[str]]


def _utc_now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def main() -> int:
    client = _make_client()

    try:
        df = _pull_ohlcv_1d_dataframe(client)
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    inspection = _inspect_dataframe(df)
    _print_report(df=df, inspection=inspection)

    return 0


def _make_client() -> db.Historical:
    api_key = get_secret(API_KEY_SECRET)
    return db.Historical(api_key)


def _pull_ohlcv_1d_dataframe(client: db.Historical):
    try:
        ts = client.timeseries.get_range(
            dataset=DATASET,
            schema=SCHEMA,
            start=START_DATE,
            end=END_DATE,
            symbols=SYMBOL,
            stype_in=STYPE_IN,
        )
    except Exception as e:
        raise RuntimeError(f"timeseries.get_range failed: {e}") from e

    try:
        return ts.to_df()
    except Exception as e:
        raise RuntimeError(f"failed to convert result to DataFrame: {e}") from e


def _inspect_dataframe(df: pd.DataFrame) -> DataFrameInspection:
    identity_fields = _identity_fields_present(df)

    return DataFrameInspection(
        columns=list(df.columns),
        dtypes={str(column): str(dtype) for column, dtype in df.dtypes.items()},
        index_name=getattr(df.index, "name", None),
        index_type=str(getattr(df.index, "dtype", type(df.index))),
        row_count=len(df),
        min_ts=_min_timestamp_label(df),
        max_ts=_max_timestamp_label(df),
        identity_fields=identity_fields,
        identity_sample=_identity_sample(df, identity_fields=identity_fields),
    )


def _min_timestamp_label(df: pd.DataFrame) -> str | None:
    if len(df) == 0:
        return None

    label = _safe_index_min(df)

    if "ts_event" in df.columns:
        ts_event_min = _safe_column_min(df, "ts_event")
        if ts_event_min is not None:
            label = f"{label} | ts_event(min)={ts_event_min}"

    return label


def _max_timestamp_label(df: pd.DataFrame) -> str | None:
    if len(df) == 0:
        return None

    label = _safe_index_max(df)

    if "ts_event" in df.columns:
        ts_event_max = _safe_column_max(df, "ts_event")
        if ts_event_max is not None:
            label = f"{label} | ts_event(max)={ts_event_max}"

    return label


def _safe_index_min(df: pd.DataFrame) -> str | None:
    try:
        return str(df.index.min())
    except Exception:
        return None


def _safe_index_max(df: pd.DataFrame) -> str | None:
    try:
        return str(df.index.max())
    except Exception:
        return None


def _safe_column_min(df: pd.DataFrame, column_name: str) -> str | None:
    try:
        return str(df[column_name].min())
    except Exception:
        return None


def _safe_column_max(df: pd.DataFrame, column_name: str) -> str | None:
    try:
        return str(df[column_name].max())
    except Exception:
        return None


def _identity_fields_present(df: pd.DataFrame) -> list[str]:
    return [
        column_name
        for column_name in ("publisher_id", "instrument_id", "symbol")
        if column_name in df.columns
    ]


def _identity_sample(
    df: pd.DataFrame,
    *,
    identity_fields: list[str],
) -> dict[str, list[str]]:
    if not identity_fields or len(df) == 0:
        return {}

    return {
        field_name: _identity_field_sample(df, field_name)
        for field_name in identity_fields
    }


def _identity_field_sample(df: pd.DataFrame, field_name: str) -> list[str]:
    try:
        unique_values = df[field_name].unique()
        return [str(value) for value in unique_values[:10]]
    except Exception:
        return ["<unavailable>"]


def _print_report(
    *,
    df: pd.DataFrame,
    inspection: DataFrameInspection,
) -> None:
    _print_header()
    _print_metadata(inspection)
    _print_columns(inspection)
    _print_dtypes(inspection)
    _print_identity_fields(inspection)
    _print_head(df)
    print("=" * 80)


def _print_header() -> None:
    print("=" * 80)
    print("MXM V1 — Databento Proof 4: Pull ohlcv-1d for one contract")
    print("=" * 80)


def _print_metadata(inspection: DataFrameInspection) -> None:
    print(f"Timestamp (UTC): {_utc_now_iso()}")
    print(f"Dataset:         {DATASET}")
    print(f"Schema:          {SCHEMA}")
    print(f"Symbol:          {SYMBOL} (stype_in={STYPE_IN})")
    print(f"Window:          {START_DATE} -> {END_DATE} (end is exclusive)")
    print("-" * 80)
    print(f"Rows returned:   {inspection.row_count}")
    print(
        f"Index:           name={inspection.index_name!r} dtype={inspection.index_type}"
    )
    print(f"Time bounds:     min={inspection.min_ts} max={inspection.max_ts}")
    print("-" * 80)


def _print_columns(inspection: DataFrameInspection) -> None:
    print("Columns:")
    print(json.dumps(inspection.columns, indent=2))
    print("-" * 80)


def _print_dtypes(inspection: DataFrameInspection) -> None:
    print("Dtypes:")
    print(json.dumps(inspection.dtypes, indent=2, sort_keys=True))
    print("-" * 80)


def _print_identity_fields(inspection: DataFrameInspection) -> None:
    print(f"Identity fields present: {inspection.identity_fields}")

    if not inspection.identity_sample:
        return

    print("Identity field sample (unique values, capped):")
    print(json.dumps(inspection.identity_sample, indent=2, sort_keys=True))
    print("-" * 80)


def _print_head(df: pd.DataFrame) -> None:
    print("Head (first 10 rows):")
    try:
        print(df.head(10).to_string())
    except Exception:
        print(df.head(10))


if __name__ == "__main__":
    raise SystemExit(main())
