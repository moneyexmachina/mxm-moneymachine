from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd

from mxm.v1.utils.date_utils import fmt_iso_day
from mxm.v1.utils.time_utils import ensure_utc_datetime_series

# ----------------------------
# Diagnostics
# ----------------------------


@dataclass(frozen=True)
class StatSelectionDiagnostics:
    stat_type: int
    source_rows_total: int
    candidate_rows_total: int
    session_dates_total: int
    selected_rows: int
    session_dates_multiple_candidates_n: int
    session_dates_missing_n: int
    session_dates_multiple_candidates_sample: list[str]


@dataclass(frozen=True)
class DailyStatsSelectionDiagnostics:
    source_rows_total: int
    by_stat: dict[int, StatSelectionDiagnostics]


# ----------------------------
# Helpers
# ----------------------------


def _require_cols(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"daily_stats.selection: missing required columns: {missing}")


def _coerce_session_date_series(s: pd.Series) -> pd.Series:
    """
    Coerce session_date-like values to tz-aware UTC timestamps aligned to midnight.

    Returns Series[datetime64[ns, UTC]] with NaT for missing/unparseable.
    """
    if s.empty:
        return pd.Series([], dtype="datetime64[ns, UTC]")

    # Be permissive for internal date-like values (YYYY-MM-DD, date objects, numpy day labels).
    dt = pd.to_datetime(s, errors="coerce", utc=True)

    # Normalise to UTC midnight (day label semantics)
    out = dt.dt.normalize()

    # Ensure exact dtype datetime64[ns, UTC] (defensive)
    out = ensure_utc_datetime_series(out)

    return out


def _select_one_per_session_date(
    candidates: pd.DataFrame,
    *,
    prefer_final: bool,
) -> tuple[pd.DataFrame, StatSelectionDiagnostics]:
    """
    Deterministically select exactly one row per session_date.

    Selection rule
    --------------
    For each session_date group:

    - If prefer_final=False:
        pick the row with maximum (sequence, ts_event).
    - If prefer_final=True:
        prefer rows with is_final==True; within the preferred set pick max (sequence, ts_event).
        If a session_date has no finals, fall back to max (sequence, ts_event) across all rows.

    Notes
    -----
    This implementation avoids groupby.apply for performance and to keep `session_date`
    as a normal column (not an index artefact).
    """
    _require_cols(candidates, ["session_date", "ts_event", "sequence"])
    candidates = candidates.copy()
    candidates["session_date"] = _coerce_session_date_series(candidates["session_date"])
    candidates = candidates[candidates["session_date"].notna()].copy()

    if prefer_final:
        _require_cols(candidates, ["is_final"])

    src_total = len(candidates)
    if src_total == 0:
        diag = StatSelectionDiagnostics(
            stat_type=int(candidates.attrs.get("stat_type", -1)),
            source_rows_total=int(candidates.attrs.get("source_rows_total", 0)),
            candidate_rows_total=0,
            session_dates_total=0,
            selected_rows=0,
            session_dates_multiple_candidates_n=0,
            session_dates_missing_n=0,
            session_dates_multiple_candidates_sample=[],
        )
        # Ensure empty output still has the session_date column.
        out = candidates.copy()
        if "session_date" not in out.columns:
            out["session_date"] = pd.Series([], dtype="object")
        return out, diag

    # Diagnostics: multiplicity by session_date
    counts = candidates.groupby("session_date", sort=True).size()
    multi = counts[counts > 1]
    multi_sample = [fmt_iso_day(d) for d in multi.index[:20]]

    cand = candidates.copy()

    # Ensure ts_event is comparable (should already be datetime64[ns, UTC] in your schema)
    # and sequence is numeric. We rely on stable pandas sort semantics.
    if prefer_final:
        # Final rows should rank above non-final rows within each session_date.
        # Use uint8 to keep it cheap; True->1, False/NA->0.
        cand["_final_rank"] = (
            cand["is_final"].to_numpy(dtype="bool", na_value=False).astype("uint8")
        )
        sort_cols = ["session_date", "_final_rank", "sequence", "ts_event"]
    else:
        sort_cols = ["session_date", "sequence", "ts_event"]

    # Sort ascending then keep='last' picks max lexicographically by sort cols
    cand = cand.sort_values(sort_cols, ascending=True, kind="mergesort")

    selected = cand.drop_duplicates(subset=["session_date"], keep="last")

    if "_final_rank" in selected.columns:
        selected = selected.drop(columns=["_final_rank"])

    # Stable output ordering by session_date (and then ts_event/sequence already monotone per group)
    selected = selected.sort_values(
        ["session_date"], ascending=True, kind="mergesort"
    ).reset_index(drop=True)

    diag = StatSelectionDiagnostics(
        stat_type=int(candidates.attrs.get("stat_type", -1)),
        source_rows_total=int(candidates.attrs.get("source_rows_total", 0)),
        candidate_rows_total=src_total,
        session_dates_total=int(counts.shape[0]),
        selected_rows=len(selected),
        session_dates_multiple_candidates_n=int(multi.shape[0]),
        session_dates_missing_n=0,  # filled by caller if they supply an expected calendar window
        session_dates_multiple_candidates_sample=multi_sample,
    )
    return selected, diag


