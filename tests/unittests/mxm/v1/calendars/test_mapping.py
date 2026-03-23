import numpy as np
import pytest

from mxm.v1.calendars.mapping import (
    CalendarMapping,
    MissingCalendarMapping,
    map_business_to_trading_sessions,
)


def _days(*xs: str) -> np.ndarray:
    return np.array(xs, dtype="datetime64[D]")


# ---------------------------------------------------------------------------
# CalendarMapping model
# ---------------------------------------------------------------------------


def test_calendar_mapping_constructs_valid_mapping() -> None:
    mapping = CalendarMapping(
        business_sessions=_days("2025-01-02", "2025-01-03", "2025-01-06"),
        mapped_sessions=_days("2025-01-02", "2025-01-03", "2025-01-06"),
        is_exact=np.array([True, True, True], dtype=bool),
        how="exact",
    )

    assert mapping.business_sessions.dtype == np.dtype("datetime64[D]")
    assert mapping.mapped_sessions.dtype == np.dtype("datetime64[D]")
    assert mapping.is_exact.dtype == np.dtype(bool)
    assert mapping.how == "exact"


def test_calendar_mapping_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="must have equal length"):
        CalendarMapping(
            business_sessions=_days("2025-01-02", "2025-01-03"),
            mapped_sessions=_days("2025-01-02"),
            is_exact=np.array([True, True], dtype=bool),
            how="exact",
        )


def test_calendar_mapping_rejects_non_1d_is_exact() -> None:
    with pytest.raises(TypeError, match="is_exact must be a 1D boolean array"):
        CalendarMapping(
            business_sessions=_days("2025-01-02", "2025-01-03"),
            mapped_sessions=_days("2025-01-02", "2025-01-03"),
            is_exact=np.array([[True, False]], dtype=bool),
            how="exact",
        )


def test_calendar_mapping_rejects_non_bool_is_exact() -> None:
    with pytest.raises(TypeError, match="is_exact must have dtype bool"):
        CalendarMapping(
            business_sessions=_days("2025-01-02", "2025-01-03"),
            mapped_sessions=_days("2025-01-02", "2025-01-03"),
            is_exact=np.array([1, 0], dtype=int),
            how="exact",
        )


def test_calendar_mapping_rejects_empty_business_sessions() -> None:
    with pytest.raises(ValueError):
        CalendarMapping(
            business_sessions=np.array([], dtype="datetime64[D]"),
            mapped_sessions=np.array([], dtype="datetime64[D]"),
            is_exact=np.array([], dtype=bool),
            how="exact",
        )


def test_calendar_mapping_counts_exact_and_inexact_rows() -> None:
    mapping = CalendarMapping(
        business_sessions=_days("2025-01-02", "2025-01-04", "2025-01-06"),
        mapped_sessions=_days("2025-01-02", "2025-01-03", "2025-01-06"),
        is_exact=np.array([True, False, True], dtype=bool),
        how="prev",
    )

    assert mapping.exact_count() == 2
    assert mapping.inexact_count() == 1


# ---------------------------------------------------------------------------
# exact
# ---------------------------------------------------------------------------


def test_map_business_to_trading_sessions_exact_returns_identity_mapping() -> None:
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-02", "2025-01-03", "2025-01-06")

    out = map_business_to_trading_sessions(
        business_sessions=business,
        trading_sessions=trading,
        how="exact",
    )

    assert np.array_equal(out.business_sessions, business)
    assert np.array_equal(out.mapped_sessions, business)
    assert np.array_equal(out.is_exact, np.array([True, True, True], dtype=bool))
    assert out.exact_count() == 3
    assert out.inexact_count() == 0


def test_map_business_to_trading_sessions_exact_raises_for_missing_middle_session() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-02", "2025-01-04", "2025-01-06")

    with pytest.raises(
        MissingCalendarMapping,
        match="no exact trading-session match",
    ):
        map_business_to_trading_sessions(
            business_sessions=business,
            trading_sessions=trading,
            how="exact",
        )


def test_map_business_to_trading_sessions_exact_raises_for_business_session_before_first_trading_session() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-01", "2025-01-02")

    with pytest.raises(
        MissingCalendarMapping,
        match="no exact trading-session match",
    ):
        map_business_to_trading_sessions(
            business_sessions=business,
            trading_sessions=trading,
            how="exact",
        )


def test_map_business_to_trading_sessions_exact_raises_for_business_session_after_last_trading_session() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-06", "2025-01-07")

    with pytest.raises(
        MissingCalendarMapping,
        match="no exact trading-session match",
    ):
        map_business_to_trading_sessions(
            business_sessions=business,
            trading_sessions=trading,
            how="exact",
        )


# ---------------------------------------------------------------------------
# prev
# ---------------------------------------------------------------------------


def test_map_business_to_trading_sessions_prev_maps_gap_days_to_previous_trading_session() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-02", "2025-01-04", "2025-01-05", "2025-01-06")

    out = map_business_to_trading_sessions(
        business_sessions=business,
        trading_sessions=trading,
        how="prev",
    )

    assert np.array_equal(out.business_sessions, business)
    assert np.array_equal(
        out.mapped_sessions,
        _days("2025-01-02", "2025-01-03", "2025-01-03", "2025-01-06"),
    )
    assert np.array_equal(
        out.is_exact,
        np.array([True, False, False, True], dtype=bool),
    )


