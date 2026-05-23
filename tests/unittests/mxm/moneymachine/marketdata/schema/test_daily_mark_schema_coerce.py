import pandas as pd
import pytest

from mxm.moneymachine.marketdata.schema.daily_mark import (
    DAILY_MARK,
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


def test_coerce_daily_mark_canonicalises_builder_output() -> None:
    df = _base_df()
    out = coerce_daily_mark(df)

    # Primary MXM business-time coordinate
    assert pd.api.types.is_integer_dtype(out["session_id"])
    assert out["session_id"].tolist() == [0, 1, 2, 3]
    assert out["session_id"].is_monotonic_increasing
    assert not out.duplicated(["contract_id", "session_id"]).any()

    # Contract surface identity
    assert str(out["contract_id"].dtype) == "string"
    assert out["contract_id"].nunique() == 1

    # Core semantic columns
    assert str(out["mark_source"].dtype) == "string"
    assert str(out["mark_quality"].dtype) == "string"
    assert str(out["is_markable"].dtype) == "boolean"
    assert str(out["is_carried"].dtype) == "boolean"
    assert pd.api.types.is_integer_dtype(out["carry_streak"])

    # Optional provenance fields
    assert "instrument_id" in out.columns
    assert pd.api.types.is_integer_dtype(out["instrument_id"])

    assert "source_trading_date" in out.columns
    non_null_source_trading_date = out["source_trading_date"].dropna()
    assert pd.api.types.is_datetime64_any_dtype(non_null_source_trading_date)
    assert not isinstance(non_null_source_trading_date.dtype, pd.DatetimeTZDtype)
    assert (non_null_source_trading_date.dt.hour == 0).all()
    assert (non_null_source_trading_date.dt.minute == 0).all()
    assert (non_null_source_trading_date.dt.second == 0).all()
    assert (non_null_source_trading_date.dt.microsecond == 0).all()
    assert (non_null_source_trading_date.dt.nanosecond == 0).all()

    assert "source_dataset" in out.columns
    assert str(out["source_dataset"].dtype) == "string"

    assert "source_publisher_id" in out.columns
    assert pd.api.types.is_integer_dtype(out["source_publisher_id"])

    assert "source_raw_symbol" in out.columns
    assert str(out["source_raw_symbol"].dtype) == "string"

    # Should validate cleanly
    validate_daily_mark(out)


def test_coerce_daily_mark_enforces_canonical_column_order() -> None:
    df = _base_df()

    # Deliberately scramble columns to mimic non-canonical builder output.
    scrambled_cols = list(df.columns)[::-1]
    out = coerce_daily_mark(df[scrambled_cols], ensure_column_order=True)

    expected_cols = [c for c in DAILY_MARK.columns if c in df.columns]
    assert list(out.columns) == expected_cols

    validate_daily_mark(out)


def test_coerce_daily_mark_preserves_optional_columns_when_present() -> None:
    df = _base_df()
    out = coerce_daily_mark(df)

    for col in (
        "instrument_id",
        "source_trading_date",
        "source_dataset",
        "source_publisher_id",
        "source_raw_symbol",
    ):
        assert col in out.columns

    validate_daily_mark(out)


def test_coerce_daily_mark_allows_missing_optional_columns() -> None:
    df = _base_df().drop(
        columns=[
            "instrument_id",
            "source_trading_date",
            "source_dataset",
            "source_publisher_id",
            "source_raw_symbol",
        ]
    )

    out = coerce_daily_mark(df)

    assert list(out.columns) == list(DAILY_MARK.required)
    validate_daily_mark(out)


def test_coerce_daily_mark_rejects_invalid_source_trading_date() -> None:
    df = _base_df()
    df.loc[1, "source_trading_date"] = "not-a-date"

    with pytest.raises(ValueError, match=r"failed to coerce `source_trading_date`"):
        coerce_daily_mark(df)
