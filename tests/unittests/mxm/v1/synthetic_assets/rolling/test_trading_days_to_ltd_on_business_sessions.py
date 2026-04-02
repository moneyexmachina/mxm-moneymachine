from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

import numpy as np
import pytest

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.synthetic_assets.rolling.trading_days_to_ltd_on_business_sessions import (
    TradingDaysToLTDOnBusinessSessions,
    UnknownContractId,
    build_trading_days_to_ltd_on_business_sessions,
)

# -----------------------------------------------------------------------------
# Minimal fakes for RefDataAPI objects
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeContract:
    last_trading_day: date


class _FakeRefDataAPI:
    """
    Minimal surface used by build_trading_days_to_ltd_on_business_sessions.

    Only method required:
      - get_contract_by_id(contract_id) -> contract or None
    """

    def __init__(self, contracts: dict[str, _FakeContract]) -> None:
        self._contracts = contracts

    def get_contract_by_id(self, contract_id: str) -> Optional[_FakeContract]:
        return self._contracts.get(contract_id)


# -----------------------------------------------------------------------------
# Calendars: (1) deterministic oracle, (2) spy for interaction tests
# -----------------------------------------------------------------------------


class _DeterministicCalendar:
    """
    Tiny deterministic calendar implementing the definition:

        trading_days_to_ltd = idx(ltd) - idx(asof)

    Used as a functional oracle.
    """

    def __init__(self, trading_days: list[str]) -> None:
        self.trading_days = np.array(trading_days, dtype="datetime64[D]")
        self._idx = {d: i for i, d in enumerate(self.trading_days.tolist())}

    def bdays_to_ltd(
        self,
        asof,
        ltd,
        *,
        strict: bool = True,
        return_projected_flag: bool = False,
        **_kwargs,
    ):
        a = np.asarray(asof, dtype="datetime64[D]")
        l = np.asarray(ltd, dtype="datetime64[D]")
        if a.shape != l.shape:
            raise ValueError("asof/ltd shape mismatch")

        out = np.empty(a.shape, dtype=np.int64)
        a_flat = a.ravel().tolist()
        l_flat = l.ravel().tolist()

        for k, (ai, li) in enumerate(zip(a_flat, l_flat)):
            if strict:
                if ai not in self._idx:
                    raise ValueError(f"asof {ai} not in trading_days")
                if li not in self._idx:
                    raise ValueError(f"ltd {li} not in trading_days")
            out.ravel()[k] = int(self._idx[li] - self._idx[ai])

        if return_projected_flag:
            return out, np.zeros_like(out, dtype=bool)
        return out


class _SpyCalendar:
    """
    Spy that records the call inputs and returns a deterministic sentinel.

    Used to verify that build_trading_days_to_ltd_on_business_sessions calls
    bdays_to_ltd with the correct mapped trading sessions, LTD array, and
    keyword arguments.
    """

    def __init__(self, trading_days: list[str]) -> None:
        self.trading_days = np.array(trading_days, dtype="datetime64[D]")
        self.calls: list[tuple[np.ndarray, np.ndarray, dict]] = []

    def bdays_to_ltd(self, asof, ltd, **kwargs):
        a = np.asarray(asof, dtype="datetime64[D]")
        l = np.asarray(ltd, dtype="datetime64[D]")
        self.calls.append((a, l, dict(kwargs)))
        return np.arange(a.size, dtype=np.int64).reshape(a.shape)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _days(*xs: str) -> np.ndarray:
    return np.array(xs, dtype="datetime64[D]")


def _mk_service_and_patch_calendar(
    monkeypatch,
    *,
    refdata,
    calendar,
) -> TradingCalendarService:
    cal_svc = TradingCalendarService(refdata_api=refdata)

    def _calendar_for_product(self: TradingCalendarService, _product_id: str):
        return calendar

    monkeypatch.setattr(
        TradingCalendarService,
        "calendar_for_product",
        _calendar_for_product,
    )
    return cal_svc


# -----------------------------------------------------------------------------
# Dataclass model tests
# -----------------------------------------------------------------------------


