from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class DailyMarkObservation:
    """
    Memory-less observation candidate for one MXM business session.

    This object represents what the source layer can currently observe for a
    given `(contract_id, session_id)` before any carry-forward policy is applied.

    Interpretation
    --------------
    - `settle_px` and `close_px` are current-session candidate observations.
    - provenance fields describe the current observed source row, if any.
    - this object carries no historical state and does not itself encode
      any valuation decision.
    """

    session_id: int
    contract_id: str

    settle_px: float | None
    close_px: float | None

    source_trading_date: object | None = None
    instrument_id: int | None = None
    source_dataset: str | None = None
    source_publisher_id: int | None = None
    source_raw_symbol: str | None = None


@dataclass(frozen=True)
class DailyMarkState:
    """
    Stateful valuation memory carried across MXM business sessions.

    This is the minimal recursive state required to implement carry-forward
    valuation semantics over an ordered session domain.

    Interpretation
    --------------
    - `last_mark_px` is the most recent authoritative mark assigned so far.
    - `has_authoritative_mark` indicates whether such a mark exists at all.
    - `carry_streak` counts consecutive carry-forward assignments up to the
      current state.
    """

    last_mark_px: float | None
    has_authoritative_mark: bool
    carry_streak: int


@dataclass(frozen=True)
class DailyMarkRow:
    """
    Authoritative daily_mark row emitted for one `(contract_id, session_id)`.

    This is the row-level semantic output of the valuation policy before it is
    converted into dataframe / parquet form.
    """

    session_id: int
    contract_id: str

    instrument_id: int | None
    mark_px: float | None
    mark_source: str
    mark_quality: str
    is_markable: bool
    is_carried: bool
    carry_streak: int

    source_trading_date: object | None
    source_dataset: str | None
    source_publisher_id: int | None
    source_raw_symbol: str | None


def initial_daily_mark_state() -> DailyMarkState:
    """
    Return the initial state for daily_mark construction.

    Initial semantics:
    - no prior authoritative mark exists
    - carry streak is zero
    """
    return DailyMarkState(
        last_mark_px=None,
        has_authoritative_mark=False,
        carry_streak=0,
    )


def _is_observed_mark_acceptable(px: float | None) -> bool:
    """
    Return True iff an observed price candidate is acceptable as a current mark.

    V1 policy:
    - acceptable means simply: non-null
    - no further economic or vendor-quality filtering is applied here
    """
    return px is not None and not pd.isna(px)


def step_daily_mark(
    *,
    prev_state: DailyMarkState,
    obs: DailyMarkObservation,
) -> tuple[DailyMarkState, DailyMarkRow]:
    """
    Apply the one-step daily_mark valuation policy.

    Policy order (V1)
    -----------------
    1. If acceptable current settle is observed, use it.
    2. Else if acceptable current close is observed, use it.
    3. Else if a prior authoritative mark exists, carry it forward.
    4. Else mark the session as unavailable.

    Returns
    -------
    (next_state, row)
        `next_state` is the recursive state to feed into the next session.
        `row` is the authoritative daily_mark row for the current session.
    """
    if obs.session_id < 0:
        raise ValueError(
            f"daily_mark.policy: session_id must be non-negative, got {obs.session_id}"
        )
    if prev_state.carry_streak < 0:
        raise ValueError(
            "daily_mark.policy: prev_state.carry_streak must be non-negative"
        )

    # 1. Preferred: current observed settle
    if _is_observed_mark_acceptable(obs.settle_px):
        mark_px = obs.settle_px
        row = DailyMarkRow(
            session_id=obs.session_id,
            contract_id=obs.contract_id,
            instrument_id=obs.instrument_id,
            mark_px=mark_px,
            mark_source="observed_settle",
            mark_quality="final",
            is_markable=True,
            is_carried=False,
            carry_streak=0,
            source_trading_date=obs.source_trading_date,
            source_dataset=obs.source_dataset,
            source_publisher_id=obs.source_publisher_id,
            source_raw_symbol=obs.source_raw_symbol,
        )
        next_state = DailyMarkState(
            last_mark_px=mark_px,
            has_authoritative_mark=True,
            carry_streak=0,
        )
        return next_state, row

    # 2. Fallback: current observed close
    if _is_observed_mark_acceptable(obs.close_px):
        mark_px = obs.close_px
        row = DailyMarkRow(
            session_id=obs.session_id,
            contract_id=obs.contract_id,
            instrument_id=obs.instrument_id,
            mark_px=mark_px,
            mark_source="observed_close",
            mark_quality="observed_fallback",
            is_markable=True,
            is_carried=False,
            carry_streak=0,
            source_trading_date=obs.source_trading_date,
            source_dataset=obs.source_dataset,
            source_publisher_id=obs.source_publisher_id,
            source_raw_symbol=obs.source_raw_symbol,
        )
        next_state = DailyMarkState(
            last_mark_px=mark_px,
            has_authoritative_mark=True,
            carry_streak=0,
        )
        return next_state, row

    # 3. Carry forward prior authoritative mark
    if prev_state.has_authoritative_mark:
        row = DailyMarkRow(
            session_id=obs.session_id,
            contract_id=obs.contract_id,
            instrument_id=None,
            mark_px=prev_state.last_mark_px,
            mark_source="carry_forward",
            mark_quality="carried",
            is_markable=True,
            is_carried=True,
            carry_streak=prev_state.carry_streak + 1,
            source_trading_date=None,
            source_dataset=None,
            source_publisher_id=None,
            source_raw_symbol=None,
        )
        next_state = DailyMarkState(
            last_mark_px=prev_state.last_mark_px,
            has_authoritative_mark=True,
            carry_streak=prev_state.carry_streak + 1,
        )
        return next_state, row

    # 4. No current observation and no prior authoritative mark
    row = DailyMarkRow(
        session_id=obs.session_id,
        contract_id=obs.contract_id,
        instrument_id=None,
        mark_px=None,
        mark_source="unavailable",
        mark_quality="unavailable",
        is_markable=False,
        is_carried=False,
        carry_streak=0,
        source_trading_date=None,
        source_dataset=None,
        source_publisher_id=None,
        source_raw_symbol=None,
    )
    next_state = DailyMarkState(
        last_mark_px=None,
        has_authoritative_mark=False,
        carry_streak=0,
    )
    return next_state, row
