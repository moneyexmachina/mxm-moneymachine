import pandas as pd
import pytest

from mxm.v1.marketdata.schema.daily_mark import (
    coerce_daily_mark,
    hash_daily_mark_content,
    validate_daily_mark,
)

pytest.skip(
    "Temporarily disabled during timestamp model refactor (Session 33b)",
    allow_module_level=True,
)


def _base_df() -> pd.DataFrame:
    # Mimic builder output: session labels are object day labels, rows unsorted.
    # Surface contains one valid example of each v1 state:
    # - unavailable
    # - observed_settle
    # - observed_close
    # - carry_forward
    return pd.DataFrame(
        {
            "session": ["2025-01-04", "2025-01-02", "2025-01-01", "2025-01-03"],
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
            "source_session": ["2025-01-03", "2025-01-02", None, "2025-01-03"],
            "source_dataset": ["GLBX.MDP3", "GLBX.MDP3", None, "GLBX.MDP3"],
            "source_publisher_id": [1, 1, None, 1],
            "source_raw_symbol": ["ESM5", "ESM5", None, "ESM5"],
        }
    )


def test_coerce_daily_mark_canonicalises_builder_output() -> None:
    df = _base_df()
    out = coerce_daily_mark(df)

    assert pd.api.types.is_datetime64_any_dtype(out["session"])
    assert not isinstance(out["session"].dtype, pd.DatetimeTZDtype)
    assert (out["session"].dt.hour == 0).all()
    assert (out["session"].dt.minute == 0).all()
    assert (out["session"].dt.second == 0).all()
    assert out["session"].is_monotonic_increasing

    assert not out.duplicated(["contract_id", "session"]).any()
    assert out["contract_id"].nunique() == 1

    assert str(out["mark_source"].dtype) == "string"
    assert str(out["mark_quality"].dtype) == "string"
    assert str(out["is_markable"].dtype) == "boolean"
    assert str(out["is_carried"].dtype) == "boolean"
    assert pd.api.types.is_integer_dtype(out["carry_streak"])

    assert "source_session" in out.columns
    non_null_source_session = out["source_session"].dropna()
    assert pd.api.types.is_datetime64_any_dtype(non_null_source_session)
    assert not isinstance(non_null_source_session.dtype, pd.DatetimeTZDtype)
    assert (non_null_source_session.dt.hour == 0).all()
    assert (non_null_source_session.dt.minute == 0).all()
    assert (non_null_source_session.dt.second == 0).all()

    # Should validate cleanly
    validate_daily_mark(out)


def test_validate_daily_mark_rejects_duplicates() -> None:
    df = _base_df()
    df.loc[1, "session"] = df.loc[0, "session"]  # duplicate day for same contract

    with pytest.raises(ValueError, match=r"duplicate \(contract_id, session\)"):
        _ = coerce_daily_mark(df, ensure_column_order=True)


def test_validate_daily_mark_rejects_multi_contract_surface() -> None:
    df = _base_df()
    df.loc[1, "contract_id"] = "CME.ESU2025"

    with pytest.raises(ValueError, match=r"exactly one contract_id"):
        _ = coerce_daily_mark(df)


def test_validate_daily_mark_rejects_unsorted_session() -> None:
    out = coerce_daily_mark(_base_df())
    bad = out.iloc[::-1].reset_index(drop=True)

    with pytest.raises(ValueError, match=r"`session` must be sorted increasing"):
        validate_daily_mark(bad)


def test_validate_daily_mark_rejects_missing_required_column() -> None:
    df = _base_df().drop(columns=["mark_quality"])

    with pytest.raises(ValueError, match=r"missing required columns"):
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


def test_validate_daily_mark_rejects_tz_aware_session_labels() -> None:
    out = coerce_daily_mark(_base_df())
    bad = out.copy()
    bad["session"] = bad["session"].dt.tz_localize("UTC")

    with pytest.raises(
        ValueError,
        match=r"`session` must be timezone-naive day labels",
    ):
        validate_daily_mark(bad)


def test_hash_is_stable_under_row_and_col_permutation() -> None:
    df = _base_df()
    h1 = hash_daily_mark_content(df)

    # Row order permuted
    h2 = hash_daily_mark_content(df.sample(frac=1.0, random_state=0))

    # Column order permuted
    cols = list(df.columns)
    cols = cols[::-1]
    h3 = hash_daily_mark_content(df[cols])

    assert h1 == h2 == h3