def test_trading_days_to_ltd_on_business_sessions_accepts_valid_payload() -> None:
    out = TradingDaysToLTDOnBusinessSessions(
        product_id="ANY",
        sessions=_days("2026-03-18", "2026-03-19", "2026-03-20"),
        contract_ids=["C1", "C1", "C2"],
        trading_days_to_ltd=np.array([2, 1, 3], dtype=np.int64),
    )

    assert out.product_id == "ANY"
    assert out.sessions.dtype == np.dtype("datetime64[D]")
    assert out.trading_days_to_ltd.dtype == np.dtype("int64")


def test_trading_days_to_ltd_on_business_sessions_rejects_length_mismatch() -> None:
    with pytest.raises(
        ValueError, match="sessions and contract_ids must have equal length"
    ):
        TradingDaysToLTDOnBusinessSessions(
            product_id="ANY",
            sessions=_days("2026-03-18", "2026-03-19"),
            contract_ids=["C1"],
            trading_days_to_ltd=np.array([2, 1], dtype=np.int64),
        )


def test_trading_days_to_ltd_on_business_sessions_rejects_values_length_mismatch() -> (
    None
):
    with pytest.raises(
        ValueError,
        match="sessions and trading_days_to_ltd must have equal length",
    ):
        TradingDaysToLTDOnBusinessSessions(
            product_id="ANY",
            sessions=_days("2026-03-18", "2026-03-19"),
            contract_ids=["C1", "C1"],
            trading_days_to_ltd=np.array([2], dtype=np.int64),
        )


def test_trading_days_to_ltd_on_business_sessions_casts_values_to_int64() -> None:
    out = TradingDaysToLTDOnBusinessSessions(
        product_id="ANY",
        sessions=_days("2026-03-18", "2026-03-19"),
        contract_ids=["C1", "C1"],
        trading_days_to_ltd=np.array([2, 1], dtype=np.int32),
    )

    assert out.trading_days_to_ltd.dtype == np.dtype("int64")


# -----------------------------------------------------------------------------
# Functional / semantic tests
# -----------------------------------------------------------------------------


def test_build_trading_days_to_ltd_on_business_sessions_functional_oracle(
    monkeypatch,
) -> None:
    """
    Functional test under controlled inputs.

    Verifies:
      - each business session is mapped to the prev trading session
      - LTD is resolved per aligned contract_id
      - output is indexed by business-session support
      - values are counted in trading-calendar space
    """
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
            "C2": _FakeContract(last_trading_day=date(2026, 6, 19)),
        }
    )

    cal = _DeterministicCalendar(
        trading_days=[
            "2026-03-18",
            "2026-03-19",
            "2026-03-20",
            "2026-03-23",
            "2026-03-24",
            "2026-06-19",
        ]
    )

    cal_svc = _mk_service_and_patch_calendar(monkeypatch, refdata=ref, calendar=cal)

    # Note the weekend-like gap from 03-20 -> 03-23 in trading days.
    # Business-session support includes a Saturday-like label that should map
    # back to 03-20 under how="prev".
    sessions = _days(
        "2026-03-18",
        "2026-03-19",
        "2026-03-21",
        "2026-03-23",
        "2026-03-24",
    )
    contract_ids = ["C1", "C1", "C2", "C2", "C2"]

    out = build_trading_days_to_ltd_on_business_sessions(
        product_id="ANY",
        sessions=sessions,
        contract_ids=contract_ids,
        calendar_service=cal_svc,
        refdata_api=ref,
    )

    assert out.sessions.tolist() == sessions.tolist()
    assert out.contract_ids == contract_ids
    assert out.trading_days_to_ltd.dtype == np.dtype("int64")

    # Prev-trading-session mapping:
    # 03-18 -> 03-18 (idx 0)
    # 03-19 -> 03-19 (idx 1)
    # 03-21 -> 03-20 (idx 2)
    # 03-23 -> 03-23 (idx 3)
    # 03-24 -> 03-24 (idx 4)
    #
    # LTD indices:
    # C1 ltd=03-20 -> idx 2
    # C2 ltd=06-19 -> idx 5
    #
    # Distances:
    # 03-18/C1 -> 2-0 = 2
    # 03-19/C1 -> 2-1 = 1
    # 03-21/C2 -> 5-2 = 3
    # 03-23/C2 -> 5-3 = 2
    # 03-24/C2 -> 5-4 = 1
    assert out.trading_days_to_ltd.tolist() == [2, 1, 3, 2, 1]


