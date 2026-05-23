from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from mxm.moneymachine.marketdata.schema.daily_mark import (
    coerce_daily_mark,
    hash_daily_mark_content,
)
from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout
from mxm.moneymachine.marketdata.stores.parquet.daily_mark import (
    ensure_daily_mark_meta,
    read_daily_mark,
    read_daily_mark_meta,
    write_daily_mark,
)


def _layout(tmp_path: Path) -> MarketdataLayout:
    return MarketdataLayout(root=tmp_path)


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


def test_write_daily_mark_writes_parquet_and_meta(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"
    df = _base_df()

    result = write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=df,
    )

    assert result["wrote"] is True
    assert result["rows"] == 4
    assert result["calendar_id"] == calendar_id
    assert result["min_session_id"] == 0
    assert result["max_session_id"] == 3
    path = result["path"]
    meta_path = result["meta_path"]
    assert isinstance(path, Path)
    assert isinstance(meta_path, Path)
    assert path.exists()
    assert meta_path.exists()

    expected_path = layout.daily_mark_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    assert path == expected_path


def test_read_daily_mark_roundtrips_canonical_content(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"
    df = _base_df()

    write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=df,
    )

    got = read_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    expected = coerce_daily_mark(df, ensure_column_order=True)

    pd.testing.assert_frame_equal(got, expected)


def test_write_daily_mark_meta_contains_expected_fields(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"
    df = _base_df()

    write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=df,
        source_content_sha256="upstream-sha-123",
    )

    meta = read_daily_mark_meta(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    assert meta is not None
    assert meta["schema"] == "daily_mark"
    assert meta["schema_version"] == "1"
    assert meta["contract_id"] == contract_id
    assert meta["calendar_id"] == calendar_id
    assert meta["row_count"] == 4
    assert meta["min_session_id"] == 0
    assert meta["max_session_id"] == 3
    assert meta["source_schema"] == "daily_stats"
    assert meta["source_content_sha256"] == "upstream-sha-123"

    assert isinstance(meta["mxm_schema_columns"], list)
    assert isinstance(meta["content_sha256"], str)
    assert isinstance(meta["artifact_sha256"], str)
    assert isinstance(meta["updated_at"], str)

    quality_counts = meta["quality_counts"]
    assert quality_counts == {
        "carried": 1,
        "final": 1,
        "observed_fallback": 1,
        "unavailable": 1,
    }


def test_read_daily_mark_meta_returns_none_when_missing(tmp_path: Path) -> None:
    layout = _layout(tmp_path)

    meta = read_daily_mark_meta(
        layout=layout,
        calendar_id="mxm_business_days_v1",
        contract_id="CME.ESM2025",
    )

    assert meta is None


def test_write_daily_mark_skip_if_unchanged_returns_wrote_false(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"
    df = _base_df()

    first = write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=df,
        source_content_sha256="upstream-sha-123",
        skip_if_unchanged=True,
    )
    second = write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=df,
        source_content_sha256="upstream-sha-123",
        skip_if_unchanged=True,
    )

    assert first["wrote"] is True
    assert second["wrote"] is False
    assert second["rows"] == 4
    assert second["calendar_id"] == calendar_id
    assert second["content_sha256"] == first["content_sha256"]
    assert second["artifact_sha256"] == first["artifact_sha256"]


def test_ensure_daily_mark_meta_rebuilds_missing_meta(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"
    df = _base_df()

    result = write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=df,
        source_content_sha256="upstream-sha-123",
    )

    meta_path = result["meta_path"]
    assert isinstance(meta_path, Path)
    assert meta_path.exists()

    meta_path.unlink()
    assert not meta_path.exists()

    rebuilt = ensure_daily_mark_meta(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        source_content_sha256="upstream-sha-123",
        force=False,
    )

    assert meta_path.exists()
    assert rebuilt["schema"] == "daily_mark"
    assert rebuilt["contract_id"] == contract_id
    assert rebuilt["calendar_id"] == calendar_id
    assert rebuilt["row_count"] == 4
    assert rebuilt["min_session_id"] == 0
    assert rebuilt["max_session_id"] == 3
    assert rebuilt["source_content_sha256"] == "upstream-sha-123"


