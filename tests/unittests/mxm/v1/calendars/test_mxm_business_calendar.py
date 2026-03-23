import numpy as np
import pytest

from mxm.v1.calendars.mxm_business_calendar import MxMBusinessCalendar


def _days(*xs: str) -> np.ndarray:
    return np.array(xs, dtype="datetime64[D]")


@pytest.fixture
def compact_calendar() -> MxMBusinessCalendar:
    """
    Small mixed observed/projected calendar with gaps.

    business_days:
        2025-01-02
        2025-01-03
        2025-01-06
        2025-01-07
        2025-01-08

    observed_end:
        2025-01-06

    So:
    - observed:  2025-01-02, 2025-01-03, 2025-01-06
    - projected: 2025-01-07, 2025-01-08
    """
    return MxMBusinessCalendar(
        calendar_id="mxm_test",
        business_days=_days(
            "2025-01-02",
            "2025-01-03",
            "2025-01-06",
            "2025-01-07",
            "2025-01-08",
        ),
        observed_end=np.datetime64("2025-01-06", "D"),
    )


@pytest.fixture
def two_day_calendar() -> MxMBusinessCalendar:
    return MxMBusinessCalendar(
        calendar_id="mxm_two_day",
        business_days=_days("2025-01-02", "2025-01-03"),
        observed_end=np.datetime64("2025-01-03", "D"),
    )


@pytest.fixture
def singleton_calendar() -> MxMBusinessCalendar:
    return MxMBusinessCalendar(
        calendar_id="mxm_singleton",
        business_days=_days("2025-01-06"),
        observed_end=np.datetime64("2025-01-06", "D"),
    )


# ---------------------------------------------------------------------------
# Constructor / invariants
# ---------------------------------------------------------------------------


def test_construct_valid_calendar_stores_expected_fields(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.calendar_id == "mxm_test"
    assert compact_calendar.business_days.dtype == np.dtype("datetime64[D]")
    assert compact_calendar.business_days.ndim == 1
    assert np.array_equal(
        compact_calendar.business_days,
        _days(
            "2025-01-02",
            "2025-01-03",
            "2025-01-06",
            "2025-01-07",
            "2025-01-08",
        ),
    )
    assert compact_calendar.observed_end == np.datetime64("2025-01-06", "D")


def test_construct_rejects_observed_end_before_first_business_day() -> None:
    with pytest.raises(
        ValueError, match="observed_end .* is outside business_days range"
    ):
        MxMBusinessCalendar(
            calendar_id="bad",
            business_days=_days("2025-01-02", "2025-01-03"),
            observed_end=np.datetime64("2025-01-01", "D"),
        )


def test_construct_rejects_observed_end_after_last_business_day() -> None:
    with pytest.raises(
        ValueError, match="observed_end .* is outside business_days range"
    ):
        MxMBusinessCalendar(
            calendar_id="bad",
            business_days=_days("2025-01-02", "2025-01-03"),
            observed_end=np.datetime64("2025-01-04", "D"),
        )


def test_construct_accepts_string_observed_end() -> None:
    cal = MxMBusinessCalendar(
        calendar_id="ok",
        business_days=_days("2025-01-02", "2025-01-03"),
        observed_end="2025-01-03",
    )
    assert cal.observed_end == np.datetime64("2025-01-03", "D")


def test_construct_rejects_non_1d_business_days() -> None:
    arr = np.array(
        [["2025-01-02", "2025-01-03"], ["2025-01-06", "2025-01-07"]],
        dtype="datetime64[D]",
    )
    with pytest.raises(Exception):
        MxMBusinessCalendar(
            calendar_id="bad_shape",
            business_days=arr,
            observed_end=np.datetime64("2025-01-07", "D"),
        )


def test_construct_rejects_empty_business_days() -> None:
    with pytest.raises(Exception):
        MxMBusinessCalendar(
            calendar_id="empty",
            business_days=np.array([], dtype="datetime64[D]"),
            observed_end=np.datetime64("2025-01-01", "D"),
        )


def test_construct_rejects_duplicate_business_days() -> None:
    # If ensure_1d_day_array normalizes instead of rejecting, update this test
    # to assert the normalized contract instead.
    with pytest.raises(Exception):
        MxMBusinessCalendar(
            calendar_id="dup",
            business_days=_days("2025-01-02", "2025-01-02", "2025-01-03"),
            observed_end=np.datetime64("2025-01-03", "D"),
        )


def test_construct_rejects_non_monotone_business_days() -> None:
    # If ensure_1d_day_array sorts instead of rejecting, update this test
    # to assert the normalized contract instead.
    with pytest.raises(Exception):
        MxMBusinessCalendar(
            calendar_id="unsorted",
            business_days=_days("2025-01-03", "2025-01-02", "2025-01-06"),
            observed_end=np.datetime64("2025-01-06", "D"),
        )


def test_calendar_is_frozen(compact_calendar: MxMBusinessCalendar) -> None:
    with pytest.raises(Exception):
        compact_calendar.calendar_id = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Membership / observed-projected classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-01-02", True),
        ("2025-01-03", True),
        ("2025-01-04", False),  # gap / weekend-like
        ("2025-01-05", False),  # gap / weekend-like
        ("2025-01-06", True),
        ("2025-01-09", False),  # after last
        ("2025-01-01", False),  # before first
    ],
)
def test_is_business_day(
    compact_calendar: MxMBusinessCalendar, value: str, expected: bool
) -> None:
    assert compact_calendar.is_business_day(value) is expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025-01-02", False),  # observed
        ("2025-01-03", False),  # observed
        ("2025-01-06", False),  # observed_end itself is observed, not projected
        ("2025-01-07", True),  # projected
        ("2025-01-08", True),  # projected
        ("2025-01-09", False),  # non-business day
        ("2025-01-05", False),  # non-business day
    ],
)
def test_is_projected_day(
    compact_calendar: MxMBusinessCalendar, value: str, expected: bool
) -> None:
    assert compact_calendar.is_projected_day(value) is expected