def test_build_trading_days_to_ltd_on_business_sessions_interaction_calls_calendar_correctly(
    monkeypatch,
) -> None:
    """
    Interaction test: verifies correct usage of the trading calendar API.

    We assert only the public contract:
      - asof array equals business sessions mapped to prev trading sessions
      - ltd array equals per-session LTD derived from contract_ids
      - kwargs include strict=True and return_projected_flag=False
    """
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
            "C2": _FakeContract(last_trading_day=date(2026, 6, 19)),
        }
    )

    spy = _SpyCalendar(
        trading_days=[
            "2026-03-18",
            "2026-03-19",
            "2026-03-20",
            "2026-03-23",
            "2026-06-19",
        ]
    )
    cal_svc = _mk_service_and_patch_calendar(monkeypatch, refdata=ref, calendar=spy)

    sessions = _days("2026-03-18", "2026-03-21", "2026-03-23")
    contract_ids = ["C1", "C1", "C2"]

    out = build_trading_days_to_ltd_on_business_sessions(
        product_id="ANY",
        sessions=sessions,
        contract_ids=contract_ids,
        calendar_service=cal_svc,
        refdata_api=ref,
    )

    assert len(spy.calls) == 1

    asof, ltd, kwargs = spy.calls[0]

    # 03-21 maps back to 03-20 under how="prev"
    expected_asof = np.array(
        ["2026-03-18", "2026-03-20", "2026-03-23"],
        dtype="datetime64[D]",
    )
    assert asof.tolist() == expected_asof.tolist()

    expected_ltd = np.array(
        ["2026-03-20", "2026-03-20", "2026-06-19"],
        dtype="datetime64[D]",
    )
    assert ltd.tolist() == expected_ltd.tolist()

    assert kwargs.get("strict") is True
    assert kwargs.get("return_projected_flag") is False

    # Spy returns sentinel [0, 1, 2]
    assert out.trading_days_to_ltd.tolist() == [0, 1, 2]


def test_build_trading_days_to_ltd_on_business_sessions_raises_on_unknown_contract_id(
    monkeypatch,
) -> None:
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
        }
    )

    cal = _DeterministicCalendar(
        trading_days=["2026-03-18", "2026-03-19", "2026-03-20"]
    )
    cal_svc = _mk_service_and_patch_calendar(monkeypatch, refdata=ref, calendar=cal)

    sessions = _days("2026-03-18", "2026-03-19")
    contract_ids = ["C1", "C_UNKNOWN"]

    with pytest.raises(UnknownContractId, match="Unknown contract_id"):
        build_trading_days_to_ltd_on_business_sessions(
            product_id="ANY",
            sessions=sessions,
            contract_ids=contract_ids,
            calendar_service=cal_svc,
            refdata_api=ref,
        )


def test_build_trading_days_to_ltd_on_business_sessions_raises_on_length_mismatch(
    monkeypatch,
) -> None:
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
        }
    )

    cal = _DeterministicCalendar(
        trading_days=["2026-03-18", "2026-03-19", "2026-03-20"]
    )
    cal_svc = _mk_service_and_patch_calendar(monkeypatch, refdata=ref, calendar=cal)

    with pytest.raises(
        ValueError,
        match="sessions and contract_ids must have equal length",
    ):
        build_trading_days_to_ltd_on_business_sessions(
            product_id="ANY",
            sessions=_days("2026-03-18", "2026-03-19"),
            contract_ids=["C1"],
            calendar_service=cal_svc,
            refdata_api=ref,
        )
