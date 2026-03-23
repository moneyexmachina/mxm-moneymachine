import datetime as dt
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest

from mxm.v1.calendars.models import TradingCalendar
from mxm.v1.calendars.mxm_business_calendar import MxMBusinessCalendar
from mxm.v1.calendars.mxm_business_calendar_service import (
    EmptyBusinessCalendar,
    EmptyObservedBusinessRegion,
    MxMBusinessCalendarService,
    canonical_business_calendar_id,
)


def _days(*xs: str) -> np.ndarray:
    return np.array(xs, dtype="datetime64[D]")


def _make_trading_calendar(
    *,
    calendar_id: str = "es_test",
    trading_days: np.ndarray | None = None,
    observed_end: str | np.datetime64 = "2025-01-03",
) -> TradingCalendar:
    if trading_days is None:
        trading_days = _days("2025-01-01", "2025-01-02", "2025-01-03")

    return TradingCalendar(
        calendar_id=calendar_id,
        trading_days=trading_days,
        observed_end=np.datetime64(observed_end, "D"),
    )


# ---------------------------------------------------------------------------
# canonical_business_calendar_id
# ---------------------------------------------------------------------------


def test_canonical_business_calendar_id_strips_and_lowercases() -> None:
    assert canonical_business_calendar_id("  MXM_V1_Business  ") == "mxm_v1_business"
    assert canonical_business_calendar_id("Es_Calendar") == "es_calendar"
    assert canonical_business_calendar_id(" already_clean ") == "already_clean"


# ---------------------------------------------------------------------------
# _filter_business_days
# ---------------------------------------------------------------------------


def test_filter_business_days_with_empty_exclusions_returns_copy() -> None:
    trading_days = _days("2025-01-01", "2025-01-02", "2025-01-03")
    excluded_days = np.array([], dtype="datetime64[D]")

    out = MxMBusinessCalendarService._filter_business_days(
        trading_days=trading_days,
        excluded_days=excluded_days,
    )

    assert np.array_equal(out, trading_days)
    assert out.dtype == np.dtype("datetime64[D]")
    assert out is not trading_days


def test_filter_business_days_removes_present_exclusions_and_ignores_absent_ones() -> (
    None
):
    trading_days = _days("2025-01-01", "2025-01-02", "2025-01-03", "2025-01-06")
    excluded_days = _days("2025-01-01", "2025-01-05")

    out = MxMBusinessCalendarService._filter_business_days(
        trading_days=trading_days,
        excluded_days=excluded_days,
    )

    assert np.array_equal(out, _days("2025-01-02", "2025-01-03", "2025-01-06"))


# ---------------------------------------------------------------------------
# _derive_observed_end
# ---------------------------------------------------------------------------


def test_derive_observed_end_returns_exact_base_observed_end_when_retained() -> None:
    business_days = _days("2025-01-02", "2025-01-03", "2025-01-06")

    out = MxMBusinessCalendarService._derive_observed_end(
        business_days=business_days,
        base_observed_end=np.datetime64("2025-01-06", "D"),
        base_calendar_id="es_test",
    )

    assert out == np.datetime64("2025-01-06", "D")


def test_derive_observed_end_returns_greatest_retained_day_le_base_observed_end() -> (
    None
):
    business_days = _days("2025-01-02", "2025-01-03", "2025-01-06")

    out = MxMBusinessCalendarService._derive_observed_end(
        business_days=business_days,
        base_observed_end=np.datetime64("2025-01-04", "D"),
        base_calendar_id="es_test",
    )

    assert out == np.datetime64("2025-01-03", "D")


def test_derive_observed_end_raises_when_no_observed_business_day_remains() -> None:
    business_days = _days("2025-01-06", "2025-01-07")

    with pytest.raises(
        EmptyObservedBusinessRegion,
        match="Holiday filtering removed all observed-region business days",
    ):
        MxMBusinessCalendarService._derive_observed_end(
            business_days=business_days,
            base_observed_end=np.datetime64("2025-01-05", "D"),
            base_calendar_id="es_test",
        )


# ---------------------------------------------------------------------------
# _holiday_exclusions_for_calendar
# ---------------------------------------------------------------------------


