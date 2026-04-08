import pandas as pd
import pytest

from mxm.v1.marketdata.schema.daily_mark import (
    coerce_daily_mark,
    validate_daily_mark,
)


def _base_df() -> pd.DataFrame:
    """
    Mimic plausible builder output for a single-contract daily_mark surface.

    Deliberate properties of this fixture:
    - rows are unsorted by session_id
    - source_trading_date is provided as string-like day labels
    - surface contains one example of each v1 semantic state:
        - unavailable
        - observed_settle
        - observed_close
        - carry_forward
    """
    return pd.DataFrame(
        {
            "session_id": [3, 1, 0, 2],
            "contract_id": ["CME.ESM2025"] * 4,
            "instrument_id": [4916, 4916, 4916, 4916],
            "mark_px": [100.5, 100.0, None, 100.2],
            "mark_source": [
                "carry_forward",
                "observed_settle",
                "unavailable",
                "observed_close",
            ],
            "mark_quality": [
                "carried",
                "final",
                "unavailable",
                "observed_fallback",
            ],
            "is_markable": [True, True, False, True],
            "is_carried": [True, False, False, False],
            "carry_streak": [1, 0, 0, 0],
            "source_trading_date": ["2025-01-03", "2025-01-02", None, "2025-01-03"],
            "source_dataset": ["GLBX.MDP3", "GLBX.MDP3", None, "GLBX.MDP3"],
            "source_publisher_id": [1, 1, None, 1],
            "source_raw_symbol": ["ESM5", "ESM5", None, "ESM5"],
        }
    )


def test_validate_daily_mark_rejects_duplicates() -> None:
    df = _base_df()
    df.loc[1, "session_id"] = df.loc[0, "session_id"]

    with pytest.raises(ValueError, match=r"duplicate \(contract_id, session_id\)"):
        _ = coerce_daily_mark(df, ensure_column_order=True)


def test_validate_daily_mark_rejects_multi_contract_surface() -> None:
    df = _base_df()
    df.loc[1, "contract_id"] = "CME.ESU2025"

    with pytest.raises(ValueError, match=r"exactly one contract_id"):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_rejects_unsorted_session_id() -> None:
    out = coerce_daily_mark(_base_df())
    bad = out.iloc[::-1].reset_index(drop=True)

    with pytest.raises(ValueError, match=r"`session_id` must be sorted increasing"):
        validate_daily_mark(bad)


def test_validate_daily_mark_rejects_missing_required_column() -> None:
    df = _base_df().drop(columns=["mark_quality"])

    with pytest.raises(ValueError, match=r"missing required columns"):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_rejects_null_session_id() -> None:
    df = _base_df()
    df.loc[0, "session_id"] = None

    with pytest.raises(ValueError, match=r"`session_id` contains null values"):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_rejects_non_integer_session_id() -> None:
    df = _base_df()
    df["session_id"] = df["session_id"].astype("float64")
    df.loc[0, "session_id"] = 1.5

    with pytest.raises(ValueError, match=r"`session_id` must be integer dtype"):
        validate_daily_mark(df)


