from __future__ import annotations

import pytest

from mxm.v1.marketdata.datasets.daily_mark.policy import (
    DailyMarkObservation,
    DailyMarkState,
    initial_daily_mark_state,
    step_daily_mark,
)


def _obs(
    *,
    session_id: int = 0,
    contract_id: str = "CME.ESM2025",
    settle_px: float | None = None,
    close_px: float | None = None,
    source_trading_date: object | None = "2025-01-02",
    instrument_id: int | None = 4916,
    source_dataset: str | None = "GLBX.MDP3",
    source_publisher_id: int | None = 1,
    source_raw_symbol: str | None = "ESM5",
) -> DailyMarkObservation:
    return DailyMarkObservation(
        session_id=session_id,
        contract_id=contract_id,
        settle_px=settle_px,
        close_px=close_px,
        source_trading_date=source_trading_date,
        instrument_id=instrument_id,
        source_dataset=source_dataset,
        source_publisher_id=source_publisher_id,
        source_raw_symbol=source_raw_symbol,
    )


def _state(
    *,
    last_mark_px: float | None = None,
    has_authoritative_mark: bool = False,
    carry_streak: int = 0,
) -> DailyMarkState:
    return DailyMarkState(
        last_mark_px=last_mark_px,
        has_authoritative_mark=has_authoritative_mark,
        carry_streak=carry_streak,
    )


def test_initial_daily_mark_state_is_empty() -> None:
    state = initial_daily_mark_state()

    assert state.last_mark_px is None
    assert state.has_authoritative_mark is False
    assert state.carry_streak == 0


def test_step_daily_mark_prefers_observed_settle_over_close() -> None:
    prev_state = _state(
        last_mark_px=99.0,
        has_authoritative_mark=True,
        carry_streak=2,
    )
    obs = _obs(
        session_id=10,
        settle_px=100.5,
        close_px=100.25,
    )

    next_state, row = step_daily_mark(
        prev_state=prev_state,
        obs=obs,
    )

    assert row.session_id == 10
    assert row.contract_id == "CME.ESM2025"
    assert row.instrument_id == 4916
    assert row.mark_px == 100.5
    assert row.mark_source == "observed_settle"
    assert row.mark_quality == "final"
    assert row.is_markable is True
    assert row.is_carried is False
    assert row.carry_streak == 0

    assert row.source_trading_date == "2025-01-02"
    assert row.source_dataset == "GLBX.MDP3"
    assert row.source_publisher_id == 1
    assert row.source_raw_symbol == "ESM5"

    assert next_state.last_mark_px == 100.5
    assert next_state.has_authoritative_mark is True
    assert next_state.carry_streak == 0


def test_step_daily_mark_uses_observed_close_when_settle_missing() -> None:
    prev_state = _state(
        last_mark_px=99.0,
        has_authoritative_mark=True,
        carry_streak=1,
    )
    obs = _obs(
        session_id=11,
        settle_px=None,
        close_px=100.25,
    )

    next_state, row = step_daily_mark(
        prev_state=prev_state,
        obs=obs,
    )

    assert row.session_id == 11
    assert row.mark_px == 100.25
    assert row.mark_source == "observed_close"
    assert row.mark_quality == "observed_fallback"
    assert row.is_markable is True
    assert row.is_carried is False
    assert row.carry_streak == 0

    assert row.source_trading_date == "2025-01-02"
    assert row.instrument_id == 4916
    assert row.source_dataset == "GLBX.MDP3"
    assert row.source_publisher_id == 1
    assert row.source_raw_symbol == "ESM5"

    assert next_state.last_mark_px == 100.25
    assert next_state.has_authoritative_mark is True
    assert next_state.carry_streak == 0


def test_step_daily_mark_carries_forward_when_no_current_observation() -> None:
    prev_state = _state(
        last_mark_px=101.0,
        has_authoritative_mark=True,
        carry_streak=2,
    )
    obs = _obs(
        session_id=12,
        settle_px=None,
        close_px=None,
        source_trading_date=None,
        instrument_id=None,
        source_dataset=None,
        source_publisher_id=None,
        source_raw_symbol=None,
    )

    next_state, row = step_daily_mark(
        prev_state=prev_state,
        obs=obs,
    )

    assert row.session_id == 12
    assert row.mark_px == 101.0
    assert row.mark_source == "carry_forward"
    assert row.mark_quality == "carried"
    assert row.is_markable is True
    assert row.is_carried is True
    assert row.carry_streak == 3

    assert row.instrument_id is None
    assert row.source_trading_date is None
    assert row.source_dataset is None
    assert row.source_publisher_id is None
    assert row.source_raw_symbol is None

    assert next_state.last_mark_px == 101.0
    assert next_state.has_authoritative_mark is True
    assert next_state.carry_streak == 3


