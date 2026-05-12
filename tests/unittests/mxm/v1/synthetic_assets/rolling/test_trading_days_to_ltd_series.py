# tests/unittests/mxm/v1/synthetic_assets/rolling/test_trading_days_to_ltd_series.py
from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
import pytest

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.contract_series import ContractSeries
from mxm.v1.synthetic_assets.rolling.trading_days_to_ltd_series import (
    UnknownContractId,
    build_trading_days_to_ltd_series,
)

# -----------------------------------------------------------------------------
# Minimal fakes for RefDataAPI objects
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class _FakeContract:
    last_trading_day: date


class _FakeRefDataAPI:
    """
    Minimal surface used by build_trading_days_to_ltd_series.

    Only method required:
      - get_contract_by_id(contract_id) -> contract or None
    """

    def __init__(self, contracts: dict[str, _FakeContract]) -> None:
        self._contracts = contracts

    def get_contract_by_id(self, contract_id: str) -> _FakeContract | None:
        return self._contracts.get(contract_id)


# -----------------------------------------------------------------------------
# Calendars: (1) deterministic oracle, (2) spy for interaction tests
# -----------------------------------------------------------------------------


class _DeterministicCalendar:
    """
    Tiny deterministic calendar implementing the definition:

        trading_days_to_ltd = idx(ltd) - idx(asof)

    This is not a production calendar double; it is an oracle for unit testing
    that our function wires inputs correctly and preserves alignment.
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
        for k, (ai, li) in enumerate(zip(a_flat, l_flat, strict=False)):
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

    Used to verify that build_trading_days_to_ltd_series calls bdays_to_ltd
    with the correct arrays and keyword arguments, without depending on
    calendar math.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[np.ndarray, np.ndarray, dict]] = []

    def bdays_to_ltd(self, asof, ltd, **kwargs):
        a = np.asarray(asof, dtype="datetime64[D]")
        l = np.asarray(ltd, dtype="datetime64[D]")
        self.calls.append((a, l, dict(kwargs)))
        return np.arange(a.size, dtype=np.int64).reshape(a.shape)


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def _make_series(
    *, product_id: str, sessions: list[str], contract_ids: list[str]
) -> ContractSeries:
    return ContractSeries(
        product_id=product_id,
        canonical_relative_id="TEST",
        short_rel_id="T",
        sessions=np.array(sessions, dtype="datetime64[D]"),
        contract_ids=contract_ids,
    )


def _mk_service_and_patch_calendar(
    monkeypatch, *, refdata, calendar
) -> TradingCalendarService:
    cal_svc = TradingCalendarService(refdata_api=refdata)

    def _calendar_for_product(self: TradingCalendarService, _product_id: str):
        return calendar

    monkeypatch.setattr(
        TradingCalendarService, "calendar_for_product", _calendar_for_product
    )
    return cal_svc


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------


def test_build_trading_days_to_ltd_series_functional_oracle(monkeypatch) -> None:
    """
    Input-output (functional) test under fully controlled inputs.

    Verifies:
      - per-session LTD anchoring (contract switch changes the LTD used)
      - numeric output is correct for a tiny trading-day grid
      - dtype and alignment properties hold
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

    series = _make_series(
        product_id="ANY",
        sessions=["2026-03-18", "2026-03-19", "2026-03-20", "2026-03-23", "2026-03-24"],
        contract_ids=["C1", "C1", "C2", "C2", "C2"],  # switch at index 2
    )

    out = build_trading_days_to_ltd_series(
        series=series,
        calendar_service=cal_svc,
        refdata_api=ref,
    )

    assert out.sessions.tolist() == series.sessions.tolist()
    assert out.contract_ids == series.contract_ids
    assert out.trading_days_to_ltd.dtype == np.dtype("int64")

    # Expected distances in our tiny grid:
    # idx(03-20)=2, idx(06-19)=5, idx(03-18)=0, idx(03-19)=1, idx(03-20)=2, idx(03-23)=3, idx(03-24)=4
    # C1 ltd=03-20: 03-18 -> 2-0=2, 03-19 -> 2-1=1
    # C2 ltd=06-19: 03-20 -> 5-2=3, 03-23 -> 5-3=2, 03-24 -> 5-4=1
    assert out.trading_days_to_ltd.tolist() == [2, 1, 3, 2, 1]


def test_build_trading_days_to_ltd_series_interaction_calls_calendar_correctly(
    monkeypatch,
) -> None:
    """
    Interaction test: verifies correct usage of the trading calendar API.

    We assert only the public contract:
      - asof array equals series.sessions
      - ltd array equals per-session LTD derived from contract_ids
      - kwargs include strict=True and return_projected_flag=False
    """
    ref = _FakeRefDataAPI(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
            "C2": _FakeContract(last_trading_day=date(2026, 6, 19)),
        }
    )

    spy = _SpyCalendar()
    cal_svc = _mk_service_and_patch_calendar(monkeypatch, refdata=ref, calendar=spy)

    series = _make_series(
        product_id="ANY",
        sessions=["2026-03-18", "2026-03-19", "2026-03-20"],
        contract_ids=["C1", "C1", "C2"],
    )

    out = build_trading_days_to_ltd_series(
        series=series,
        calendar_service=cal_svc,
        refdata_api=ref,
    )

    # Calendar called exactly once
    assert len(spy.calls) == 1

    asof, ltd, kwargs = spy.calls[0]
    assert asof.tolist() == series.sessions.tolist()

    # Expected LTD vector, per session:
    expected_ltd = np.array(
        ["2026-03-20", "2026-03-20", "2026-06-19"], dtype="datetime64[D]"
    )
    assert ltd.tolist() == expected_ltd.tolist()

    assert kwargs.get("strict") is True
    assert kwargs.get("return_projected_flag") is False

    # Output is the spy sentinel (cast to int64 inside the function)
    assert out.trading_days_to_ltd.tolist() == [0, 1, 2]


def test_build_trading_days_to_ltd_series_raises_on_unknown_contract_id(
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

    series = _make_series(
        product_id="ANY",
        sessions=["2026-03-18", "2026-03-19"],
        contract_ids=["C1", "C_UNKNOWN"],
    )

    with pytest.raises(UnknownContractId):
        build_trading_days_to_ltd_series(
            series=series,
            calendar_service=cal_svc,
            refdata_api=ref,
        )


def test_contract_series_constructor_raises_on_length_mismatch() -> None:
    """
    ContractSeries validates alignment itself.

    So the correct test is that ContractSeries cannot be constructed with
    mismatched lengths, rather than expecting the days-to-LTD builder to
    receive an invalid series.
    """
    with pytest.raises(ValueError):
        _make_series(
            product_id="ANY",
            sessions=["2026-03-18", "2026-03-19", "2026-03-20"],
            contract_ids=["C1", "C1"],  # mismatch
        )
