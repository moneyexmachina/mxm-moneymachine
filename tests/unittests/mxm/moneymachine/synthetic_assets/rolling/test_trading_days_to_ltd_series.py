"""Tests for trading-days-to-LTD series construction."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Protocol, cast

import numpy as np
import numpy.typing as npt
import pytest
from pytest import MonkeyPatch

from mxm.moneymachine.calendars.service import TradingCalendarService
from mxm.moneymachine.contracts.contract_series import ContractSeries
from mxm.moneymachine.synthetic_assets.rolling.trading_days_to_ltd_series import (
    UnknownContractId,
    build_trading_days_to_ltd_series,
)
from mxm.refdata import RefDataReader

type DateArray = npt.NDArray[np.datetime64]
type IntArray = npt.NDArray[np.int64]
type BoolArray = npt.NDArray[np.bool_]


@dataclass(frozen=True)
class _FakeContract:
    last_trading_day: date


class _FakeRefDataReader:
    """Minimal reference-data surface used by the builder."""

    def __init__(self, contracts: Mapping[str, _FakeContract]) -> None:
        self._contracts = dict(contracts)

    def get_contract_by_id(self, contract_id: str) -> _FakeContract:
        try:
            return self._contracts[contract_id]
        except KeyError as exc:
            raise UnknownContractId(contract_id) from exc


class _CalendarProtocol(Protocol):
    def bdays_to_ltd(
        self,
        asof: DateArray,
        ltd: DateArray,
        *,
        strict: bool = True,
        return_projected_flag: bool = False,
    ) -> IntArray | tuple[IntArray, BoolArray]: ...


class _DeterministicCalendar:
    """Small deterministic oracle for business-days-to-LTD calculations."""

    def __init__(self, trading_days: list[str]) -> None:
        self.trading_days: DateArray = np.array(trading_days, dtype="datetime64[D]")
        self._index_by_day = {
            trading_day: index
            for index, trading_day in enumerate(self.trading_days.tolist())
        }

    def bdays_to_ltd(
        self,
        asof: DateArray,
        ltd: DateArray,
        *,
        strict: bool = True,
        return_projected_flag: bool = False,
    ) -> IntArray | tuple[IntArray, BoolArray]:
        asof_dates: DateArray = np.asarray(asof, dtype="datetime64[D]")
        ltd_dates: DateArray = np.asarray(ltd, dtype="datetime64[D]")

        if asof_dates.shape != ltd_dates.shape:
            raise ValueError("asof/ltd shape mismatch")

        days_to_ltd: IntArray = np.empty(asof_dates.shape, dtype=np.int64)
        flat_days_to_ltd = days_to_ltd.ravel()

        asof_flat = asof_dates.ravel().tolist()
        ltd_flat = ltd_dates.ravel().tolist()

        for flat_index, (asof_date, ltd_date) in enumerate(
            zip(asof_flat, ltd_flat, strict=False)
        ):
            if strict:
                if asof_date not in self._index_by_day:
                    raise ValueError(f"asof {asof_date} not in trading_days")
                if ltd_date not in self._index_by_day:
                    raise ValueError(f"ltd {ltd_date} not in trading_days")

            flat_days_to_ltd[flat_index] = int(
                self._index_by_day[ltd_date] - self._index_by_day[asof_date]
            )

        if return_projected_flag:
            projected_flags: BoolArray = np.zeros_like(days_to_ltd, dtype=np.bool_)
            return days_to_ltd, projected_flags

        return days_to_ltd


@dataclass(frozen=True)
class _CalendarCall:
    asof: DateArray
    ltd: DateArray
    strict: bool | None
    return_projected_flag: bool | None


class _SpyCalendar:
    """Spy calendar that records call inputs and returns a deterministic sentinel."""

    def __init__(self) -> None:
        self.calls: list[_CalendarCall] = []

    def bdays_to_ltd(
        self,
        asof: DateArray,
        ltd: DateArray,
        *,
        strict: bool = True,
        return_projected_flag: bool = False,
    ) -> IntArray:
        asof_dates: DateArray = np.asarray(asof, dtype="datetime64[D]")
        ltd_dates: DateArray = np.asarray(ltd, dtype="datetime64[D]")

        self.calls.append(
            _CalendarCall(
                asof=asof_dates,
                ltd=ltd_dates,
                strict=strict,
                return_projected_flag=return_projected_flag,
            )
        )

        return np.arange(asof_dates.size, dtype=np.int64).reshape(asof_dates.shape)


def _make_series(
    *,
    product_id: str,
    sessions: list[str],
    contract_ids: list[str],
) -> ContractSeries:
    return ContractSeries(
        product_id=product_id,
        canonical_relative_id="TEST",
        short_rel_id="T",
        sessions=np.array(sessions, dtype="datetime64[D]"),
        contract_ids=contract_ids,
    )


def _make_service_with_calendar(
    monkeypatch: MonkeyPatch,
    *,
    refdata_reader: RefDataReader,
    calendar: _CalendarProtocol,
) -> TradingCalendarService:
    calendar_service = TradingCalendarService(refdata_reader=refdata_reader)

    def fake_calendar_for_product(
        self: TradingCalendarService,
        product_id: str,
    ) -> _CalendarProtocol:
        _ = (self, product_id)
        return calendar

    monkeypatch.setattr(
        TradingCalendarService,
        "calendar_for_product",
        fake_calendar_for_product,
    )

    return calendar_service


def test_build_trading_days_to_ltd_series_functional_oracle(
    monkeypatch: MonkeyPatch,
) -> None:
    """Build trading-days-to-LTD series under fully controlled inputs."""
    refdata_reader = _FakeRefDataReader(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
            "C2": _FakeContract(last_trading_day=date(2026, 6, 19)),
        }
    )

    calendar = _DeterministicCalendar(
        trading_days=[
            "2026-03-18",
            "2026-03-19",
            "2026-03-20",
            "2026-03-23",
            "2026-03-24",
            "2026-06-19",
        ]
    )

    calendar_service = _make_service_with_calendar(
        monkeypatch,
        refdata_reader=cast(RefDataReader, refdata_reader),
        calendar=calendar,
    )

    series = _make_series(
        product_id="ANY",
        sessions=["2026-03-18", "2026-03-19", "2026-03-20", "2026-03-23", "2026-03-24"],
        contract_ids=["C1", "C1", "C2", "C2", "C2"],
    )

    result = build_trading_days_to_ltd_series(
        series=series,
        calendar_service=calendar_service,
        refdata_reader=cast(RefDataReader, refdata_reader),
    )

    assert result.sessions.tolist() == series.sessions.tolist()
    assert result.contract_ids == series.contract_ids
    assert result.trading_days_to_ltd.dtype == np.dtype("int64")
    assert result.trading_days_to_ltd.tolist() == [2, 1, 3, 2, 1]


def test_build_trading_days_to_ltd_series_interaction_calls_calendar_correctly(
    monkeypatch: MonkeyPatch,
) -> None:
    """Verify that the builder calls the trading calendar with the expected inputs."""
    refdata_reader = _FakeRefDataReader(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
            "C2": _FakeContract(last_trading_day=date(2026, 6, 19)),
        }
    )

    spy_calendar = _SpyCalendar()
    calendar_service = _make_service_with_calendar(
        monkeypatch,
        refdata_reader=cast(RefDataReader, refdata_reader),
        calendar=spy_calendar,
    )

    series = _make_series(
        product_id="ANY",
        sessions=["2026-03-18", "2026-03-19", "2026-03-20"],
        contract_ids=["C1", "C1", "C2"],
    )

    result = build_trading_days_to_ltd_series(
        series=series,
        calendar_service=calendar_service,
        refdata_reader=cast(RefDataReader, refdata_reader),
    )

    assert len(spy_calendar.calls) == 1

    calendar_call = spy_calendar.calls[0]
    assert calendar_call.asof.tolist() == series.sessions.tolist()

    expected_ltd: DateArray = np.array(
        ["2026-03-20", "2026-03-20", "2026-06-19"],
        dtype="datetime64[D]",
    )
    assert calendar_call.ltd.tolist() == expected_ltd.tolist()
    assert calendar_call.strict is True
    assert calendar_call.return_projected_flag is False
    assert result.trading_days_to_ltd.tolist() == [0, 1, 2]


def test_build_trading_days_to_ltd_series_raises_on_unknown_contract_id(
    monkeypatch: MonkeyPatch,
) -> None:
    """Raise when the contract series references an unknown contract id."""
    refdata_reader = _FakeRefDataReader(
        contracts={
            "C1": _FakeContract(last_trading_day=date(2026, 3, 20)),
        }
    )

    calendar = _DeterministicCalendar(
        trading_days=["2026-03-18", "2026-03-19", "2026-03-20"]
    )
    calendar_service = _make_service_with_calendar(
        monkeypatch,
        refdata_reader=cast(RefDataReader, refdata_reader),
        calendar=calendar,
    )

    series = _make_series(
        product_id="ANY",
        sessions=["2026-03-18", "2026-03-19"],
        contract_ids=["C1", "C_UNKNOWN"],
    )

    with pytest.raises(UnknownContractId, match="C_UNKNOWN"):
        build_trading_days_to_ltd_series(
            series=series,
            calendar_service=calendar_service,
            refdata_reader=cast(RefDataReader, refdata_reader),
        )


def test_contract_series_constructor_raises_on_length_mismatch() -> None:
    """ContractSeries rejects mismatched session and contract-id lengths."""
    with pytest.raises(ValueError, match="length"):
        _make_series(
            product_id="ANY",
            sessions=["2026-03-18", "2026-03-19", "2026-03-20"],
            contract_ids=["C1", "C1"],
        )