# ----------------------------
# Public selection functions
# ----------------------------


def select_ts_ref_stat_daily(
    df: pd.DataFrame,
    *,
    stat_type: int,
    prefer_final: bool,
    session_date_of: Callable[[pd.Series], pd.Series],
) -> tuple[pd.DataFrame, StatSelectionDiagnostics]:
    """
    Select exactly one row per session_date for stat_types that are *intended*
    to be ts_ref-anchored, but may have missing ts_ref/trading_date in practice.

    Session-date derivation:
      1) Use df["trading_date"] when present and non-null (vendor/intended anchor).
      2) Fallback: derive from ts_event via session_date_of (calendar-backed).
    """
    _require_cols(df, ["stat_type", "ts_event", "sequence"])
    if "trading_date" not in df.columns:
        raise ValueError("daily_stats.selection: missing required column: trading_date")

    if prefer_final:
        _require_cols(df, ["is_final"])

    source_rows_total = len(df)
    cand = df[df["stat_type"] == stat_type].copy()
    cand.attrs["stat_type"] = stat_type
    cand.attrs["source_rows_total"] = source_rows_total

    # Always ensure session_date exists on the candidate frame before any early return
    cand["session_date"] = _coerce_session_date_series(cand["trading_date"])

    # Fallback: if vendor trading_date missing, derive from ts_event via calendar
    missing = cand["session_date"].isna()
    if missing.any():
        target_dtype = cand["session_date"].dtype

        values = session_date_of(cand.loc[missing, "ts_event"])
        values = pd.Series(values, index=cand.loc[missing].index)
        values = values.astype(target_dtype)

        cand.loc[missing, "session_date"] = values

    # Drop unmapped rows (still possible if calendar out-of-range or coercion failed)
    cand = cand[cand["session_date"].notna()].copy()

    # Ensure column exists even if empty
    if "session_date" not in cand.columns:
        cand["session_date"] = pd.Series([], dtype="object")

    selected, diag = _select_one_per_session_date(cand, prefer_final=prefer_final)
    return selected, diag


def select_event_time_stat_daily(
    df: pd.DataFrame,
    *,
    stat_type: int,
    session_date_of: Callable[[pd.Series], pd.Series],
) -> tuple[pd.DataFrame, StatSelectionDiagnostics]:
    _require_cols(df, ["stat_type", "ts_event", "sequence"])

    source_rows_total = len(df)
    cand = df[df["stat_type"] == stat_type].copy()
    cand.attrs["stat_type"] = stat_type
    cand.attrs["source_rows_total"] = source_rows_total

    # Always ensure session_date exists on the candidate frame before any early return
    if "session_date" not in cand.columns:
        cand["session_date"] = pd.Series([None] * len(cand), dtype="object")

    if cand.empty:
        # Return an empty *selected* frame with correct schema
        selected = cand.copy()
        diag = StatSelectionDiagnostics(
            stat_type=stat_type,
            source_rows_total=source_rows_total,
            candidate_rows_total=0,
            session_dates_total=0,
            selected_rows=0,
            session_dates_multiple_candidates_n=0,
            session_dates_missing_n=0,
            session_dates_multiple_candidates_sample=[],
        )
        return selected, diag

    # Map ts_event -> session_date and drop unmapped rows
    cand["session_date"] = session_date_of(cand["ts_event"])
    cand = cand[cand["session_date"].notna()].copy()

    if cand.empty:
        # All candidates unmapped -> empty selected
        selected = cand.copy()
        diag = StatSelectionDiagnostics(
            stat_type=stat_type,
            source_rows_total=source_rows_total,
            candidate_rows_total=0,  # or original candidate count; pick semantics you prefer
            session_dates_total=0,
            selected_rows=0,
            session_dates_multiple_candidates_n=0,
            session_dates_missing_n=0,
            session_dates_multiple_candidates_sample=[],
        )
        return selected, diag

    selected, diag = _select_one_per_session_date(cand, prefer_final=False)
    return selected, diag


