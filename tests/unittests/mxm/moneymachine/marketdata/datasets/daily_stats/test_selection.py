from __future__ import annotations

import numpy as np
import pandas as pd

from mxm.moneymachine.marketdata.datasets.daily_stats.selection import (
    build_daily_stats_surface,
    select_event_time_stat_daily,
    select_ts_ref_stat_daily,
)

type RowValue = str | int | float | bool | None
type Row = dict[str, RowValue]


def _df(rows: list[Row]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    if "ts_event" in df.columns:
        df.loc[:, "ts_event"] = pd.to_datetime(
            df["ts_event"],
            utc=True,
            errors="raise",
        )
    return df


def _session_date_of(ts: pd.Series) -> pd.Series:
    mapping = {
        pd.Timestamp("2025-01-02T09:00:00Z"): np.datetime64("2025-01-02", "D"),
        pd.Timestamp("2025-01-02T10:00:00Z"): np.datetime64("2025-01-02", "D"),
        pd.Timestamp("2025-01-03T09:00:00Z"): np.datetime64("2025-01-03", "D"),
        pd.Timestamp("2025-01-03T10:00:00Z"): np.datetime64("2025-01-03", "D"),
    }
    s = pd.to_datetime(ts, utc=True, errors="coerce")
    return s.map(mapping).astype("object")


def test_select_ts_ref_prefers_final_even_if_lower_sequence() -> None:
    df = _df(
        [
            # same trading_date, two candidates: final has lower sequence
            {
                "stat_type": 3,
                "trading_date": "2025-01-02",
                "ts_event": "2025-01-02T20:00:00Z",
                "sequence": 10,
                "price": 100.0,
                "is_final": False,
            },
            {
                "stat_type": 3,
                "trading_date": "2025-01-02",
                "ts_event": "2025-01-02T21:00:00Z",
                "sequence": 5,
                "price": 101.0,
                "is_final": True,
            },
        ]
    )

    sel, diag = select_ts_ref_stat_daily(
        df, stat_type=3, prefer_final=True, session_date_of=_session_date_of
    )
    assert len(sel) == 1
    assert float(sel.iloc[0]["price"]) == 101.0
    assert bool(sel.iloc[0]["is_final"]) is True
    assert diag.session_dates_multiple_candidates_n == 1


def test_select_ts_ref_final_tie_break_by_sequence_then_ts_event() -> None:
    df = _df(
        [
            {
                "stat_type": 3,
                "trading_date": "2025-01-02",
                "ts_event": "2025-01-02T20:00:00Z",
                "sequence": 10,
                "price": 100.0,
                "is_final": True,
            },
            {
                "stat_type": 3,
                "trading_date": "2025-01-02",
                "ts_event": "2025-01-02T21:00:00Z",
                "sequence": 11,
                "price": 101.0,
                "is_final": True,
            },
        ]
    )
    sel, _ = select_ts_ref_stat_daily(
        df, stat_type=3, prefer_final=True, session_date_of=_session_date_of
    )
    assert float(sel.iloc[0]["price"]) == 101.0


def test_select_ts_ref_drops_null_trading_date() -> None:
    df = _df(
        [
            {
                "stat_type": 10,
                "trading_date": None,
                "ts_event": "2025-01-02T12:00:00Z",
                "sequence": 1,
                "price": 50.0,
                "is_final": True,
            }
        ]
    )
    sel, diag = select_ts_ref_stat_daily(
        df, stat_type=10, prefer_final=True, session_date_of=_session_date_of
    )
    assert len(sel) == 0
    assert diag.candidate_rows_total == 0


def test_select_event_time_uses_mapper_and_picks_latest_sequence() -> None:
    df = _df(
        [
            {
                "stat_type": 1,
                "ts_event": "2025-01-02T09:00:00Z",
                "sequence": 1,
                "price": 10.0,
            },
            {
                "stat_type": 1,
                "ts_event": "2025-01-02T10:00:00Z",
                "sequence": 2,
                "price": 11.0,
            },
        ]
    )
    sel, diag = select_event_time_stat_daily(
        df, stat_type=1, session_date_of=_session_date_of
    )
    assert len(sel) == 1
    assert float(sel.iloc[0]["price"]) == 11.0
    assert diag.session_dates_multiple_candidates_n == 1


def test_select_event_time_drops_unmapped() -> None:
    df = _df(
        [
            {
                "stat_type": 4,
                "ts_event": "2025-02-01T09:00:00Z",
                "sequence": 1,
                "price": 9.0,
            }
        ]
    )
    sel, _ = select_event_time_stat_daily(
        df, stat_type=4, session_date_of=_session_date_of
    )
    assert len(sel) == 0


def test_build_daily_stats_surface_outer_join_and_columns() -> None:
    df = _df(
        [
            # settlement day1
            {
                "stat_type": 3,
                "trading_date": "2025-01-02",
                "ts_event": "2025-01-02T21:00:00Z",
                "sequence": 10,
                "price": 100.0,
                "is_final": True,
                "instrument_id": 1,
                "publisher_id": 1,
                "dataset": "GLBX.MDP3",
                "raw_symbol": "ESZ5",
                "quantity": 0,
            },
            # open day1 (no ts_ref)
            {
                "stat_type": 1,
                "ts_event": "2025-01-02T09:00:00Z",
                "sequence": 1,
                "price": 99.0,
                "instrument_id": 1,
                "publisher_id": 1,
                "dataset": "GLBX.MDP3",
                "raw_symbol": "ESZ5",
                "quantity": 0,
            },
            # open interest day1 (ts_ref)
            {
                "stat_type": 9,
                "trading_date": "2025-01-02",
                "ts_event": "2025-01-02T22:00:00Z",
                "sequence": 2,
                "quantity": 123,
                "price": np.nan,
                "instrument_id": 1,
                "publisher_id": 1,
                "dataset": "GLBX.MDP3",
                "raw_symbol": "ESZ5",
            },
        ]
    )

    out, diag = build_daily_stats_surface(df, session_date_of=_session_date_of)

    assert "session_date" in out.columns
    assert "settle_px" in out.columns
    assert "open_px" in out.columns
    assert "open_interest_qty" in out.columns

    assert len(out) == 1
    row = out.iloc[0]
    assert float(row["settle_px"]) == 100.0
    assert float(row["open_px"]) == 99.0
    assert int(row["open_interest_qty"]) == 123

    # uniqueness on key
    assert (
        out.duplicated(
            subset=[
                "session_date",
                "instrument_id",
                "publisher_id",
                "dataset",
                "raw_symbol",
            ]
        ).sum()
        == 0
    )
    assert diag.source_rows_total == len(df)