def test_step_daily_mark_returns_unavailable_when_no_observation_and_no_history() -> (
    None
):
    prev_state = initial_daily_mark_state()
    obs = _obs(
        session_id=13,
        settle_px=None,
        close_px=None,
        source_trading_date=None,
        instrument_id=None,
        source_dataset=None,
        source_publisher_id=None,
        source_raw_symbol=None,
    )

    next_state, row = step_daily_mark(
        prev_state=prev_state,
        obs=obs,
    )

    assert row.session_id == 13
    assert row.mark_px is None
    assert row.mark_source == "unavailable"
    assert row.mark_quality == "unavailable"
    assert row.is_markable is False
    assert row.is_carried is False
    assert row.carry_streak == 0

    assert row.instrument_id is None
    assert row.source_trading_date is None
    assert row.source_dataset is None
    assert row.source_publisher_id is None
    assert row.source_raw_symbol is None

    assert next_state.last_mark_px is None
    assert next_state.has_authoritative_mark is False
    assert next_state.carry_streak == 0


def test_step_daily_mark_carry_streak_increments_across_consecutive_carries() -> None:
    state0 = initial_daily_mark_state()

    state1, row1 = step_daily_mark(
        prev_state=state0,
        obs=_obs(session_id=20, settle_px=100.0, close_px=None),
    )
    state2, row2 = step_daily_mark(
        prev_state=state1,
        obs=_obs(
            session_id=21,
            settle_px=None,
            close_px=None,
            source_trading_date=None,
            instrument_id=None,
            source_dataset=None,
            source_publisher_id=None,
            source_raw_symbol=None,
        ),
    )
    state3, row3 = step_daily_mark(
        prev_state=state2,
        obs=_obs(
            session_id=22,
            settle_px=None,
            close_px=None,
            source_trading_date=None,
            instrument_id=None,
            source_dataset=None,
            source_publisher_id=None,
            source_raw_symbol=None,
        ),
    )

    assert row1.mark_source == "observed_settle"
    assert row1.carry_streak == 0

    assert row2.mark_source == "carry_forward"
    assert row2.carry_streak == 1

    assert row3.mark_source == "carry_forward"
    assert row3.carry_streak == 2

    assert state3.last_mark_px == 100.0
    assert state3.has_authoritative_mark is True
    assert state3.carry_streak == 2


def test_step_daily_mark_resets_carry_streak_after_new_observed_mark() -> None:
    state0 = initial_daily_mark_state()

    state1, row1 = step_daily_mark(
        prev_state=state0,
        obs=_obs(session_id=30, settle_px=100.0, close_px=None),
    )
    state2, row2 = step_daily_mark(
        prev_state=state1,
        obs=_obs(
            session_id=31,
            settle_px=None,
            close_px=None,
            source_trading_date=None,
            instrument_id=None,
            source_dataset=None,
            source_publisher_id=None,
            source_raw_symbol=None,
        ),
    )
    state3, row3 = step_daily_mark(
        prev_state=state2,
        obs=_obs(
            session_id=32,
            settle_px=None,
            close_px=None,
            source_trading_date=None,
            instrument_id=None,
            source_dataset=None,
            source_publisher_id=None,
            source_raw_symbol=None,
        ),
    )
    state4, row4 = step_daily_mark(
        prev_state=state3,
        obs=_obs(session_id=33, settle_px=None, close_px=101.25),
    )

    assert row1.mark_source == "observed_settle"
    assert row2.mark_source == "carry_forward"
    assert row2.carry_streak == 1
    assert row3.mark_source == "carry_forward"
    assert row3.carry_streak == 2

    assert row4.mark_source == "observed_close"
    assert row4.mark_quality == "observed_fallback"
    assert row4.mark_px == 101.25
    assert row4.is_carried is False
    assert row4.carry_streak == 0

    assert state4.last_mark_px == 101.25
    assert state4.has_authoritative_mark is True
    assert state4.carry_streak == 0


def test_step_daily_mark_rejects_negative_session_id() -> None:
    prev_state = initial_daily_mark_state()
    obs = _obs(session_id=-1, settle_px=100.0)

    with pytest.raises(
        ValueError,
        match=r"session_id must be non-negative",
    ):
        _ = step_daily_mark(
            prev_state=prev_state,
            obs=obs,
        )


def test_step_daily_mark_rejects_negative_prev_carry_streak() -> None:
    prev_state = _state(
        last_mark_px=100.0,
        has_authoritative_mark=True,
        carry_streak=-1,
    )
    obs = _obs(session_id=40, settle_px=None, close_px=None)

    with pytest.raises(
        ValueError,
        match=r"prev_state\.carry_streak must be non-negative",
    ):
        _ = step_daily_mark(
            prev_state=prev_state,
            obs=obs,
        )


def test_step_daily_mark_treats_nan_settle_as_missing() -> None:
    prev_state = initial_daily_mark_state()
    obs = _obs(session_id=1, settle_px=float("nan"), close_px=None)

    next_state, row = step_daily_mark(prev_state=prev_state, obs=obs)

    assert row.mark_source == "unavailable"
    assert row.mark_px is None
    assert row.is_markable is False
    assert next_state.has_authoritative_mark is False
