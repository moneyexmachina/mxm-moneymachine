from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pandas as pd

from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.marketdata.datasets.daily_mark.builder import build_daily_mark


@dataclass(frozen=True)
class FakeBusinessCalendar:
    labels_by_session_id: dict[int, object]

    def label_from_session_id(self, session_id: int) -> object:
        return self.labels_by_session_id[session_id]


def _daily_stats_df() -> pd.DataFrame:
    """
    Minimal canonical contract-level daily_stats-like frame for builder tests.

    Only includes columns actually consumed by builder.py.
    """
    return pd.DataFrame(
        {
            "trading_date": pd.to_datetime(
                [
                    "2025-01-02T00:00:00Z",
                    "2025-01-05T00:00:00Z",
                ],
                utc=True,
            ),
            "contract_id": ["CME.ESM2025", "CME.ESM2025"],
            "product_id": ["CME.ES", "CME.ES"],
            "instrument_id": [4916, 4916],
            "publisher_id": [1, 1],
            "dataset": ["GLBX.MDP3", "GLBX.MDP3"],
            "raw_symbol": ["ESM5", "ESM5"],
            "settle_px": [100.0, 101.5],
        }
    )


def test_build_daily_mark_builds_observed_settle_rows_from_matching_daily_stats() -> (
    None
):
    business_calendar = FakeBusinessCalendar(
        labels_by_session_id={
            0: pd.Timestamp("2025-01-02"),
            1: pd.Timestamp("2025-01-05"),
        }
    )
    daily_stats = _daily_stats_df()

    df, diag = build_daily_mark(
        contract_id="CME.ESM2025",
        session_ids=[0, 1],
        business_calendar=cast(MXMBusinessCalendar, business_calendar),
        daily_stats=daily_stats,
    )

    assert df["session_id"].tolist() == [0, 1]
    assert df["mark_source"].tolist() == ["observed_settle", "observed_settle"]
    assert df["mark_quality"].tolist() == ["final", "final"]
    assert df["mark_px"].tolist() == [100.0, 101.5]
    assert df["is_markable"].tolist() == [True, True]
    assert df["is_carried"].tolist() == [False, False]
    assert df["carry_streak"].tolist() == [0, 0]

    assert diag.contract_id == "CME.ESM2025"
    assert diag.sessions_total == 2
    assert diag.observed_settle_n == 2
    assert diag.observed_close_n == 0
    assert diag.carry_forward_n == 0
    assert diag.unavailable_n == 0
    assert diag.max_carry_streak == 0


def test_build_daily_mark_carries_forward_after_missing_observation() -> None:
    business_calendar = FakeBusinessCalendar(
        labels_by_session_id={
            0: pd.Timestamp("2025-01-02"),
            1: pd.Timestamp("2025-01-03"),
            2: pd.Timestamp("2025-01-04"),
        }
    )
    daily_stats = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(["2025-01-02T00:00:00Z"], utc=True),
            "contract_id": ["CME.ESM2025"],
            "product_id": ["CME.ES"],
            "instrument_id": [4916],
            "publisher_id": [1],
            "dataset": ["GLBX.MDP3"],
            "raw_symbol": ["ESM5"],
            "settle_px": [100.0],
        }
    )

    df, diag = build_daily_mark(
        contract_id="CME.ESM2025",
        session_ids=[0, 1, 2],
        business_calendar=cast(MXMBusinessCalendar, business_calendar),
        daily_stats=daily_stats,
    )

    assert df["session_id"].tolist() == [0, 1, 2]
    assert df["mark_source"].tolist() == [
        "observed_settle",
        "carry_forward",
        "carry_forward",
    ]
    assert df["mark_quality"].tolist() == ["final", "carried", "carried"]
    assert df["mark_px"].tolist() == [100.0, 100.0, 100.0]
    assert df["is_markable"].tolist() == [True, True, True]
    assert df["is_carried"].tolist() == [False, True, True]
    assert df["carry_streak"].tolist() == [0, 1, 2]

    assert diag.sessions_total == 3
    assert diag.observed_settle_n == 1
    assert diag.observed_close_n == 0
    assert diag.carry_forward_n == 2
    assert diag.unavailable_n == 0
    assert diag.max_carry_streak == 2


