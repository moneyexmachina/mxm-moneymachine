import pandas as pd

from mxm.moneymachine.marketdata.schema.daily_mark import hash_daily_mark_content


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


def test_hash_daily_mark_is_stable_under_row_permutation() -> None:
    df = _base_df()

    h1 = hash_daily_mark_content(df)
    h2 = hash_daily_mark_content(df.sample(frac=1.0, random_state=0))

    assert h1 == h2


def test_hash_daily_mark_is_stable_under_column_permutation() -> None:
    df = _base_df()

    h1 = hash_daily_mark_content(df)

    cols = list(df.columns)[::-1]
    h2 = hash_daily_mark_content(df[cols])

    assert h1 == h2


def test_hash_daily_mark_is_stable_under_builder_like_dtype_variation() -> None:
    df = _base_df()

    h1 = hash_daily_mark_content(df)

    # Same semantic content, but with deliberately looser / different
    # pre-coercion representations that should canonicalize identically.
    df_variant = pd.DataFrame(
        {
            "session_id": pd.Series([3, 1, 0, 2], dtype="int64"),
            "contract_id": pd.Series(["CME.ESM2025"] * 4, dtype="object"),
            "instrument_id": pd.Series([4916, 4916, 4916, 4916], dtype="int64"),
            "mark_px": pd.Series([100.5, 100.0, None, 100.2], dtype="float64"),
            "mark_source": pd.Series(
                [
                    "carry_forward",
                    "observed_settle",
                    "unavailable",
                    "observed_close",
                ],
                dtype="object",
            ),
            "mark_quality": pd.Series(
                [
                    "carried",
                    "final",
                    "unavailable",
                    "observed_fallback",
                ],
                dtype="object",
            ),
            "is_markable": pd.Series([True, True, False, True], dtype="object"),
            "is_carried": pd.Series([True, False, False, False], dtype="object"),
            "carry_streak": pd.Series([1, 0, 0, 0], dtype="int64"),
            "source_trading_date": pd.Series(
                ["2025-01-03", "2025-01-02", None, "2025-01-03"],
                dtype="object",
            ),
            "source_dataset": pd.Series(
                ["GLBX.MDP3", "GLBX.MDP3", None, "GLBX.MDP3"],
                dtype="object",
            ),
            "source_publisher_id": pd.Series([1, 1, None, 1], dtype="object"),
            "source_raw_symbol": pd.Series(
                ["ESM5", "ESM5", None, "ESM5"], dtype="object"
            ),
        }
    )

    h2 = hash_daily_mark_content(df_variant)

    assert h1 == h2


def test_hash_daily_mark_changes_when_semantic_content_changes() -> None:
    df = _base_df()
    h1 = hash_daily_mark_content(df)

    df_changed = df.copy()
    df_changed.loc[df_changed["session_id"] == 2, "mark_px"] = 100.25

    h2 = hash_daily_mark_content(df_changed)

    assert h1 != h2