def test_validate_daily_mark_rejects_negative_session_id() -> None:
    df = _base_df()
    df.loc[0, "session_id"] = -1

    with pytest.raises(ValueError, match=r"`session_id` must be non-negative"):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_rejects_invalid_mark_source() -> None:
    df = _base_df()
    df.loc[1, "mark_source"] = "foo"

    with pytest.raises(ValueError, match=r"`mark_source` contains invalid values"):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_rejects_invalid_mark_quality() -> None:
    df = _base_df()
    df.loc[1, "mark_quality"] = "bar"

    with pytest.raises(ValueError, match=r"`mark_quality` contains invalid values"):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_unavailable_rows_require_null_mark() -> None:
    df = _base_df()
    unavailable_idx = df.index[df["mark_source"] == "unavailable"][0]
    df.loc[unavailable_idx, "mark_px"] = 99.9

    with pytest.raises(ValueError, match=r"unavailable rows must have null `mark_px`"):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_unavailable_rows_require_mark_quality_unavailable() -> (
    None
):
    df = _base_df()
    unavailable_idx = df.index[df["mark_source"] == "unavailable"][0]
    df.loc[unavailable_idx, "mark_quality"] = "carried"

    with pytest.raises(
        ValueError,
        match=r"inconsistent unavailable state: `mark_source` and `mark_quality` must agree",
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_unavailable_rows_require_is_markable_false() -> None:
    df = _base_df()
    unavailable_idx = df.index[df["mark_source"] == "unavailable"][0]
    df.loc[unavailable_idx, "is_markable"] = True

    with pytest.raises(
        ValueError, match=r"unavailable rows must have `is_markable=False`"
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_unavailable_rows_require_is_carried_false() -> None:
    df = _base_df()
    unavailable_idx = df.index[df["mark_source"] == "unavailable"][0]
    df.loc[unavailable_idx, "is_carried"] = True

    with pytest.raises(
        ValueError, match=r"unavailable rows must have `is_carried=False`"
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_unavailable_rows_require_zero_carry_streak() -> None:
    df = _base_df()
    unavailable_idx = df.index[df["mark_source"] == "unavailable"][0]
    df.loc[unavailable_idx, "carry_streak"] = 1

    with pytest.raises(
        ValueError, match=r"unavailable rows must have `carry_streak=0`"
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_carried_rows_require_carry_forward_source() -> None:
    df = _base_df()
    carried_idx = df.index[df["is_carried"] == True][0]  # noqa: E712
    df.loc[carried_idx, "mark_source"] = "observed_settle"

    with pytest.raises(
        ValueError,
        match=r"carried rows must have `mark_source='carry_forward'`",
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_carried_rows_require_carried_quality() -> None:
    df = _base_df()
    carried_idx = df.index[df["is_carried"] == True][0]  # noqa: E712
    df.loc[carried_idx, "mark_quality"] = "final"

    with pytest.raises(
        ValueError,
        match=r"carried rows must have `mark_quality='carried'`",
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_carried_rows_require_positive_carry_streak() -> None:
    df = _base_df()
    carried_idx = df.index[df["is_carried"] == True][0]  # noqa: E712
    df.loc[carried_idx, "carry_streak"] = 0

    with pytest.raises(
        ValueError,
        match=r"carried rows must have `carry_streak > 0`",
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_available_rows_require_non_null_mark() -> None:
    df = _base_df()
    avail_idx = df.index[df["mark_source"] == "observed_close"][0]
    df.loc[avail_idx, "mark_px"] = None

    with pytest.raises(
        ValueError,
        match=r"available rows must have non-null `mark_px`",
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_available_rows_require_is_markable_true() -> None:
    df = _base_df()
    avail_idx = df.index[df["mark_source"] == "observed_close"][0]
    df.loc[avail_idx, "is_markable"] = False

    with pytest.raises(
        ValueError,
        match=r"available rows must have `is_markable=True`",
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_non_carried_available_rows_require_zero_carry_streak() -> (
    None
):
    df = _base_df()
    idx = df.index[df["mark_source"] == "observed_settle"][0]
    df.loc[idx, "carry_streak"] = 2

    with pytest.raises(
        ValueError,
        match=r"non-carried available rows must have `carry_streak=0`",
    ):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_rejects_tz_aware_source_trading_date() -> None:
    out = coerce_daily_mark(_base_df())
    bad = out.copy()
    bad["source_trading_date"] = bad["source_trading_date"].dt.tz_localize("UTC")

    with pytest.raises(
        ValueError,
        match=r"`source_trading_date` must be timezone-naive day labels",
    ):
        validate_daily_mark(bad)


def test_validate_daily_mark_accepts_null_source_trading_date() -> None:
    out = coerce_daily_mark(_base_df())
    out["source_trading_date"] = pd.NaT

    validate_daily_mark(out)


def test_validate_daily_mark_rejects_invalid_source_trading_date() -> None:
    df = _base_df()
    df.loc[1, "source_trading_date"] = "not-a-date"

    with pytest.raises(ValueError, match=r"failed to coerce `source_trading_date`"):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_rejects_non_string_source_dataset() -> None:
    out = coerce_daily_mark(_base_df())
    bad = out.copy()
    bad["source_dataset"] = pd.Series([1, 2, None, 4], dtype="Int64")

    with pytest.raises(
        ValueError,
        match=r"`source_dataset` must be pandas string dtype if present",
    ):
        validate_daily_mark(bad)


def test_validate_daily_mark_rejects_non_integer_source_publisher_id() -> None:
    out = coerce_daily_mark(_base_df())
    bad = out.copy()
    bad["source_publisher_id"] = pd.Series(
        [1.0, 1.0, None, 1.0],
        dtype="Float64",
    )

    with pytest.raises(
        ValueError,
        match=r"`source_publisher_id` must be integer dtype if present",
    ):
        validate_daily_mark(bad)


def test_validate_daily_mark_rejects_non_string_source_raw_symbol() -> None:
    out = coerce_daily_mark(_base_df())
    bad = out.copy()
    bad["source_raw_symbol"] = pd.Series([1, 2, None, 4], dtype="Int64")

    with pytest.raises(
        ValueError,
        match=r"`source_raw_symbol` must be pandas string dtype if present",
    ):
        validate_daily_mark(bad)


def test_validate_daily_mark_rejects_non_integer_instrument_id() -> None:
    out = coerce_daily_mark(_base_df())
    bad = out.copy()
    bad["instrument_id"] = pd.Series(
        [4916.0, 4916.0, None, 4916.0],
        dtype="Float64",
    )

    with pytest.raises(
        ValueError,
        match=r"`instrument_id` must be integer dtype if present",
    ):
        validate_daily_mark(bad)
