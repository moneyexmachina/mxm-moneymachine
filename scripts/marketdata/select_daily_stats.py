from __future__ import annotations

import datetime as _dt
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd

from mxm.v1.marketdata.datasets.statistics_1d.store import Statistics1DStore
from mxm.v1.marketdata.stores.layout import MarketdataLayout

SETTLEMENT_STAT_TYPE = 3
SELECTION_RULE_VERSION = "settlement_v0"


@dataclass(frozen=True)
class SettlementSelectionDiagnostics:
    source_rows_total: int
    settlement_rows_total: int
    session_dates_total: int
    selected_rows: int

    session_dates_multiple_candidates_n: int
    session_dates_multiple_finals_n: int
    session_dates_missing_final_n: int

    session_dates_multiple_candidates_sample: list[str]
    session_dates_multiple_finals_sample: list[str]
    session_dates_missing_final_sample: list[str]


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _row_hash(df: pd.DataFrame, cols: list[str]) -> pd.Series:
    """
    Deterministic per-row hash used as a final tie-breaker when sequence/ts_event ties.
    """

    def _to_jsonable(v: Any) -> Any:
        if pd.isna(v):
            return None
        # pandas Timestamp
        if isinstance(v, pd.Timestamp):
            return v.isoformat()
        # python datetime / date
        if isinstance(v, (_dt.datetime, _dt.date)):
            return v.isoformat()
        # numpy scalars -> python scalars
        # (covers int64, float64, bool_, etc.)
        try:
            import numpy as np  # local import ok

            if isinstance(v, np.generic):
                return v.item()
        except Exception:
            pass
        return v

    def one(row: pd.Series) -> str:
        payload: dict[str, Any] = {c: _to_jsonable(row.get(c, None)) for c in cols}
        b = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return _sha256_bytes(b)

    return df.apply(one, axis=1)


