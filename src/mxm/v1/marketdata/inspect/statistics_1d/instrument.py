"""
Data-plane inspection for statistics_1d (event stream).

Reads the persisted statistics_1d parquet via Statistics1DStore and produces a
JSON-serialisable descriptive report.

Normative constraints (MXM V1):
- MAY read dataset payloads (parquet) via the dataset store.
- MUST NOT write derived artifacts.
- MUST NOT implement settlement selection semantics or tie-breaking rules.
- MUST return JSON-serialisable objects only.

Design:
- Core transform is pure: describe_statistics_1d_events_df(df=...) -> dict.
  This can be reused by daily_stats derivation attempts to record diagnostics.
"""

from __future__ import annotations

import math
from datetime import date, datetime

import pandas as pd

from mxm.types import JSONMap, JSONScalar, JSONValue
from mxm.v1.marketdata.datasets.statistics_1d.store import Statistics1DStore


def _require_dataset(dataset: str | None) -> str:
    if dataset is None or not dataset:
        raise ValueError("statistics_1d inspection requires dataset")
    return dataset


def _optional_utc_timestamp(value: str | None) -> pd.Timestamp | None:
    if value is None:
        return None

    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.tz_localize("UTC")
    return ts.tz_convert("UTC")


def _is_missing_scalar(value: object) -> bool:
    if value is None:
        return True

    if value is pd.NaT:
        return True

    if value is pd.NA:
        return True

    if isinstance(value, float):
        return math.isnan(value)

    return False


def _json_safe_scalar(value: object) -> JSONScalar:
    if _is_missing_scalar(value):
        return None

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, datetime | date):
        return value.isoformat()

    if isinstance(value, str | int | float | bool):
        return value

    return repr(value)


# -------------------------
# Public API
# -------------------------


def inspect_statistics_1d_instrument(
    *,
    store: Statistics1DStore,
    dataset: str | None,
    publisher_id: int,
    instrument_id: int,
    start: str | None = None,
    end: str | None = None,
    sample_n: int = 5,
) -> JSONMap:
    """
    Inspect a single (publisher_id, instrument_id) event stream.

    Assumes the store returns the canonical schema (coerced/validated).
    """
    dataset_required = _require_dataset(dataset)
    df = _read_statistics_1d_events(
        store=store,
        dataset=dataset_required,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        start=start,
        end=end,
    )

    return describe_statistics_1d_events_df(
        df=df,
        identity={
            "dataset": dataset_required,
            "publisher_id": int(publisher_id),
            "instrument_id": int(instrument_id),
        },
        sample_n=sample_n,
    )


# -------------------------
# Store adapter (isolate API naming)
# -------------------------


def _read_statistics_1d_events(
    *,
    store: Statistics1DStore,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    start: str | None,
    end: str | None,
) -> pd.DataFrame:
    return store.read(
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        start=_optional_utc_timestamp(start),
        end=_optional_utc_timestamp(end),
    )


# -------------------------
# Core transform (pure): DF -> JSON report
# -------------------------


