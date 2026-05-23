from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

import pandas as pd
from numpy import datetime64

from mxm.moneymachine.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.moneymachine.marketdata.datasets.daily_mark.policy import (
    DailyMarkObservation,
    DailyMarkRow,
    DailyMarkState,
    initial_daily_mark_state,
    step_daily_mark,
)
from mxm.moneymachine.marketdata.schema.daily_mark import coerce_daily_mark

# ----------------------------
# Diagnostics
# ----------------------------


@dataclass(frozen=True)
class DailyMarkBuildDiagnostics:
    contract_id: str
    sessions_total: int
    observed_settle_n: int
    observed_close_n: int
    carry_forward_n: int
    unavailable_n: int
    max_carry_streak: int


# ----------------------------
# Helpers
# ----------------------------


def _require_cols(df: pd.DataFrame, cols: list[str]) -> None:
    missing = [c for c in cols if c not in df.columns]
    if missing:
        raise ValueError(f"daily_mark.builder: missing required columns: {missing}")


def _build_daily_stats_lookup(df: pd.DataFrame) -> dict[pd.Timestamp, pd.Series]:
    """
    Build lookup: trading_date -> row

    Assumes:
    - one row per trading_date (validated upstream)
    """
    if df.empty:
        return {}

    _require_cols(df, ["trading_date"])

    # trading_date already normalized UTC timestamps
    return {row["trading_date"]: row for _, row in df.iterrows()}


def _extract_observation(
    *,
    session_id: int,
    contract_id: str,
    trading_date: pd.Timestamp,
    lookup: dict[pd.Timestamp, pd.Series],
) -> DailyMarkObservation:
    """
    Extract observation for a single session_id using trading_date lookup.
    """
    row = lookup.get(trading_date)

    if row is None:
        return DailyMarkObservation(
            session_id=session_id,
            contract_id=contract_id,
            settle_px=None,
            close_px=None,
            source_trading_date=None,
            instrument_id=None,
            source_dataset=None,
            source_publisher_id=None,
            source_raw_symbol=None,
        )

    return DailyMarkObservation(
        session_id=session_id,
        contract_id=contract_id,
        settle_px=row.get("settle_px"),
        close_px=None,  # not present in daily_stats v1
        source_trading_date=row.get("trading_date"),
        instrument_id=row.get("instrument_id"),
        source_dataset=row.get("dataset"),
        source_publisher_id=row.get("publisher_id"),
        source_raw_symbol=row.get("raw_symbol"),
    )


def _rows_to_frame(rows: list[DailyMarkRow]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame()

    df = pd.DataFrame([r.__dict__ for r in rows])
    return coerce_daily_mark(df, ensure_column_order=True)


def _session_label_to_trading_date(label: datetime64) -> pd.Timestamp:
    """
    Convert an MXM business-session day label into the canonical daily_stats
    trading_date lookup representation: tz-aware UTC midnight timestamp.
    """
    ts = pd.Timestamp(label)
    return ts.tz_localize("UTC").normalize()


# ----------------------------
# Builder
# ----------------------------


def build_daily_mark(
    *,
    contract_id: str,
    session_ids: Iterable[int],
    business_calendar: MXMBusinessCalendar,
    daily_stats: pd.DataFrame,
) -> tuple[pd.DataFrame, DailyMarkBuildDiagnostics]:
    """
    Build curated daily_mark dataset for a single contract.

    Parameters
    ----------
    contract_id
        Contract identifier.

    session_ids
        Ordered sequence of MXM business session_ids.

    business_calendar
        Provides label_of(session_id) -> UTC day label.

    daily_stats
        Canonical contract-level daily_stats dataframe.

    Returns
    -------
    (df, diagnostics)
    """

    session_ids = list(session_ids)

    lookup = _build_daily_stats_lookup(daily_stats)

    state: DailyMarkState = initial_daily_mark_state()
    rows: list[DailyMarkRow] = []

    observed_settle_n = 0
    observed_close_n = 0
    carry_forward_n = 0
    unavailable_n = 0
    max_carry_streak = 0

    for sid in session_ids:
        trading_date = _session_label_to_trading_date(
            business_calendar.label_from_session_id(sid)
        )

        obs = _extract_observation(
            session_id=sid,
            contract_id=contract_id,
            trading_date=trading_date,
            lookup=lookup,
        )

        state, row = step_daily_mark(
            prev_state=state,
            obs=obs,
        )

        rows.append(row)

        # diagnostics accounting
        if row.mark_source == "observed_settle":
            observed_settle_n += 1
        elif row.mark_source == "observed_close":
            observed_close_n += 1
        elif row.mark_source == "carry_forward":
            carry_forward_n += 1
        elif row.mark_source == "unavailable":
            unavailable_n += 1

        if row.carry_streak > max_carry_streak:
            max_carry_streak = row.carry_streak

    df = _rows_to_frame(rows)

    diag = DailyMarkBuildDiagnostics(
        contract_id=contract_id,
        sessions_total=len(session_ids),
        observed_settle_n=observed_settle_n,
        observed_close_n=observed_close_n,
        carry_forward_n=carry_forward_n,
        unavailable_n=unavailable_n,
        max_carry_streak=max_carry_streak,
    )

    return df, diag