def test_map_business_to_trading_sessions_prev_marks_exact_and_inexact_rows_correctly() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-03", "2025-01-04", "2025-01-06")

    out = map_business_to_trading_sessions(
        business_sessions=business,
        trading_sessions=trading,
        how="prev",
    )

    assert np.array_equal(
        out.mapped_sessions,
        _days("2025-01-03", "2025-01-03", "2025-01-06"),
    )
    assert np.array_equal(out.is_exact, np.array([True, False, True], dtype=bool))
    assert out.exact_count() == 2
    assert out.inexact_count() == 1


def test_map_business_to_trading_sessions_prev_raises_when_business_session_precedes_first_trading_session() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-01", "2025-01-02")

    with pytest.raises(
        MissingCalendarMapping,
        match="before first available trading session",
    ):
        map_business_to_trading_sessions(
            business_sessions=business,
            trading_sessions=trading,
            how="prev",
        )


def test_map_business_to_trading_sessions_prev_maps_after_last_business_session_to_last_trading_session() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-06", "2025-01-07", "2025-01-08")

    out = map_business_to_trading_sessions(
        business_sessions=business,
        trading_sessions=trading,
        how="prev",
    )

    assert np.array_equal(
        out.mapped_sessions,
        _days("2025-01-06", "2025-01-06", "2025-01-06"),
    )
    assert np.array_equal(out.is_exact, np.array([True, False, False], dtype=bool))


def test_map_business_to_trading_sessions_prev_maps_multiple_gap_days_to_same_previous_session() -> (
    None
):
    trading = _days("2025-01-03", "2025-01-06")
    business = _days("2025-01-04", "2025-01-05")

    out = map_business_to_trading_sessions(
        business_sessions=business,
        trading_sessions=trading,
        how="prev",
    )

    assert np.array_equal(
        out.mapped_sessions,
        _days("2025-01-03", "2025-01-03"),
    )
    assert np.array_equal(out.is_exact, np.array([False, False], dtype=bool))


# ---------------------------------------------------------------------------
# next
# ---------------------------------------------------------------------------


def test_map_business_to_trading_sessions_next_maps_gap_days_to_next_trading_session() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-02", "2025-01-04", "2025-01-05", "2025-01-06")

    out = map_business_to_trading_sessions(
        business_sessions=business,
        trading_sessions=trading,
        how="next",
    )

    assert np.array_equal(out.business_sessions, business)
    assert np.array_equal(
        out.mapped_sessions,
        _days("2025-01-02", "2025-01-06", "2025-01-06", "2025-01-06"),
    )
    assert np.array_equal(
        out.is_exact,
        np.array([True, False, False, True], dtype=bool),
    )


def test_map_business_to_trading_sessions_next_marks_exact_and_inexact_rows_correctly() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-02", "2025-01-05", "2025-01-06")

    out = map_business_to_trading_sessions(
        business_sessions=business,
        trading_sessions=trading,
        how="next",
    )

    assert np.array_equal(
        out.mapped_sessions,
        _days("2025-01-02", "2025-01-06", "2025-01-06"),
    )
    assert np.array_equal(out.is_exact, np.array([True, False, True], dtype=bool))
    assert out.exact_count() == 2
    assert out.inexact_count() == 1


def test_map_business_to_trading_sessions_next_maps_before_first_business_session_to_first_trading_session() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-01", "2025-01-02")

    out = map_business_to_trading_sessions(
        business_sessions=business,
        trading_sessions=trading,
        how="next",
    )

    assert np.array_equal(
        out.mapped_sessions,
        _days("2025-01-02", "2025-01-02"),
    )
    assert np.array_equal(out.is_exact, np.array([False, True], dtype=bool))


def test_map_business_to_trading_sessions_next_raises_when_business_session_exceeds_last_trading_session() -> (
    None
):
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-06", "2025-01-07")

    with pytest.raises(
        MissingCalendarMapping,
        match="after last available trading session",
    ):
        map_business_to_trading_sessions(
            business_sessions=business,
            trading_sessions=trading,
            how="next",
        )


def test_map_business_to_trading_sessions_next_maps_multiple_gap_days_to_same_next_session() -> (
    None
):
    trading = _days("2025-01-03", "2025-01-06")
    business = _days("2025-01-04", "2025-01-05")

    out = map_business_to_trading_sessions(
        business_sessions=business,
        trading_sessions=trading,
        how="next",
    )

    assert np.array_equal(
        out.mapped_sessions,
        _days("2025-01-06", "2025-01-06"),
    )
    assert np.array_equal(out.is_exact, np.array([False, False], dtype=bool))


def test_calendar_mapping_allows_repeated_mapped_sessions() -> None:
    mapping = CalendarMapping(
        business_sessions=_days("2025-01-04", "2025-01-05"),
        mapped_sessions=_days("2025-01-03", "2025-01-03"),
        is_exact=np.array([False, False], dtype=bool),
        how="prev",
    )
    assert np.array_equal(mapping.mapped_sessions, _days("2025-01-03", "2025-01-03"))


# ---------------------------------------------------------------------------
# policy validation
# ---------------------------------------------------------------------------


def test_map_business_to_trading_sessions_rejects_unknown_alignment_policy() -> None:
    trading = _days("2025-01-02", "2025-01-03", "2025-01-06")
    business = _days("2025-01-02", "2025-01-03")

    with pytest.raises(ValueError, match="Unknown alignment policy"):
        map_business_to_trading_sessions(
            business_sessions=business,
            trading_sessions=trading,
            how="bad",  # type: ignore[arg-type]
        )