def select_settlement_daily(
    df: pd.DataFrame,
    *,
    sample_n: int = 20,
    selection_rule_version: str = SELECTION_RULE_VERSION,
) -> tuple[pd.DataFrame, SettlementSelectionDiagnostics]:
    """
    Select a single settlement row per session date (trading date), deterministically.

    Input:
      - statistics_1d event stream for ONE instrument (but works fine if more).
      - Required columns:
          stat_type, ts_ref, sequence, price, is_final
      - Optional columns (used for tie-break / provenance if present):
          ts_event, is_actual, stat_flags, update_action, dataset, schema, publisher_id, instrument_id, raw_symbol

    Session date anchor:
      - session_date := ts_ref.date()   (ts_ref is vendor session reference)

    Selection rule (per session_date):
      1) Prefer is_final == True
      2) Choose highest sequence
      3) Tie-break by latest ts_event (if present)
      4) Final tie-break by deterministic row hash

    Output:
      - daily settlements dataframe: one row per session_date
      - diagnostics: counts + small samples of anomalous dates

    Notes:
      - We intentionally do NOT filter on is_actual in v0. We propagate it.
      - We also intentionally do NOT interpret stat_flags beyond is_final already provided.
    """
    required = ["stat_type", "ts_ref", "sequence", "price", "is_final"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise KeyError(
            f"select_settlement_daily missing required columns: {missing}. "
            f"Available: {sorted(df.columns)}"
        )

    src_total = len(df)

    settle = df[df["stat_type"] == SETTLEMENT_STAT_TYPE].copy()
    settle_total = len(settle)

    if settle_total == 0:
        empty = settle.head(0).copy()
        empty["session_date"] = pd.Series(dtype="object")
        empty["selection_rule_version"] = selection_rule_version
        diag = SettlementSelectionDiagnostics(
            source_rows_total=src_total,
            settlement_rows_total=0,
            session_dates_total=0,
            selected_rows=0,
            session_dates_multiple_candidates_n=0,
            session_dates_multiple_finals_n=0,
            session_dates_missing_final_n=0,
            session_dates_multiple_candidates_sample=[],
            session_dates_multiple_finals_sample=[],
            session_dates_missing_final_sample=[],
        )
        return empty, diag

    # Normalize types
    settle["ts_ref"] = pd.to_datetime(settle["ts_ref"], utc=True, errors="coerce")
    settle["session_date"] = settle["ts_ref"].dt.date

    # Some rows could have null ts_ref (shouldn't for settlement, but defend)
    settle = settle[settle["session_date"].notna()].copy()

    settle["is_final"] = settle["is_final"].fillna(False).astype(bool)
    settle["sequence"] = (
        pd.to_numeric(settle["sequence"], errors="coerce").fillna(-1).astype("int64")
    )

    has_ts_event = "ts_event" in settle.columns
    if has_ts_event:
        settle["ts_event"] = pd.to_datetime(
            settle["ts_event"], utc=True, errors="coerce"
        )
    else:
        settle["ts_event"] = pd.NaT

    # Row hash tie-break: include stable identity + key fields and any payload columns we have.
    hash_cols: list[str] = []
    for c in [
        "publisher_id",
        "instrument_id",
        "raw_symbol",
        "stat_type",
        "session_date",
        "ts_ref",
        "price",
        "quantity",
        "sequence",
        "is_final",
        "is_actual",
        "stat_flags",
        "update_action",
        "ts_event",
    ]:
        if c in settle.columns:
            hash_cols.append(c)
    settle["_row_hash"] = _row_hash(settle, cols=hash_cols)

    # Diagnostics pre-selection
    g = settle.groupby("session_date", sort=True)

    per_date = g.size().rename("n_candidates").to_frame()
    per_date["n_finals"] = g["is_final"].sum().astype(int)

    dates_multiple_candidates = per_date[per_date["n_candidates"] > 1].index.tolist()
    dates_multiple_finals = per_date[per_date["n_finals"] > 1].index.tolist()
    dates_missing_final = per_date[per_date["n_finals"] == 0].index.tolist()

    # Deterministic ordering then pick first per session_date
    # Sort by session_date ascending, then:
    #   is_final desc, sequence desc, ts_event desc, row_hash desc
    settle_sorted = settle.sort_values(
        by=["session_date", "is_final", "sequence", "ts_event", "_row_hash"],
        ascending=[True, False, False, False, False],
        kind="mergesort",
    )

    selected = (
        settle_sorted.groupby("session_date", sort=True, as_index=False).head(1).copy()
    )

    # Enrich with per-date counts and provenance fields
    selected = selected.merge(per_date.reset_index(), on="session_date", how="left")
    selected["selection_rule_version"] = selection_rule_version
    selected["selected_is_final"] = selected["is_final"].astype(bool)
    selected["selected_sequence"] = selected["sequence"].astype("int64")
    selected["selected_ts_event"] = selected["ts_event"]

    # Order output for readability
    selected = selected.sort_values(["session_date"], kind="mergesort").reset_index(
        drop=True
    )

    diag = SettlementSelectionDiagnostics(
        source_rows_total=src_total,
        settlement_rows_total=settle_total,
        session_dates_total=int(per_date.shape[0]),
        selected_rows=int(selected.shape[0]),
        session_dates_multiple_candidates_n=len(dates_multiple_candidates),
        session_dates_multiple_finals_n=len(dates_multiple_finals),
        session_dates_missing_final_n=len(dates_missing_final),
        session_dates_multiple_candidates_sample=[
            d.isoformat() for d in dates_multiple_candidates[:sample_n]
        ],
        session_dates_multiple_finals_sample=[
            d.isoformat() for d in dates_multiple_finals[:sample_n]
        ],
        session_dates_missing_final_sample=[
            d.isoformat() for d in dates_missing_final[:sample_n]
        ],
    )

    return selected, diag


if __name__ == "__main__":
    store = Statistics1DStore(layout=MarketdataLayout(root=Path.home() / ".mxm"))
    df = store.read(dataset="GLBX.MDP3", publisher_id=1, instrument_id=4916)
    print(df)
    print(df.dtypes)
    print(df.columns.tolist())
    for t in [1, 4, 5, 6, 9, 10]:
        sub = df[df.stat_type == t]
        print(t, "rows:", len(sub))
        if "ts_ref" in sub.columns:
            print("  ts_ref non-null:", sub["ts_ref"].notna().sum())

    sub = df[df.stat_type == 1].copy()
    sub["anchor_date"] = sub["ts_event"].dt.date
    g = sub.groupby("anchor_date").size()
    print(g.describe())
    print("max rows/day:", g.max())
    settlement, diag = select_settlement_daily(df)
    print(settlement)
    print(diag)

    d = "2025-06-17"  # one from the missing_final list
    cand = df[(df.stat_type == 3) & (df.ts_ref.dt.date.astype(str) == d)].copy()

    print(
        cand[
            [
                "ts_event",
                "sequence",
                "price",
                "is_final",
                "is_actual",
                "stat_flags",
                "update_action",
            ]
        ]
        .sort_values(
            ["is_final", "sequence", "ts_event"], ascending=[False, False, False]
        )
        .head(20)
        .to_string(index=False)
    )

    print("final count:", cand["is_final"].sum())
    print("candidates:", len(cand))
