from __future__ import annotations

import numpy as np
import pytest
from numpy.typing import NDArray

from mxm.v1.calendars.mxm_business_calendar import (
    MXMBusinessCalendar,
    canonical_calendar_id,
)


def _make_valid_session_ids() -> NDArray[np.int64]:
    return np.array([0, 1, 2], dtype=np.int64)


def _make_valid_labels() -> NDArray[np.datetime64]:
    return np.array(
        [
            np.datetime64("2024-01-02", "D"),
            np.datetime64("2024-01-03", "D"),
            np.datetime64("2024-01-04", "D"),
        ],
        dtype="datetime64[D]",
    )


def _make_valid_start_ts() -> NDArray[np.datetime64]:
    return np.array(
        [
            np.datetime64("2024-01-02T00:00:00.000000000", "ns"),
            np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
            np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
        ],
        dtype="datetime64[ns]",
    )


def _make_valid_end_ts() -> NDArray[np.datetime64]:
    return np.array(
        [
            np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
            np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
            np.datetime64("2024-01-05T00:00:00.000000000", "ns"),
        ],
        dtype="datetime64[ns]",
    )


def make_valid_calendar(
    *,
    calendar_id: str = "  MXM_V1_Business  ",
    session_ids: NDArray[np.int64] | None = None,
    labels: NDArray[np.datetime64] | None = None,
    start_ts: NDArray[np.datetime64] | None = None,
    end_ts: NDArray[np.datetime64] | None = None,
) -> MXMBusinessCalendar:
    return MXMBusinessCalendar(
        calendar_id=calendar_id,
        session_ids=_make_valid_session_ids() if session_ids is None else session_ids,
        labels=_make_valid_labels() if labels is None else labels,
        start_ts=_make_valid_start_ts() if start_ts is None else start_ts,
        end_ts=_make_valid_end_ts() if end_ts is None else end_ts,
    )


class TestCanonicalCalendarId:
    def test_canonical_calendar_id_strips_and_lowercases(self) -> None:
        assert canonical_calendar_id("  MXM_V1_Business  ") == "mxm_v1_business"

    def test_canonical_calendar_id_rejects_empty_after_strip(self) -> None:
        with pytest.raises(ValueError, match="must not be empty"):
            canonical_calendar_id("   ")


class TestMXMBusinessCalendarConstruction:
    def test_constructs_valid_calendar(self) -> None:
        cal = make_valid_calendar()

        assert cal.calendar_id == "mxm_v1_business"
        assert len(cal) == 3
        assert np.array_equal(cal.session_ids, _make_valid_session_ids())
        assert np.array_equal(cal.labels, _make_valid_labels())
        assert np.array_equal(cal.start_ts, _make_valid_start_ts())
        assert np.array_equal(cal.end_ts, _make_valid_end_ts())

    def test_constructs_single_session_calendar(self) -> None:
        cal = make_valid_calendar(
            session_ids=np.array([0], dtype=np.int64),
            labels=np.array([np.datetime64("2024-01-02", "D")], dtype="datetime64[D]"),
            start_ts=np.array(
                [np.datetime64("2024-01-02T00:00:00.000000000", "ns")],
                dtype="datetime64[ns]",
            ),
            end_ts=np.array(
                [np.datetime64("2024-01-03T00:00:00.000000000", "ns")],
                dtype="datetime64[ns]",
            ),
        )

        assert cal.calendar_id == "mxm_v1_business"
        assert len(cal) == 1
        assert cal.session_ids[0] == 0
        assert cal.labels[0] == np.datetime64("2024-01-02", "D")