def test_holiday_exclusions_for_calendar_unions_years_in_span(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MxMBusinessCalendarService(base_trading_calendar_id="es_test")

    calendar = _make_trading_calendar(
        trading_days=_days("2024-12-31", "2025-01-02", "2025-12-31"),
        observed_end="2025-12-31",
    )

    calls: list[int] = []

    def fake_holidays(year: int) -> set[dt.date]:
        calls.append(year)
        mapping = {
            2024: {dt.date(2024, 1, 1)},
            2025: {dt.date(2025, 1, 1), dt.date(2025, 12, 25)},
        }
        return mapping.get(year, set())

    monkeypatch.setattr(
        "mxm.v1.calendars.mxm_business_calendar_service.us_full_closure_holidays_minimal",
        fake_holidays,
    )

    out = service._holiday_exclusions_for_calendar(calendar)

    assert calls == [2024, 2025]
    assert out.dtype == np.dtype("datetime64[D]")
    assert np.array_equal(
        out,
        _days("2024-01-01", "2025-01-01", "2025-12-25"),
    )


def test_holiday_exclusions_for_calendar_returns_sorted_datetime64_day_array(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MxMBusinessCalendarService(base_trading_calendar_id="es_test")

    calendar = _make_trading_calendar(
        trading_days=_days("2025-01-02", "2025-12-31"),
        observed_end="2025-12-31",
    )

    def fake_holidays(year: int) -> set[dt.date]:
        assert year == 2025
        return {
            dt.date(2025, 12, 25),
            dt.date(2025, 1, 1),
            dt.date(2025, 7, 4),
        }

    monkeypatch.setattr(
        "mxm.v1.calendars.mxm_business_calendar_service.us_full_closure_holidays_minimal",
        fake_holidays,
    )

    out = service._holiday_exclusions_for_calendar(calendar)

    assert np.array_equal(
        out,
        _days("2025-01-01", "2025-07-04", "2025-12-25"),
    )


# ---------------------------------------------------------------------------
# _build_from_trading_calendar
# ---------------------------------------------------------------------------


def test_build_from_trading_calendar_returns_filtered_business_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MxMBusinessCalendarService(
        base_trading_calendar_id="es_test",
        business_calendar_id="  MXM_V1_BUSINESS  ",
    )

    base_calendar = _make_trading_calendar(
        calendar_id="es_test",
        trading_days=_days("2025-01-01", "2025-01-02", "2025-01-03"),
        observed_end="2025-01-03",
    )

    def fake_holiday_exclusions_for_calendar(
        self: MxMBusinessCalendarService,
        calendar: TradingCalendar,
    ) -> np.ndarray:
        assert calendar is base_calendar
        return _days("2025-01-01")

    monkeypatch.setattr(
        MxMBusinessCalendarService,
        "_holiday_exclusions_for_calendar",
        fake_holiday_exclusions_for_calendar,
    )

    out = service._build_from_trading_calendar(base_calendar)

    assert isinstance(out, MxMBusinessCalendar)
    assert out.calendar_id == "mxm_v1_business"
    assert np.array_equal(out.business_days, _days("2025-01-02", "2025-01-03"))
    assert out.observed_end == np.datetime64("2025-01-03", "D")


def test_build_from_trading_calendar_raises_empty_business_calendar_when_all_days_excluded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MxMBusinessCalendarService(base_trading_calendar_id="es_test")

    base_calendar = _make_trading_calendar(
        calendar_id="es_test",
        trading_days=_days("2025-01-01", "2025-01-02"),
        observed_end="2025-01-02",
    )

    def fake_holiday_exclusions_for_calendar(
        self: MxMBusinessCalendarService,
        calendar: TradingCalendar,
    ) -> np.ndarray:
        assert calendar is base_calendar
        return _days("2025-01-01", "2025-01-02")

    monkeypatch.setattr(
        MxMBusinessCalendarService,
        "_holiday_exclusions_for_calendar",
        fake_holiday_exclusions_for_calendar,
    )

    with pytest.raises(
        EmptyBusinessCalendar,
        match="Business-calendar filtering removed all sessions",
    ):
        service._build_from_trading_calendar(base_calendar)


def test_build_from_trading_calendar_raises_empty_observed_region_when_no_retained_day_is_observed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MxMBusinessCalendarService(base_trading_calendar_id="es_test")

    base_calendar = _make_trading_calendar(
        calendar_id="es_test",
        trading_days=_days("2025-01-02", "2025-01-03", "2025-01-06"),
        observed_end="2025-01-03",
    )

    def fake_holiday_exclusions_for_calendar(
        self: MxMBusinessCalendarService,
        calendar: TradingCalendar,
    ) -> np.ndarray:
        assert calendar is base_calendar
        return _days("2025-01-02", "2025-01-03")

    monkeypatch.setattr(
        MxMBusinessCalendarService,
        "_holiday_exclusions_for_calendar",
        fake_holiday_exclusions_for_calendar,
    )

    with pytest.raises(
        EmptyObservedBusinessRegion,
        match="Holiday filtering removed all observed-region business days",
    ):
        service._build_from_trading_calendar(base_calendar)


# ---------------------------------------------------------------------------
# get_calendar
# ---------------------------------------------------------------------------


def test_get_calendar_builds_and_returns_business_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MxMBusinessCalendarService(
        base_trading_calendar_id="  ES_TEST  ",
        business_calendar_id="  MXM_V1_BUSINESS  ",
    )

    base_calendar = _make_trading_calendar(
        calendar_id="es_test",
        trading_days=_days("2025-01-01", "2025-01-02", "2025-01-03"),
        observed_end="2025-01-03",
    )

    load_calendar_mock = Mock(return_value=base_calendar)
    monkeypatch.setattr(
        "mxm.v1.calendars.mxm_business_calendar_service.load_calendar",
        load_calendar_mock,
    )

    def fake_holiday_exclusions_for_calendar(
        self: MxMBusinessCalendarService,
        calendar: TradingCalendar,
    ) -> np.ndarray:
        assert calendar is base_calendar
        return _days("2025-01-01")

    monkeypatch.setattr(
        MxMBusinessCalendarService,
        "_holiday_exclusions_for_calendar",
        fake_holiday_exclusions_for_calendar,
    )

    out = service.get_calendar()

    assert isinstance(out, MxMBusinessCalendar)
    assert out.calendar_id == "mxm_v1_business"
    assert np.array_equal(out.business_days, _days("2025-01-02", "2025-01-03"))
    assert out.observed_end == np.datetime64("2025-01-03", "D")

    load_calendar_mock.assert_called_once_with("es_test", root=None)


def test_get_calendar_passes_root_to_load_calendar(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = Path("/tmp/calendars")
    service = MxMBusinessCalendarService(
        base_trading_calendar_id="ES_TEST",
        calendars_root=root,
    )

    base_calendar = _make_trading_calendar()

    load_calendar_mock = Mock(return_value=base_calendar)
    monkeypatch.setattr(
        "mxm.v1.calendars.mxm_business_calendar_service.load_calendar",
        load_calendar_mock,
    )

    def fake_holiday_exclusions_for_calendar(
        self: MxMBusinessCalendarService,
        calendar: TradingCalendar,
    ) -> np.ndarray:
        assert calendar is base_calendar
        return np.array([], dtype="datetime64[D]")

    monkeypatch.setattr(
        MxMBusinessCalendarService,
        "_holiday_exclusions_for_calendar",
        fake_holiday_exclusions_for_calendar,
    )

    service.get_calendar()

    load_calendar_mock.assert_called_once_with("es_test", root=root)


def test_get_calendar_caches_result_and_loads_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = MxMBusinessCalendarService(base_trading_calendar_id="ES_TEST")

    base_calendar = _make_trading_calendar(
        calendar_id="es_test",
        trading_days=_days("2025-01-01", "2025-01-02", "2025-01-03"),
        observed_end="2025-01-03",
    )

    load_calendar_mock = Mock(return_value=base_calendar)
    monkeypatch.setattr(
        "mxm.v1.calendars.mxm_business_calendar_service.load_calendar",
        load_calendar_mock,
    )

    def fake_holiday_exclusions_for_calendar(
        self: MxMBusinessCalendarService,
        calendar: TradingCalendar,
    ) -> np.ndarray:
        assert calendar is base_calendar
        return _days("2025-01-01")

    monkeypatch.setattr(
        MxMBusinessCalendarService,
        "_holiday_exclusions_for_calendar",
        fake_holiday_exclusions_for_calendar,
    )

    cal1 = service.get_calendar()
    cal2 = service.get_calendar()

    assert cal1 is cal2
    load_calendar_mock.assert_called_once_with("es_test", root=None)
