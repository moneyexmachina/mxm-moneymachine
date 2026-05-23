from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from mxm.moneymachine.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.moneymachine.calendars.mxm_business_calendar_builder import (
    build_mxm_business_calendar,
)


def _day_array(*days: str) -> NDArray[np.datetime64]:
    return np.array([np.datetime64(day, "D") for day in days], dtype="datetime64[D]")


def _ts_ns_array(*timestamps: str) -> NDArray[np.datetime64]:
    return np.array(
        [np.datetime64(ts, "ns") for ts in timestamps],
        dtype="datetime64[ns]",
    )


class TestBuildMXMBusinessCalendarHappyPath:
    def test_builds_calendar_for_simple_weekday_span(self) -> None:
        calendar = build_mxm_business_calendar(
            calendar_id="  MXM_Business  ",
            start_label=np.datetime64("2024-01-02", "D"),
            end_label=np.datetime64("2024-01-05", "D"),
        )

        assert isinstance(calendar, MXMBusinessCalendar)
        assert calendar.calendar_id == "mxm_business"
        assert np.array_equal(
            calendar.session_ids,
            np.array([0, 1, 2, 3], dtype=np.int64),
        )
        assert np.array_equal(
            calendar.labels,
            _day_array("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"),
        )
        assert np.array_equal(
            calendar.start_ts,
            _ts_ns_array(
                "2024-01-02T00:00:00.000000000",
                "2024-01-03T00:00:00.000000000",
                "2024-01-04T00:00:00.000000000",
                "2024-01-05T00:00:00.000000000",
            ),
        )
        assert np.array_equal(
            calendar.end_ts,
            _ts_ns_array(
                "2024-01-03T00:00:00.000000000",
                "2024-01-04T00:00:00.000000000",
                "2024-01-05T00:00:00.000000000",
                "2024-01-06T00:00:00.000000000",
            ),
        )

    def test_builds_single_session_calendar_for_single_included_day(self) -> None:
        calendar = build_mxm_business_calendar(
            calendar_id="mxm_business",
            start_label=np.datetime64("2024-01-02", "D"),
            end_label=np.datetime64("2024-01-02", "D"),
        )

        assert calendar.calendar_id == "mxm_business"
        assert np.array_equal(calendar.session_ids, np.array([0], dtype=np.int64))
        assert np.array_equal(calendar.labels, _day_array("2024-01-02"))
        assert np.array_equal(
            calendar.start_ts,
            _ts_ns_array("2024-01-02T00:00:00.000000000"),
        )
        assert np.array_equal(
            calendar.end_ts,
            _ts_ns_array("2024-01-03T00:00:00.000000000"),
        )


