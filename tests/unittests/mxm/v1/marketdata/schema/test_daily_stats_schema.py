import pandas as pd
import pytest

from mxm.v1.marketdata.schema.daily_stats import (
    coerce_daily_stats,
    hash_daily_stats_content,
    validate_daily_stats,
)


def _base_df() -> pd.DataFrame:
    # Mimic selection output: session_date is object day labels
    return pd.DataFrame(
        {
            "session_date": ["2025-01-02", "2025-01-01"],
            "instrument_id": [4916, 4916],
            "publisher_id": [1, 1],
            "dataset": ["GLBX.MDP3", "GLBX.MDP3"],
            "settle_px": [100.0, 99.0],
            "settle_px_is_final": [True, False],
            "fix_px": [100.1, 99.1],
            "fix_px_is_final": [True, True],
            "open_px": [99.5, 98.8],
            "high_px": [101.0, 99.7],
            "low_px": [98.9, 98.0],
            "open_interest_qty": [12345, 12000],
            "cleared_volume_qty": [5000, 4800],
        }
    )


def test_coerce_daily_stats_canonicalises_selection_output() -> None:
    df = _base_df()
    out = coerce_daily_stats(df)
    assert isinstance(out["session_date"].dtype, pd.DatetimeTZDtype)
    assert str(out["session_date"].dtype.tz) == "UTC"
    assert (out["session_date"].dt.hour == 0).all()
    assert out["session_date"].is_monotonic_increasing
    assert not out.duplicated(["instrument_id", "session_date"]).any()
    assert out["instrument_id"].nunique() == 1
    assert str(out["settle_px_is_final"].dtype) == "boolean"
    assert str(out["fix_px_is_final"].dtype) == "boolean"

    # Should validate cleanly
    validate_daily_stats(out)


def test_validate_daily_stats_rejects_duplicates() -> None:
    df = _base_df()
    df.loc[1, "session_date"] = df.loc[0, "session_date"]  # duplicate day

    with pytest.raises(ValueError, match=r"duplicate \(instrument_id, session_date\)"):
        _ = coerce_daily_stats(df, ensure_column_order=True)


def test_validate_daily_stats_rejects_multi_instrument_surface() -> None:
    df = _base_df()
    df.loc[1, "instrument_id"] = 9999

    with pytest.raises(ValueError, match=r"exactly one instrument_id"):
        _ = coerce_daily_stats(df)


def test_hash_is_stable_under_row_and_col_permutation() -> None:
    df = _base_df()
    h1 = hash_daily_stats_content(df)

    # Row order permuted
    h2 = hash_daily_stats_content(df.sample(frac=1.0, random_state=0))

    # Column order permuted
    cols = list(df.columns)
    cols = cols[::-1]
    h3 = hash_daily_stats_content(df[cols])

    assert h1 == h2 == h3