def test_build_daily_mark_returns_unavailable_before_first_observation() -> None:
    business_calendar = FakeBusinessCalendar(
        labels_by_session_id={
            0: pd.Timestamp("2025-01-01"),
            1: pd.Timestamp("2025-01-02"),
            2: pd.Timestamp("2025-01-03"),
        }
    )
    daily_stats = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(["2025-01-03T00:00:00Z"], utc=True),
            "contract_id": ["CME.ESM2025"],
            "product_id": ["CME.ES"],
            "instrument_id": [4916],
            "publisher_id": [1],
            "dataset": ["GLBX.MDP3"],
            "raw_symbol": ["ESM5"],
            "settle_px": [100.0],
        }
    )

    df, diag = build_daily_mark(
        contract_id="CME.ESM2025",
        session_ids=[0, 1, 2],
        business_calendar=cast(MXMBusinessCalendar, business_calendar),
        daily_stats=daily_stats,
    )

    assert df["session_id"].tolist() == [0, 1, 2]
    assert df["mark_source"].tolist() == [
        "unavailable",
        "unavailable",
        "observed_settle",
    ]
    assert df["mark_quality"].tolist() == [
        "unavailable",
        "unavailable",
        "final",
    ]
    assert pd.isna(df.loc[0, "mark_px"])
    assert pd.isna(df.loc[1, "mark_px"])
    assert df.loc[2, "mark_px"] == 100.0
    assert df["is_markable"].tolist() == [False, False, True]
    assert df["is_carried"].tolist() == [False, False, False]
    assert df["carry_streak"].tolist() == [0, 0, 0]

    assert diag.sessions_total == 3
    assert diag.observed_settle_n == 1
    assert diag.observed_close_n == 0
    assert diag.carry_forward_n == 0
    assert diag.unavailable_n == 2
    assert diag.max_carry_streak == 0


def test_build_daily_mark_populates_provenance_on_observed_rows_and_none_on_carried_rows() -> (
    None
):
    business_calendar = FakeBusinessCalendar(
        labels_by_session_id={
            0: pd.Timestamp("2025-01-02"),
            1: pd.Timestamp("2025-01-03"),
        }
    )
    daily_stats = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(["2025-01-02T00:00:00Z"], utc=True),
            "contract_id": ["CME.ESM2025"],
            "product_id": ["CME.ES"],
            "instrument_id": [4916],
            "publisher_id": [1],
            "dataset": ["GLBX.MDP3"],
            "raw_symbol": ["ESM5"],
            "settle_px": [100.0],
        }
    )

    df, _ = build_daily_mark(
        contract_id="CME.ESM2025",
        session_ids=[0, 1],
        business_calendar=cast(MXMBusinessCalendar, business_calendar),
        daily_stats=daily_stats,
    )

    observed = df.loc[df["session_id"] == 0].iloc[0]
    carried = df.loc[df["session_id"] == 1].iloc[0]

    assert observed["mark_source"] == "observed_settle"
    assert observed["source_trading_date"] == pd.Timestamp("2025-01-02T00:00:00")
    assert observed["instrument_id"] == 4916
    assert observed["source_dataset"] == "GLBX.MDP3"
    assert observed["source_publisher_id"] == 1
    assert observed["source_raw_symbol"] == "ESM5"

    assert carried["mark_source"] == "carry_forward"
    assert pd.isna(carried["source_trading_date"])
    assert pd.isna(carried["instrument_id"])
    assert pd.isna(carried["source_dataset"])
    assert pd.isna(carried["source_publisher_id"])
    assert pd.isna(carried["source_raw_symbol"])


def test_build_daily_mark_returns_correct_diagnostics_for_mixed_path() -> None:
    business_calendar = FakeBusinessCalendar(
        labels_by_session_id={
            0: pd.Timestamp("2025-01-01"),
            1: pd.Timestamp("2025-01-02"),
            2: pd.Timestamp("2025-01-03"),
            3: pd.Timestamp("2025-01-04"),
            4: pd.Timestamp("2025-01-05"),
        }
    )
    daily_stats = pd.DataFrame(
        {
            "trading_date": pd.to_datetime(
                [
                    "2025-01-02T00:00:00Z",
                    "2025-01-05T00:00:00Z",
                ],
                utc=True,
            ),
            "contract_id": ["CME.ESM2025", "CME.ESM2025"],
            "product_id": ["CME.ES", "CME.ES"],
            "instrument_id": [4916, 4916],
            "publisher_id": [1, 1],
            "dataset": ["GLBX.MDP3", "GLBX.MDP3"],
            "raw_symbol": ["ESM5", "ESM5"],
            "settle_px": [100.0, 101.5],
        }
    )

    _, diag = build_daily_mark(
        contract_id="CME.ESM2025",
        session_ids=[0, 1, 2, 3, 4],
        business_calendar=cast(MXMBusinessCalendar, business_calendar),
        daily_stats=daily_stats,
    )

    assert diag.contract_id == "CME.ESM2025"
    assert diag.sessions_total == 5
    assert diag.observed_settle_n == 2
    assert diag.observed_close_n == 0
    assert diag.carry_forward_n == 2
    assert diag.unavailable_n == 1
    assert diag.max_carry_streak == 2


def test_build_daily_mark_supports_empty_session_ids() -> None:
    business_calendar = FakeBusinessCalendar(labels_by_session_id={})
    daily_stats = _daily_stats_df()

    df, diag = build_daily_mark(
        contract_id="CME.ESM2025",
        session_ids=[],
        business_calendar=cast(MXMBusinessCalendar, business_calendar),
        daily_stats=daily_stats,
    )

    assert df.empty
    assert list(df.columns) == []
    assert diag.contract_id == "CME.ESM2025"
    assert diag.sessions_total == 0
    assert diag.observed_settle_n == 0
    assert diag.observed_close_n == 0
    assert diag.carry_forward_n == 0
    assert diag.unavailable_n == 0
    assert diag.max_carry_streak == 0