class TestBuildMXMBusinessCalendarPolicy:
    def test_excludes_weekends(self) -> None:
        calendar = build_mxm_business_calendar(
            calendar_id="mxm_business",
            start_label=np.datetime64("2024-01-05", "D"),  # Friday
            end_label=np.datetime64("2024-01-08", "D"),  # Monday
        )

        assert np.array_equal(
            calendar.labels,
            _day_array("2024-01-05", "2024-01-08"),
        )
        assert np.array_equal(calendar.session_ids, np.array([0, 1], dtype=np.int64))

    def test_excludes_january_first(self) -> None:
        calendar = build_mxm_business_calendar(
            calendar_id="mxm_business",
            start_label=np.datetime64("2024-01-01", "D"),
            end_label=np.datetime64("2024-01-03", "D"),
        )

        assert np.array_equal(
            calendar.labels,
            _day_array("2024-01-02", "2024-01-03"),
        )
        assert np.array_equal(calendar.session_ids, np.array([0, 1], dtype=np.int64))

    def test_excludes_december_twenty_fifth(self) -> None:
        calendar = build_mxm_business_calendar(
            calendar_id="mxm_business",
            start_label=np.datetime64("2024-12-24", "D"),
            end_label=np.datetime64("2024-12-26", "D"),
        )

        assert np.array_equal(
            calendar.labels,
            _day_array("2024-12-24", "2024-12-26"),
        )
        assert np.array_equal(calendar.session_ids, np.array([0, 1], dtype=np.int64))

    def test_combines_weekend_and_fixed_holiday_exclusions(self) -> None:
        calendar = build_mxm_business_calendar(
            calendar_id="mxm_business",
            start_label=np.datetime64("2021-12-24", "D"),
            end_label=np.datetime64("2021-12-27", "D"),
        )

        assert np.array_equal(
            calendar.labels,
            _day_array("2021-12-24", "2021-12-27"),
        )
        assert np.array_equal(calendar.session_ids, np.array([0, 1], dtype=np.int64))

    def test_span_is_inclusive_on_both_bounds(self) -> None:
        calendar = build_mxm_business_calendar(
            calendar_id="mxm_business",
            start_label=np.datetime64("2024-01-02", "D"),
            end_label=np.datetime64("2024-01-03", "D"),
        )

        assert np.array_equal(
            calendar.labels,
            _day_array("2024-01-02", "2024-01-03"),
        )

    def test_normalizes_non_day_resolution_inputs(self) -> None:
        calendar = build_mxm_business_calendar(
            calendar_id="mxm_business",
            start_label=np.datetime64("2024-01-02T15:30:00.000000000", "ns"),
            end_label=np.datetime64("2024-01-05T23:59:59.999999999", "ns"),
        )

        assert np.array_equal(
            calendar.labels,
            _day_array("2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"),
        )
        assert np.array_equal(
            calendar.start_ts,
            _ts_ns_array(
                "2024-01-02T00:00:00.000000000",
                "2024-01-03T00:00:00.000000000",
                "2024-01-04T00:00:00.000000000",
                "2024-01-05T00:00:00.000000000",
            ),
        )
        assert np.array_equal(
            calendar.end_ts,
            _ts_ns_array(
                "2024-01-03T00:00:00.000000000",
                "2024-01-04T00:00:00.000000000",
                "2024-01-05T00:00:00.000000000",
                "2024-01-06T00:00:00.000000000",
            ),
        )


class TestBuildMXMBusinessCalendarSpanValidation:
    def test_rejects_start_after_end(self) -> None:
        with pytest.raises(
            ValueError,
            match=r"start_label 2024-01-05 must be <= end_label 2024-01-02",
        ):
            build_mxm_business_calendar(
                calendar_id="mxm_business",
                start_label=np.datetime64("2024-01-05", "D"),
                end_label=np.datetime64("2024-01-02", "D"),
            )

    def test_rejects_empty_after_filter_weekend_only_span(self) -> None:
        with pytest.raises(
            ValueError,
            match=r"Requested date span contains no MXM business sessions",
        ):
            build_mxm_business_calendar(
                calendar_id="mxm_business",
                start_label=np.datetime64("2024-01-06", "D"),
                end_label=np.datetime64("2024-01-07", "D"),
            )

    def test_rejects_empty_after_filter_january_first_only(self) -> None:
        with pytest.raises(
            ValueError,
            match=r"Requested date span contains no MXM business sessions",
        ):
            build_mxm_business_calendar(
                calendar_id="mxm_business",
                start_label=np.datetime64("2024-01-01", "D"),
                end_label=np.datetime64("2024-01-01", "D"),
            )

    def test_rejects_empty_after_filter_december_twenty_fifth_only(self) -> None:
        with pytest.raises(
            ValueError,
            match=r"Requested date span contains no MXM business sessions",
        ):
            build_mxm_business_calendar(
                calendar_id="mxm_business",
                start_label=np.datetime64("2024-12-25", "D"),
                end_label=np.datetime64("2024-12-25", "D"),
            )

    def test_rejects_nat_start_label(self) -> None:
        with pytest.raises(ValueError, match=r"start_label must not be NaT"):
            build_mxm_business_calendar(
                calendar_id="mxm_business",
                start_label=np.datetime64("NaT", "ns"),
                end_label=np.datetime64("2024-01-02", "D"),
            )

    def test_rejects_nat_end_label(self) -> None:
        with pytest.raises(ValueError, match=r"end_label must not be NaT"):
            build_mxm_business_calendar(
                calendar_id="mxm_business",
                start_label=np.datetime64("2024-01-02", "D"),
                end_label=np.datetime64("NaT", "ns"),
            )