class TestMXMBusinessCalendarValidationShapeAndDtype:
    def test_rejects_non_1d_session_ids(self) -> None:
        session_ids = np.array([[0, 1, 2]], dtype=np.int64)

        with pytest.raises(ValueError, match="session_ids must be 1D"):
            make_valid_calendar(session_ids=session_ids)

    def test_rejects_non_1d_labels(self) -> None:
        labels = np.array(
            [
                [
                    np.datetime64("2024-01-02", "D"),
                    np.datetime64("2024-01-03", "D"),
                    np.datetime64("2024-01-04", "D"),
                ]
            ],
            dtype="datetime64[D]",
        )

        with pytest.raises(ValueError, match="labels must be 1D"):
            make_valid_calendar(labels=labels)

    def test_rejects_non_1d_start_ts(self) -> None:
        start_ts = np.array(
            [
                [
                    np.datetime64("2024-01-02T00:00:00.000000000", "ns"),
                    np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
                    np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
                ]
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(ValueError, match="start_ts must be 1D"):
            make_valid_calendar(start_ts=start_ts)

    def test_rejects_non_1d_end_ts(self) -> None:
        end_ts = np.array(
            [
                [
                    np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
                    np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
                    np.datetime64("2024-01-05T00:00:00.000000000", "ns"),
                ]
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(ValueError, match="end_ts must be 1D"):
            make_valid_calendar(end_ts=end_ts)

    def test_rejects_wrong_dtype_session_ids(self) -> None:
        session_ids = np.array([0, 1, 2], dtype=np.int32)

        with pytest.raises(TypeError, match="session_ids must have dtype"):
            make_valid_calendar(session_ids=session_ids)

    def test_rejects_wrong_dtype_labels(self) -> None:
        labels = np.array(
            [
                np.datetime64("2024-01-02T00:00:00", "ns"),
                np.datetime64("2024-01-03T00:00:00", "ns"),
                np.datetime64("2024-01-04T00:00:00", "ns"),
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(TypeError, match="labels must have dtype"):
            make_valid_calendar(labels=labels)

    def test_rejects_wrong_dtype_start_ts(self) -> None:
        start_ts = np.array(
            [
                np.datetime64("2024-01-02", "D"),
                np.datetime64("2024-01-03", "D"),
                np.datetime64("2024-01-04", "D"),
            ],
            dtype="datetime64[D]",
        )
        with pytest.raises(
            TypeError,
            match=(
                r"Expected canonical MXM timestamp array "
                r"\(np\.ndarray with dtype datetime64\[ns\]\)\."
            ),
        ):
            make_valid_calendar(start_ts=start_ts)

    def test_rejects_wrong_dtype_end_ts(self) -> None:
        end_ts = np.array(
            [
                np.datetime64("2024-01-03", "D"),
                np.datetime64("2024-01-04", "D"),
                np.datetime64("2024-01-05", "D"),
            ],
            dtype="datetime64[D]",
        )
        with pytest.raises(
            TypeError,
            match=(
                r"Expected canonical MXM timestamp array "
                r"\(np\.ndarray with dtype datetime64\[ns\]\)\."
            ),
        ):
            make_valid_calendar(end_ts=end_ts)


class TestMXMBusinessCalendarValidationLengths:
    def test_rejects_labels_length_mismatch(self) -> None:
        labels = np.array(
            [
                np.datetime64("2024-01-02", "D"),
                np.datetime64("2024-01-03", "D"),
            ],
            dtype="datetime64[D]",
        )

        with pytest.raises(ValueError, match="labels size 2 != session_ids size 3"):
            make_valid_calendar(labels=labels)

    def test_rejects_start_ts_length_mismatch(self) -> None:
        start_ts = np.array(
            [
                np.datetime64("2024-01-02T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(ValueError, match="start_ts size 2 != session_ids size 3"):
            make_valid_calendar(start_ts=start_ts)

    def test_rejects_end_ts_length_mismatch(self) -> None:
        end_ts = np.array(
            [
                np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(ValueError, match="end_ts size 2 != session_ids size 3"):
            make_valid_calendar(end_ts=end_ts)


class TestMXMBusinessCalendarValidationCoreInvariants:
    def test_rejects_empty_calendar(self) -> None:
        with pytest.raises(
            ValueError, match="calendar must contain at least one session"
        ):
            make_valid_calendar(
                session_ids=np.array([], dtype=np.int64),
                labels=np.array([], dtype="datetime64[D]"),
                start_ts=np.array([], dtype="datetime64[ns]"),
                end_ts=np.array([], dtype="datetime64[ns]"),
            )

    def test_rejects_session_ids_not_starting_at_zero(self) -> None:
        session_ids = np.array([1, 2, 3], dtype=np.int64)

        with pytest.raises(ValueError, match=r"dense sequence 0..N-1"):
            make_valid_calendar(session_ids=session_ids)

    def test_rejects_session_ids_with_gap(self) -> None:
        session_ids = np.array([0, 2, 3], dtype=np.int64)

        with pytest.raises(ValueError, match=r"dense sequence 0..N-1"):
            make_valid_calendar(session_ids=session_ids)

    def test_rejects_session_ids_with_duplicate(self) -> None:
        session_ids = np.array([0, 1, 1], dtype=np.int64)

        with pytest.raises(ValueError, match=r"dense sequence 0..N-1"):
            make_valid_calendar(session_ids=session_ids)

    def test_rejects_session_ids_out_of_order(self) -> None:
        session_ids = np.array([0, 2, 1], dtype=np.int64)

        with pytest.raises(ValueError, match=r"dense sequence 0..N-1"):
            make_valid_calendar(session_ids=session_ids)

    def test_rejects_labels_with_nat(self) -> None:
        labels = np.array(
            [
                np.datetime64("2024-01-02", "D"),
                np.datetime64("NaT", "D"),
                np.datetime64("2024-01-04", "D"),
            ],
            dtype="datetime64[D]",
        )

        with pytest.raises(ValueError, match="labels must not contain NaT"):
            make_valid_calendar(labels=labels)

    def test_rejects_duplicate_labels(self) -> None:
        labels = np.array(
            [
                np.datetime64("2024-01-02", "D"),
                np.datetime64("2024-01-02", "D"),
                np.datetime64("2024-01-04", "D"),
            ],
            dtype="datetime64[D]",
        )

        with pytest.raises(
            ValueError, match="labels must be strictly increasing and unique"
        ):
            make_valid_calendar(labels=labels)

    def test_rejects_decreasing_labels(self) -> None:
        labels = np.array(
            [
                np.datetime64("2024-01-02", "D"),
                np.datetime64("2024-01-04", "D"),
                np.datetime64("2024-01-03", "D"),
            ],
            dtype="datetime64[D]",
        )

        with pytest.raises(
            ValueError, match="labels must be strictly increasing and unique"
        ):
            make_valid_calendar(labels=labels)

    def test_rejects_start_ts_with_nat(self) -> None:
        start_ts = np.array(
            [
                np.datetime64("2024-01-02T00:00:00.000000000", "ns"),
                np.datetime64("NaT", "ns"),
                np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(ValueError):
            make_valid_calendar(start_ts=start_ts)

    def test_rejects_end_ts_with_nat(self) -> None:
        end_ts = np.array(
            [
                np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
                np.datetime64("NaT", "ns"),
                np.datetime64("2024-01-05T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(ValueError):
            make_valid_calendar(end_ts=end_ts)

    def test_rejects_non_monotonic_start_ts(self) -> None:
        start_ts = np.array(
            [
                np.datetime64("2024-01-02T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )
        with pytest.raises(
            ValueError,
            match=r"Canonical MXM timestamp array must be monotonic increasing\.",
        ):
            make_valid_calendar(start_ts=start_ts)

    def test_rejects_non_monotonic_end_ts(self) -> None:
        end_ts = np.array(
            [
                np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-05T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )
        with pytest.raises(
            ValueError,
            match=r"Canonical MXM timestamp array must be monotonic increasing\.",
        ):
            make_valid_calendar(end_ts=end_ts)

    def test_rejects_session_with_start_not_before_end(self) -> None:
        end_ts = np.array(
            [
                np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-05T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(
            ValueError, match="every session must satisfy start_ts < end_ts"
        ):
            make_valid_calendar(end_ts=end_ts)

    def test_rejects_overlapping_intervals(self) -> None:
        start_ts = np.array(
            [
                np.datetime64("2024-01-02T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-02T12:00:00.000000000", "ns"),
                np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )
        end_ts = np.array(
            [
                np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-05T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(ValueError, match="ordered and non-overlapping"):
            make_valid_calendar(start_ts=start_ts, end_ts=end_ts)


class TestMXMBusinessCalendarValidationV1Alignment:
    def test_rejects_start_ts_not_equal_to_label_midnight(self) -> None:
        start_ts = np.array(
            [
                np.datetime64("2024-01-02T01:00:00.000000000", "ns"),
                np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(
            ValueError, match="start_ts must equal labels cast to datetime64\\[ns\\]"
        ):
            make_valid_calendar(start_ts=start_ts)

    def test_rejects_end_ts_not_equal_to_start_ts_plus_one_day(self) -> None:
        end_ts = np.array(
            [
                np.datetime64("2024-01-02T23:00:00.000000000", "ns"),
                np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
                np.datetime64("2024-01-05T00:00:00.000000000", "ns"),
            ],
            dtype="datetime64[ns]",
        )

        with pytest.raises(ValueError, match="end_ts must equal start_ts \\+ 1 day"):
            make_valid_calendar(end_ts=end_ts)


class TestMXMBusinessCalendarLookup:
    def test_contains_session_id_for_valid_ids(self) -> None:
        cal = make_valid_calendar()

        assert cal.contains_session_id(0)
        assert cal.contains_session_id(1)
        assert cal.contains_session_id(2)

    def test_contains_session_id_for_invalid_ids(self) -> None:
        cal = make_valid_calendar()

        assert not cal.contains_session_id(-1)
        assert not cal.contains_session_id(3)
        assert not cal.contains_session_id(100)

    def test_validate_session_id_accepts_valid_ids(self) -> None:
        cal = make_valid_calendar()

        cal.validate_session_id(0)
        cal.validate_session_id(1)
        cal.validate_session_id(2)

    def test_validate_session_id_rejects_negative(self) -> None:
        cal = make_valid_calendar()

        with pytest.raises(ValueError, match="outside valid range"):
            cal.validate_session_id(-1)

    def test_validate_session_id_rejects_too_large(self) -> None:
        cal = make_valid_calendar()

        with pytest.raises(ValueError, match="outside valid range"):
            cal.validate_session_id(3)

    def test_contains_label_true_for_existing_labels(self) -> None:
        cal = make_valid_calendar()

        assert cal.contains_label(np.datetime64("2024-01-02", "D"))
        assert cal.contains_label(np.datetime64("2024-01-03", "D"))
        assert cal.contains_label(np.datetime64("2024-01-04", "D"))

    def test_contains_label_false_for_missing_labels(self) -> None:
        cal = make_valid_calendar()

        assert not cal.contains_label(np.datetime64("2024-01-01", "D"))
        assert not cal.contains_label(np.datetime64("2024-01-05", "D"))
        assert not cal.contains_label(np.datetime64("2024-01-10", "D"))

    def test_contains_label_accepts_non_day_resolution_scalar(self) -> None:
        cal = make_valid_calendar()

        assert cal.contains_label(np.datetime64("2024-01-03T13:45:00.000000000", "ns"))

    def test_session_id_from_label_returns_expected_ids(self) -> None:
        cal = make_valid_calendar()

        assert cal.session_id_from_label(np.datetime64("2024-01-02", "D")) == 0
        assert cal.session_id_from_label(np.datetime64("2024-01-03", "D")) == 1
        assert cal.session_id_from_label(np.datetime64("2024-01-04", "D")) == 2

    def test_session_id_from_label_accepts_non_day_resolution_scalar(self) -> None:
        cal = make_valid_calendar()

        assert (
            cal.session_id_from_label(
                np.datetime64("2024-01-03T23:59:59.999999999", "ns")
            )
            == 1
        )

    def test_session_id_from_label_rejects_missing_label(self) -> None:
        cal = make_valid_calendar()

        with pytest.raises(ValueError, match="is not present in calendar"):
            cal.session_id_from_label(np.datetime64("2024-01-05", "D"))

    def test_label_from_session_id_returns_expected_label(self) -> None:
        cal = make_valid_calendar()

        assert cal.label_from_session_id(0) == np.datetime64("2024-01-02", "D")
        assert cal.label_from_session_id(1) == np.datetime64("2024-01-03", "D")
        assert cal.label_from_session_id(2) == np.datetime64("2024-01-04", "D")

    def test_start_ts_from_session_id_returns_expected_timestamp(self) -> None:
        cal = make_valid_calendar()

        assert cal.start_ts_from_session_id(0) == np.datetime64(
            "2024-01-02T00:00:00.000000000", "ns"
        )
        assert cal.start_ts_from_session_id(1) == np.datetime64(
            "2024-01-03T00:00:00.000000000", "ns"
        )
        assert cal.start_ts_from_session_id(2) == np.datetime64(
            "2024-01-04T00:00:00.000000000", "ns"
        )

    def test_end_ts_from_session_id_returns_expected_timestamp(self) -> None:
        cal = make_valid_calendar()

        assert cal.end_ts_from_session_id(0) == np.datetime64(
            "2024-01-03T00:00:00.000000000", "ns"
        )
        assert cal.end_ts_from_session_id(1) == np.datetime64(
            "2024-01-04T00:00:00.000000000", "ns"
        )
        assert cal.end_ts_from_session_id(2) == np.datetime64(
            "2024-01-05T00:00:00.000000000", "ns"
        )

    def test_bounds_from_session_id_returns_expected_pair(self) -> None:
        cal = make_valid_calendar()

        bounds = cal.bounds_from_session_id(1)

        assert bounds == (
            np.datetime64("2024-01-03T00:00:00.000000000", "ns"),
            np.datetime64("2024-01-04T00:00:00.000000000", "ns"),
        )

    def test_lookup_methods_reject_invalid_session_id(self) -> None:
        cal = make_valid_calendar()

        with pytest.raises(ValueError, match="outside valid range"):
            cal.label_from_session_id(3)

        with pytest.raises(ValueError, match="outside valid range"):
            cal.start_ts_from_session_id(3)

        with pytest.raises(ValueError, match="outside valid range"):
            cal.end_ts_from_session_id(3)

        with pytest.raises(ValueError, match="outside valid range"):
            cal.bounds_from_session_id(3)
