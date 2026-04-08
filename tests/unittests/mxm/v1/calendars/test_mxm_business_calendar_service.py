from __future__ import annotations

import numpy as np
import pytest

import mxm.v1.calendars.mxm_business_calendar_service as svcmod
from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.calendars.mxm_business_calendar_service import (
    MXMBusinessCalendarService,
    build_mxm_business_calendar_id,
)


def _days(*xs: str) -> np.ndarray:
    return np.array(xs, dtype="datetime64[D]")


def _make_calendar(
    *,
    calendar_id: str = "mxm_v1_business_2026-03-18_2026-03-20",
    labels: np.ndarray | None = None,
) -> MXMBusinessCalendar:
    if labels is None:
        labels = _days("2026-03-18", "2026-03-19", "2026-03-20")

    start_ts = labels.astype("datetime64[ns]")
    end_ts = (start_ts + np.timedelta64(1, "D")).astype("datetime64[ns]")

    return MXMBusinessCalendar(
        calendar_id=calendar_id,
        session_ids=np.arange(labels.size, dtype=np.int64),
        labels=labels,
        start_ts=start_ts,
        end_ts=end_ts,
    )


def test_build_mxm_business_calendar_id_derives_canonical_identity() -> None:
    calendar_id = build_mxm_business_calendar_id(
        calendar_base_id="mxm_v1_business",
        start_label=np.datetime64("2026-03-18", "D"),
        end_label=np.datetime64("2026-03-20", "D"),
    )

    assert calendar_id == "mxm_v1_business_2026-03-18_2026-03-20"


def test_build_mxm_business_calendar_id_rejects_end_before_start() -> None:
    with pytest.raises(ValueError, match=r"end_label must be >= start_label"):
        _ = build_mxm_business_calendar_id(
            calendar_base_id="mxm_v1_business",
            start_label=np.datetime64("2026-03-20", "D"),
            end_label=np.datetime64("2026-03-18", "D"),
        )


def test_calendar_id_property_derives_effective_identity() -> None:
    service = MXMBusinessCalendarService(
        calendar_base_id="mxm_v1_business",
        start_label=np.datetime64("2026-03-18", "D"),
        end_label=np.datetime64("2026-03-20", "D"),
    )

    assert service.calendar_id == "mxm_v1_business_2026-03-18_2026-03-20"


def test_get_calendar_builds_real_calendar_and_caches_it() -> None:
    service = MXMBusinessCalendarService(
        calendar_base_id="mxm_v1_business",
        start_label=np.datetime64("2026-03-18", "D"),
        end_label=np.datetime64("2026-03-20", "D"),
    )

    cal1 = service.get_calendar()
    cal2 = service.get_calendar()

    assert isinstance(cal1, MXMBusinessCalendar)
    assert cal1 is cal2
    assert cal1.calendar_id == "mxm_v1_business_2026-03-18_2026-03-20"
    assert np.array_equal(
        cal1.labels,
        _days("2026-03-18", "2026-03-19", "2026-03-20"),
    )


def test_get_calendar_calls_builder_once_with_derived_arguments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    built_calendar = _make_calendar(
        calendar_id="mxm_test_2026-03-18_2026-03-20",
    )

    def fake_build_mxm_business_calendar(
        *,
        calendar_id: str,
        start_label: np.datetime64,
        end_label: np.datetime64,
    ) -> MXMBusinessCalendar:
        captured["calendar_id"] = calendar_id
        captured["start_label"] = start_label
        captured["end_label"] = end_label
        return built_calendar

    monkeypatch.setattr(
        svcmod,
        "build_mxm_business_calendar",
        fake_build_mxm_business_calendar,
    )

    service = MXMBusinessCalendarService(
        calendar_base_id="mxm_test",
        start_label=np.datetime64("2026-03-18", "D"),
        end_label=np.datetime64("2026-03-20", "D"),
    )

    cal1 = service.get_calendar()
    cal2 = service.get_calendar()

    assert captured["calendar_id"] == "mxm_test_2026-03-18_2026-03-20"
    assert captured["start_label"] == np.datetime64("2026-03-18", "D")
    assert captured["end_label"] == np.datetime64("2026-03-20", "D")

    assert cal1 is built_calendar
    assert cal2 is built_calendar
    assert cal1 is cal2


def test_get_calendar_does_not_rebuild_after_first_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_count = 0
    built_calendar = _make_calendar()

    def fake_build_mxm_business_calendar(
        *,
        calendar_id: str,
        start_label: np.datetime64,
        end_label: np.datetime64,
    ) -> MXMBusinessCalendar:
        nonlocal call_count
        call_count += 1
        return built_calendar

    monkeypatch.setattr(
        svcmod,
        "build_mxm_business_calendar",
        fake_build_mxm_business_calendar,
    )

    service = MXMBusinessCalendarService(
        calendar_base_id="mxm_v1_business",
        start_label=np.datetime64("2026-03-18", "D"),
        end_label=np.datetime64("2026-03-20", "D"),
    )

    _ = service.get_calendar()
    _ = service.get_calendar()
    _ = service.get_calendar()

    assert call_count == 1


def test_get_calendar_rejects_end_before_start() -> None:
    service = MXMBusinessCalendarService(
        calendar_base_id="mxm_v1_business",
        start_label=np.datetime64("2026-03-20", "D"),
        end_label=np.datetime64("2026-03-18", "D"),
    )

    with pytest.raises(ValueError, match=r"end_label must be >= start_label"):
        _ = service.get_calendar()