def test_ensure_daily_mark_meta_raises_if_parquet_missing(tmp_path: Path) -> None:
    layout = _layout(tmp_path)

    with pytest.raises(FileNotFoundError, match=r"daily_mark not found"):
        _ = ensure_daily_mark_meta(
            layout=layout,
            calendar_id="mxm_business_days_v1",
            contract_id="CME.ESM2025",
            force=False,
        )


def test_read_daily_mark_filters_by_start_session_id(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
    )

    got = read_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        start_session_id=2,
    )

    assert got["session_id"].tolist() == [2, 3]


def test_read_daily_mark_filters_by_end_session_id(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
    )

    got = read_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        end_session_id=2,
    )

    assert got["session_id"].tolist() == [0, 1]


def test_read_daily_mark_filters_by_half_open_interval(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
    )

    got = read_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        start_session_id=1,
        end_session_id=3,
    )

    assert got["session_id"].tolist() == [1, 2]


def test_read_daily_mark_returns_empty_frame_when_interval_excludes_all_rows(
    tmp_path: Path,
) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
    )

    got = read_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        start_session_id=10,
        end_session_id=20,
    )

    assert got.empty
    assert list(got.columns) == list(coerce_daily_mark(_base_df()).columns)


def test_daily_mark_paths_are_separate_across_calendar_id(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    contract_id = "CME.ESM2025"
    df = _base_df()

    write_daily_mark(
        layout=layout,
        calendar_id="mxm_business_days_v1",
        contract_id=contract_id,
        df_new=df,
    )
    write_daily_mark(
        layout=layout,
        calendar_id="mxm_business_days_v2",
        contract_id=contract_id,
        df_new=df,
    )

    path_v1 = layout.daily_mark_path(
        calendar_id="mxm_business_days_v1",
        contract_id=contract_id,
    )
    path_v2 = layout.daily_mark_path(
        calendar_id="mxm_business_days_v2",
        contract_id=contract_id,
    )

    assert path_v1 != path_v2
    assert path_v1.exists()
    assert path_v2.exists()


def test_daily_mark_paths_are_separate_across_contract_id(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"

    df_a = _base_df()
    df_b = _base_df().copy()
    df_b["contract_id"] = "CME.ESU2025"

    write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id="CME.ESM2025",
        df_new=df_a,
    )
    write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id="CME.ESU2025",
        df_new=df_b,
    )

    path_a = layout.daily_mark_path(
        calendar_id=calendar_id,
        contract_id="CME.ESM2025",
    )
    path_b = layout.daily_mark_path(
        calendar_id=calendar_id,
        contract_id="CME.ESU2025",
    )

    assert path_a != path_b
    assert path_a.exists()
    assert path_b.exists()


def test_write_daily_mark_rejects_mismatched_contract_id(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    df = _base_df()

    with pytest.raises(
        ValueError,
        match=r"write_daily_mark requires dataframe content to match requested contract_id",
    ):
        _ = write_daily_mark(
            layout=layout,
            calendar_id="mxm_business_days_v1",
            contract_id="CME.ESU2025",
            df_new=df,
        )


def test_ensure_daily_mark_meta_rebuilds_corrupt_meta(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    result = write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
    )

    meta_path = result["meta_path"]
    assert isinstance(meta_path, Path)
    meta_path.write_text("{ not valid json", encoding="utf-8")

    rebuilt = ensure_daily_mark_meta(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        force=False,
    )

    assert rebuilt["schema"] == "daily_mark"
    assert rebuilt["contract_id"] == contract_id
    assert rebuilt["calendar_id"] == calendar_id

    meta_from_disk = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta_from_disk["schema"] == "daily_mark"
    assert meta_from_disk["contract_id"] == contract_id
    assert meta_from_disk["calendar_id"] == calendar_id


def test_write_daily_mark_meta_content_hash_matches_schema_hash(tmp_path: Path) -> None:
    layout = _layout(tmp_path)
    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"
    df = _base_df()

    write_daily_mark(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=df,
    )

    meta = read_daily_mark_meta(
        layout=layout,
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    assert meta is not None

    expected_hash = hash_daily_mark_content(df)
    assert meta["content_sha256"] == expected_hash