def test_is_business_day_accepts_np_datetime64(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.is_business_day(np.datetime64("2025-01-06", "D")) is True
    assert compact_calendar.is_business_day(np.datetime64("2025-01-05", "D")) is False


# ---------------------------------------------------------------------------
# normalize
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("how", ["raise", "next", "prev"])
def test_normalize_exact_business_day_returns_same_day(
    compact_calendar: MxMBusinessCalendar,
    how: str,
) -> None:
    out = compact_calendar.normalize("2025-01-06", how=how)  # type: ignore[arg-type]
    assert out == np.datetime64("2025-01-06", "D")


def test_normalize_raise_rejects_non_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="is not a business day"):
        compact_calendar.normalize("2025-01-05", how="raise")


def test_normalize_next_returns_first_business_day_on_or_after_gap_date(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.normalize("2025-01-05", how="next") == np.datetime64(
        "2025-01-06", "D"
    )


def test_normalize_prev_returns_last_business_day_on_or_before_gap_date(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.normalize("2025-01-05", how="prev") == np.datetime64(
        "2025-01-03", "D"
    )


def test_normalize_next_before_first_returns_first_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.normalize("2025-01-01", how="next") == np.datetime64(
        "2025-01-02", "D"
    )


def test_normalize_prev_before_first_raises(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="before first available business day"):
        compact_calendar.normalize("2025-01-01", how="prev")


def test_normalize_prev_after_last_returns_last_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.normalize("2025-01-09", how="prev") == np.datetime64(
        "2025-01-08", "D"
    )


def test_normalize_next_after_last_raises(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="after last available business day"):
        compact_calendar.normalize("2025-01-09", how="next")


def test_normalize_unknown_policy_raises(compact_calendar: MxMBusinessCalendar) -> None:
    with pytest.raises(ValueError, match="Unknown normalize policy"):
        compact_calendar.normalize("2025-01-06", how="bad")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# next_business_day / prev_business_day
# ---------------------------------------------------------------------------


def test_next_business_day_strict_from_valid_business_day_returns_next(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.next_business_day("2025-01-03") == np.datetime64(
        "2025-01-06", "D"
    )


def test_prev_business_day_strict_from_valid_business_day_returns_previous(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.prev_business_day("2025-01-06") == np.datetime64(
        "2025-01-03", "D"
    )


def test_next_business_day_strict_raises_for_non_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="is not a business day"):
        compact_calendar.next_business_day("2025-01-05", strict=True)


def test_prev_business_day_strict_raises_for_non_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="is not a business day"):
        compact_calendar.prev_business_day("2025-01-05", strict=True)


def test_next_business_day_non_strict_from_gap_returns_first_business_day_after_date(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.next_business_day(
        "2025-01-05", strict=False
    ) == np.datetime64("2025-01-06", "D")


def test_prev_business_day_non_strict_from_gap_returns_last_business_day_before_date(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.prev_business_day(
        "2025-01-05", strict=False
    ) == np.datetime64("2025-01-03", "D")


def test_next_business_day_non_strict_exact_hit_returns_strictly_next_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.next_business_day(
        "2025-01-06", strict=False
    ) == np.datetime64("2025-01-07", "D")


def test_prev_business_day_non_strict_exact_hit_returns_strictly_previous_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.prev_business_day(
        "2025-01-06", strict=False
    ) == np.datetime64("2025-01-03", "D")


def test_next_business_day_at_last_business_day_raises(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="No next business day after"):
        compact_calendar.next_business_day("2025-01-08")


def test_prev_business_day_at_first_business_day_raises(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="No previous business day before"):
        compact_calendar.prev_business_day("2025-01-02")


def test_next_business_day_non_strict_after_last_raises(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="No next business day after"):
        compact_calendar.next_business_day("2025-01-09", strict=False)


def test_prev_business_day_non_strict_before_first_raises(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="No previous business day before"):
        compact_calendar.prev_business_day("2025-01-01", strict=False)


# ---------------------------------------------------------------------------
# add_business_days
# ---------------------------------------------------------------------------


def test_add_business_days_zero_returns_same_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.add_business_days("2025-01-06", 0) == np.datetime64(
        "2025-01-06", "D"
    )


def test_add_business_days_positive_offset_returns_later_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.add_business_days("2025-01-03", 2) == np.datetime64(
        "2025-01-07", "D"
    )


def test_add_business_days_negative_offset_returns_earlier_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    assert compact_calendar.add_business_days("2025-01-07", -2) == np.datetime64(
        "2025-01-03", "D"
    )


def test_add_business_days_can_cross_observed_projected_boundary(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    # observed_end is 2025-01-06; adding 1 crosses into projected region
    assert compact_calendar.add_business_days("2025-01-06", 1) == np.datetime64(
        "2025-01-07", "D"
    )


def test_add_business_days_strict_raises_for_non_business_start(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="is not a business day"):
        compact_calendar.add_business_days("2025-01-05", 1, strict=True)


def test_add_business_days_non_strict_normalize_next_then_offset(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    # 2025-01-05 normalizes to 2025-01-06, then +1 -> 2025-01-07
    assert compact_calendar.add_business_days(
        "2025-01-05",
        1,
        strict=False,
        normalize_how="next",
    ) == np.datetime64("2025-01-07", "D")


def test_add_business_days_non_strict_normalize_prev_then_offset(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    # 2025-01-05 normalizes to 2025-01-03, then +1 -> 2025-01-06
    assert compact_calendar.add_business_days(
        "2025-01-05",
        1,
        strict=False,
        normalize_how="prev",
    ) == np.datetime64("2025-01-06", "D")


def test_add_business_days_positive_overflow_raises(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="Result out of range"):
        compact_calendar.add_business_days("2025-01-08", 1)


def test_add_business_days_negative_overflow_raises(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="Result out of range"):
        compact_calendar.add_business_days("2025-01-02", -1)


# ---------------------------------------------------------------------------
# business_days_between
# ---------------------------------------------------------------------------


def test_business_days_between_both_includes_both_endpoints(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    out = compact_calendar.business_days_between(
        "2025-01-03",
        "2025-01-07",
        inclusive="both",
    )
    assert np.array_equal(out, _days("2025-01-03", "2025-01-06", "2025-01-07"))


def test_business_days_between_left_excludes_right_endpoint(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    out = compact_calendar.business_days_between(
        "2025-01-03",
        "2025-01-07",
        inclusive="left",
    )
    assert np.array_equal(out, _days("2025-01-03", "2025-01-06"))


def test_business_days_between_right_excludes_left_endpoint(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    out = compact_calendar.business_days_between(
        "2025-01-03",
        "2025-01-07",
        inclusive="right",
    )
    assert np.array_equal(out, _days("2025-01-06", "2025-01-07"))


def test_business_days_between_neither_excludes_both_endpoints(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    out = compact_calendar.business_days_between(
        "2025-01-03",
        "2025-01-07",
        inclusive="neither",
    )
    assert np.array_equal(out, _days("2025-01-06"))


def test_business_days_between_same_day_both_returns_singleton(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    out = compact_calendar.business_days_between(
        "2025-01-06",
        "2025-01-06",
        inclusive="both",
    )
    assert np.array_equal(out, _days("2025-01-06"))


@pytest.mark.parametrize("inclusive", ["left", "right", "neither"])
def test_business_days_between_same_day_non_both_returns_empty(
    compact_calendar: MxMBusinessCalendar,
    inclusive: str,
) -> None:
    out = compact_calendar.business_days_between(
        "2025-01-06",
        "2025-01-06",
        inclusive=inclusive,  # type: ignore[arg-type]
    )
    assert out.dtype == np.dtype("datetime64[D]")
    assert out.size == 0


def test_business_days_between_open_interval_over_adjacent_days_returns_empty(
    two_day_calendar: MxMBusinessCalendar,
) -> None:
    out = two_day_calendar.business_days_between(
        "2025-01-02",
        "2025-01-03",
        inclusive="neither",
    )
    assert out.dtype == np.dtype("datetime64[D]")
    assert out.size == 0


def test_business_days_between_raises_when_start_after_end(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="start .* is after end"):
        compact_calendar.business_days_between("2025-01-07", "2025-01-03")


def test_business_days_between_strict_raises_when_start_is_not_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="start .* is not a business day"):
        compact_calendar.business_days_between(
            "2025-01-05",
            "2025-01-07",
            strict=True,
        )


def test_business_days_between_strict_raises_when_end_is_not_business_day(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="end .* is not a business day"):
        compact_calendar.business_days_between(
            "2025-01-03",
            "2025-01-05",
            strict=True,
        )


def test_business_days_between_non_strict_normalizes_start_and_end(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    # start 2025-01-05 -> next => 2025-01-06
    # end   2025-01-05 -> prev => 2025-01-03
    # This would reverse the interval if used that way, so choose a coherent case:
    out = compact_calendar.business_days_between(
        "2025-01-05",  # -> 2025-01-06 via next
        "2025-01-08",  # exact
        strict=False,
        normalize_start="next",
        normalize_end="raise",
        inclusive="both",
    )
    assert np.array_equal(out, _days("2025-01-06", "2025-01-07", "2025-01-08"))


def test_business_days_between_non_strict_can_return_empty_after_normalization(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    # start 2025-01-05 -> prev => 2025-01-03
    # end   2025-01-06 -> exact
    # open interval between adjacent retained dates => empty
    out = compact_calendar.business_days_between(
        "2025-01-05",
        "2025-01-06",
        strict=False,
        normalize_start="prev",
        normalize_end="raise",
        inclusive="neither",
    )
    assert out.dtype == np.dtype("datetime64[D]")
    assert out.size == 0


def test_business_days_between_returns_copy_not_view(
    compact_calendar: MxMBusinessCalendar,
) -> None:
    out = compact_calendar.business_days_between("2025-01-03", "2025-01-07")
    out[0] = np.datetime64("1999-01-01", "D")

    assert np.array_equal(
        compact_calendar.business_days,
        _days(
            "2025-01-02",
            "2025-01-03",
            "2025-01-06",
            "2025-01-07",
            "2025-01-08",
        ),
    )


# ---------------------------------------------------------------------------
# Singleton edge cases
# ---------------------------------------------------------------------------


def test_singleton_next_business_day_raises(
    singleton_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="No next business day after"):
        singleton_calendar.next_business_day("2025-01-06")


def test_singleton_prev_business_day_raises(
    singleton_calendar: MxMBusinessCalendar,
) -> None:
    with pytest.raises(ValueError, match="No previous business day before"):
        singleton_calendar.prev_business_day("2025-01-06")


def test_singleton_add_zero_returns_same_day(
    singleton_calendar: MxMBusinessCalendar,
) -> None:
    assert singleton_calendar.add_business_days("2025-01-06", 0) == np.datetime64(
        "2025-01-06", "D"
    )