def describe_statistics_1d_events_df(
    *,
    df: pd.DataFrame,
    identity: JSONMap,
    sample_n: int = 5,
) -> JSONMap:
    """
    Pure descriptive inspection of a statistics_1d events dataframe.

    Expects canonical columns:
      - ts_recv, ts_event, ts_ref (UTC timestamps)
      - stat_type (numeric)
      - trading_date (date)
    Optional (reported if present):
      - is_final, is_actual, stat_flags
      - price, quantity, sequence, rtype, ts_in_delta
    """
    if len(df) == 0:
        return {
            "identity": identity,
            "rows": {
                "row_count": 0,
                "min_ts_event": None,
                "max_ts_event": None,
                "min_ts_recv": None,
                "max_ts_recv": None,
                "min_ts_ref": None,
                "max_ts_ref": None,
            },
            "distributions": {"stat_type_counts": {}, "settlement": None},
            "quality": {"null_fractions": {}, "ordering": {}},
            "per_trading_date": None,
            "samples": {"head": [], "tail": []},
        }

    d = df

    # Required columns (fail loudly if store violated the contract)
    for c in ("ts_recv", "ts_event", "ts_ref", "stat_type", "trading_date"):
        if c not in d.columns:
            raise KeyError(
                f"statistics_1d inspector expected column {c!r}; have={list(d.columns)!r}"
            )

    # Basic ranges (ISO strings)
    def _minmax_iso(series: pd.Series) -> tuple[str | None, str | None]:
        s = pd.to_datetime(series, errors="coerce", utc=True)
        if s.isna().all():
            return None, None
        return s.min().isoformat(), s.max().isoformat()

    min_ts_event, max_ts_event = _minmax_iso(d["ts_event"])
    min_ts_recv, max_ts_recv = _minmax_iso(d["ts_recv"])
    min_ts_ref, max_ts_ref = _minmax_iso(d["ts_ref"])

    # Distributions
    vc = d["stat_type"].value_counts(dropna=False)
    stat_type_counts: JSONMap = {str(k): int(v) for k, v in vc.items()}

    # Settlement diagnostics (descriptive only)
    settlement_report: JSONMap | None = None
    per_trading_date_report: JSONMap | None = None

    settlement_df = d[d["stat_type"] == 3]
    if len(settlement_df) > 0:
        settlement_report = {
            "row_count": len(settlement_df),
            "min_ts_event": _minmax_iso(settlement_df["ts_event"])[0],
            "max_ts_event": _minmax_iso(settlement_df["ts_event"])[1],
            "is_final_counts": _value_counts_json(settlement_df, "is_final"),
            "is_actual_counts": _value_counts_json(settlement_df, "is_actual"),
            "stat_flags_topk": _topk_json(settlement_df, "stat_flags", k=10),
        }
        # Per-trading-date density and multi-event patterns
        # trading_date is expected to be date-like; normalise to ISO date strings.
        td = pd.to_datetime(settlement_df["trading_date"], errors="coerce").dt.date
        counts_by_date = td.value_counts(dropna=False)
        non_null_dates = [
            dt_ for dt_ in counts_by_date.index if not _is_missing_scalar(dt_)
        ]

        unique_dates = len(non_null_dates)
        max_events_per_date = int(counts_by_date.max()) if len(counts_by_date) else 0
        dates_with_multiple_events = int(
            sum(
                1
                for dt_, count in counts_by_date.items()
                if not _is_missing_scalar(dt_) and int(count) > 1
            )
        )
        multiple_finals_same_date = None
        dates_without_final = None

        if "is_final" in settlement_df.columns:
            finals_mask = settlement_df["is_final"].astype("boolean").fillna(False)
            finals_only = settlement_df[finals_mask]

            finals_td = pd.to_datetime(
                finals_only["trading_date"], errors="coerce"
            ).dt.date
            finals_counts = finals_td.value_counts(dropna=False)

            multiple_finals_same_date = int(
                sum(
                    1
                    for dt_, count in finals_counts.items()
                    if not _is_missing_scalar(dt_) and int(count) > 1
                )
            )
            final_date_set = {
                dt_ for dt_ in finals_counts.index if not _is_missing_scalar(dt_)
            }
            dates_without_final = int(
                sum(
                    1
                    for dt_ in counts_by_date.index
                    if pd.notna(dt_) and dt_ not in final_date_set
                )
            )

        per_trading_date_report = {
            "unique_dates": unique_dates,
            "max_events_per_date": max_events_per_date,
            "dates_with_multiple_events": dates_with_multiple_events,
            "multiple_finals_same_date": multiple_finals_same_date,
            "dates_without_final": dates_without_final,
        }

    # Quality: null fractions for key columns
    null_fracs: JSONMap = {}
    key_cols = [
        "ts_recv",
        "ts_event",
        "ts_ref",
        "trading_date",
        "stat_type",
        # optional, reported if present
        "price",
        "quantity",
        "sequence",
        "rtype",
        "ts_in_delta",
        "is_final",
        "is_actual",
        "stat_flags",
    ]
    for c in key_cols:
        if c in d.columns:
            null_fracs[c] = float(d[c].isna().mean())

    # Quality: simple ordering sanity (descriptive)
    # We do NOT enforce monotonicity (event streams can be out-of-order), but we report it.
    ordering: JSONMap = {
        "ts_event_non_decreasing_fraction": _non_decreasing_fraction(d["ts_event"]),
        "ts_recv_non_decreasing_fraction": _non_decreasing_fraction(d["ts_recv"]),
        "ts_ref_non_decreasing_fraction": _non_decreasing_fraction(d["ts_ref"]),
    }

    # Samples: JSON-friendly head/tail
    head: list[JSONValue] = list(_rows_to_json(d.head(sample_n)))
    tail: list[JSONValue] = list(_rows_to_json(d.tail(sample_n)))
    rows: JSONMap = {
        "row_count": len(d),
        "min_ts_event": min_ts_event,
        "max_ts_event": max_ts_event,
        "min_ts_recv": min_ts_recv,
        "max_ts_recv": max_ts_recv,
        "min_ts_ref": min_ts_ref,
        "max_ts_ref": max_ts_ref,
    }

    distributions: JSONMap = {
        "stat_type_counts": stat_type_counts,
        "settlement": settlement_report,
    }

    quality: JSONMap = {
        "null_fractions": null_fracs,
        "ordering": ordering,
    }

    samples: JSONMap = {
        "head": head,
        "tail": tail,
    }

    report: JSONMap = {
        "identity": identity,
        "rows": rows,
        "distributions": distributions,
        "quality": quality,
        "per_trading_date": per_trading_date_report,
        "samples": samples,
    }

    return report


# -------------------------
# Helpers (pure)
# -------------------------


def _value_counts_json(df: pd.DataFrame, col: str) -> JSONMap | None:
    if col not in df.columns:
        return None
    vc = df[col].value_counts(dropna=False)
    return {str(k): int(v) for k, v in vc.items()}


def _topk_json(df: pd.DataFrame, col: str, k: int) -> list[JSONValue] | None:
    if col not in df.columns:
        return None

    vc = df[col].value_counts(dropna=False).head(k)

    return [
        {
            "value": _json_safe_scalar(idx),
            "count": int(cnt),
        }
        for idx, cnt in vc.items()
    ]


def _rows_to_json(df: pd.DataFrame) -> list[JSONMap]:
    if len(df) == 0:
        return []

    out: list[JSONMap] = []

    for _, row in df.iterrows():
        rec: JSONMap = {}
        for key, value in row.items():
            rec[str(key)] = _json_safe_scalar(value)
        out.append(rec)

    return out


def _non_decreasing_fraction(series: pd.Series) -> float:
    """
    Fraction of adjacent pairs that are non-decreasing after coercion to UTC.

    Returns 1.0 for length < 2.
    """
    if len(series) < 2:
        return 1.0

    s = pd.to_datetime(series, errors="coerce", utc=True)
    a = s.iloc[:-1].reset_index(drop=True)
    b = s.iloc[1:].reset_index(drop=True)

    ok = (b >= a).fillna(False)
    return float(ok.mean())