# ----------------------------
# Composition: daily_stats surface
# ----------------------------


def build_daily_stats_surface(
    df: pd.DataFrame,
    *,
    session_date_of: Callable[[pd.Series], pd.Series],
) -> tuple[pd.DataFrame, DailyStatsSelectionDiagnostics]:
    """
    Build a daily surface from statistics_1d.

    Output rows are keyed by session_date, plus instrument identity columns that are
    carried through from the selected rows (instrument_id, publisher_id, dataset, raw_symbol if present).

    Columns produced (initial set):
      - settle_px, settle_is_final
      - open_px
      - high_px
      - low_px
      - fix_px, fix_is_final
      - open_interest_qty
      - cleared_volume_qty
    """
    _require_cols(df, ["stat_type", "ts_event", "sequence"])
    source_rows_total = len(df)
    # --- ts_ref anchored (with fallback to calendar)
    settle, d_settle = select_ts_ref_stat_daily(
        df, stat_type=3, prefer_final=True, session_date_of=session_date_of
    )
    fix, d_fix = select_ts_ref_stat_daily(
        df, stat_type=10, prefer_final=True, session_date_of=session_date_of
    )
    oi, d_oi = select_ts_ref_stat_daily(
        df, stat_type=9, prefer_final=False, session_date_of=session_date_of
    )
    clr, d_clr = select_ts_ref_stat_daily(
        df, stat_type=6, prefer_final=False, session_date_of=session_date_of
    )
    # --- event-time anchored
    opn, d_opn = select_event_time_stat_daily(
        df, stat_type=1, session_date_of=session_date_of
    )
    low, d_low = select_event_time_stat_daily(
        df, stat_type=4, session_date_of=session_date_of
    )
    high, d_high = select_event_time_stat_daily(
        df, stat_type=5, session_date_of=session_date_of
    )

    # helper to choose identity cols present
    ident_cols = [
        c
        for c in ["instrument_id", "publisher_id", "dataset", "raw_symbol"]
        if c in df.columns
    ]

    def _frame(
        selected: pd.DataFrame, *, prefix: str, value_col: str, keep_final: bool
    ) -> pd.DataFrame:
        cols = ["session_date"] + ident_cols
        out = selected[cols + [value_col]].copy()
        out = out.rename(columns={value_col: f"{prefix}"})
        if keep_final and "is_final" in selected.columns:
            out[f"{prefix}_is_final"] = selected["is_final"].astype("boolean")
        return out

    # settlement uses price
    f_settle = _frame(settle, prefix="settle_px", value_col="price", keep_final=True)
    f_fix = _frame(fix, prefix="fix_px", value_col="price", keep_final=True)
    f_open = _frame(opn, prefix="open_px", value_col="price", keep_final=False)
    f_low = _frame(low, prefix="low_px", value_col="price", keep_final=False)
    f_high = _frame(high, prefix="high_px", value_col="price", keep_final=False)

    # quantities
    if "quantity" not in df.columns:
        raise ValueError(
            "daily_stats.selection: expected quantity column for stat_type 6/9"
        )
    f_oi = _frame(
        oi, prefix="open_interest_qty", value_col="quantity", keep_final=False
    )
    f_clr = _frame(
        clr, prefix="cleared_volume_qty", value_col="quantity", keep_final=False
    )

    # outer-join everything on (session_date + identity)
    keys = ["session_date"] + ident_cols
    out = f_settle
    for part in [f_fix, f_open, f_high, f_low, f_oi, f_clr]:
        out = out.merge(part, on=keys, how="outer")

    # sort for stable output
    out = out.sort_values(keys).reset_index(drop=True)

    diag = DailyStatsSelectionDiagnostics(
        source_rows_total=source_rows_total,
        by_stat={
            3: d_settle,
            10: d_fix,
            1: d_opn,
            5: d_high,
            4: d_low,
            9: d_oi,
            6: d_clr,
        },
    )
    return out, diag
