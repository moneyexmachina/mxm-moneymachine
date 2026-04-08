from __future__ import annotations

from pathlib import Path

import pandas as pd

from mxm.v1.marketdata.datasets.daily_mark.store import DailyMarkStore
from mxm.v1.marketdata.schema.daily_mark import coerce_daily_mark
from mxm.v1.marketdata.stores.layout import MarketdataLayout


def _layout(tmp_path: Path) -> MarketdataLayout:
    return MarketdataLayout(root=tmp_path)


def _store(tmp_path: Path) -> DailyMarkStore:
    return DailyMarkStore(layout=_layout(tmp_path))


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


def test_daily_mark_store_mark_path_matches_layout(tmp_path: Path) -> None:
    store = _store(tmp_path)
    layout = _layout(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    got = store.mark_path(calendar_id=calendar_id, contract_id=contract_id)
    expected = layout.daily_mark_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    assert got == expected


def test_daily_mark_store_meta_path_matches_layout(tmp_path: Path) -> None:
    store = _store(tmp_path)
    layout = _layout(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    got = store.meta_path(calendar_id=calendar_id, contract_id=contract_id)
    expected = layout.daily_mark_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    ).with_name("daily_mark.meta.json")

    assert got == expected


def test_daily_mark_store_write_read_roundtrip(tmp_path: Path) -> None:
    store = _store(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"
    df = _base_df()

    result = store.write(
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=df,
        source_content_sha256="upstream-sha-123",
    )

    assert result["wrote"] is True
    assert result["rows"] == 4
    assert result["calendar_id"] == calendar_id
    assert result["min_session_id"] == 0
    assert result["max_session_id"] == 3

    got = store.read(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    expected = coerce_daily_mark(df, ensure_column_order=True)

    pd.testing.assert_frame_equal(got, expected)


def test_daily_mark_store_read_meta_returns_written_meta(tmp_path: Path) -> None:
    store = _store(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    store.write(
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
        source_content_sha256="upstream-sha-123",
    )

    meta = store.read_meta(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    assert meta is not None
    assert meta["schema"] == "daily_mark"
    assert meta["schema_version"] == "1"
    assert meta["calendar_id"] == calendar_id
    assert meta["contract_id"] == contract_id
    assert meta["row_count"] == 4
    assert meta["min_session_id"] == 0
    assert meta["max_session_id"] == 3
    assert meta["source_content_sha256"] == "upstream-sha-123"


def test_daily_mark_store_scan_coverage_returns_missing_snapshot_when_absent(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    snap = store.scan_coverage(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    assert snap.exists is False
    assert snap.row_count == 0
    assert snap.min_session_id is None
    assert snap.max_session_id is None
    assert snap.meta_path is None
    assert snap.content_sha256 is None
    assert snap.artifact_sha256 is None
    assert snap.source_content_sha256 is None


def test_daily_mark_store_scan_coverage_uses_meta_when_present(tmp_path: Path) -> None:
    store = _store(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    store.write(
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
        source_content_sha256="upstream-sha-123",
    )

    snap = store.scan_coverage(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    assert snap.exists is True
    assert snap.row_count == 4
    assert snap.min_session_id == 0
    assert snap.max_session_id == 3
    assert snap.meta_path is not None
    assert snap.meta_path.exists()
    assert snap.content_sha256 is not None
    assert snap.artifact_sha256 is not None
    assert snap.source_content_sha256 == "upstream-sha-123"
    assert snap.mark_path.exists()


def test_daily_mark_store_scan_coverage_falls_back_when_meta_missing(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    store.write(
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
        source_content_sha256="upstream-sha-123",
    )

    meta_path = store.meta_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    assert meta_path.exists()

    meta_path.unlink()
    assert not meta_path.exists()

    snap = store.scan_coverage(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    assert snap.exists is True
    assert snap.row_count == 4
    assert snap.min_session_id == 0
    assert snap.max_session_id == 3
    assert snap.meta_path is None
    assert snap.content_sha256 is None
    assert snap.artifact_sha256 is None
    assert snap.source_content_sha256 is None
    assert snap.mark_path.exists()


def test_daily_mark_store_scan_coverage_falls_back_when_meta_corrupt(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    store.write(
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
        source_content_sha256="upstream-sha-123",
    )

    meta_path = store.meta_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    assert meta_path.exists()

    meta_path.write_text("{ not valid json", encoding="utf-8")

    snap = store.scan_coverage(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    assert snap.exists is True
    assert snap.row_count == 4
    assert snap.min_session_id == 0
    assert snap.max_session_id == 3
    assert snap.meta_path is not None
    assert snap.meta_path.exists()
    assert snap.content_sha256 is None
    assert snap.artifact_sha256 is None
    assert snap.source_content_sha256 is None
    assert snap.mark_path.exists()


def test_daily_mark_store_read_filters_by_session_id_interval(tmp_path: Path) -> None:
    store = _store(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    store.write(
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
    )

    got = store.read(
        calendar_id=calendar_id,
        contract_id=contract_id,
        start_session_id=1,
        end_session_id=3,
    )

    assert got["session_id"].tolist() == [1, 2]


def test_daily_mark_store_delete_removes_parquet_and_meta(tmp_path: Path) -> None:
    store = _store(tmp_path)

    calendar_id = "mxm_business_days_v1"
    contract_id = "CME.ESM2025"

    store.write(
        calendar_id=calendar_id,
        contract_id=contract_id,
        df_new=_base_df(),
    )

    mark_path = store.mark_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    meta_path = store.meta_path(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    assert mark_path.exists()
    assert meta_path.exists()

    existed = store.delete(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )

    assert existed is True
    assert not mark_path.exists()
    assert not meta_path.exists()


def test_daily_mark_store_delete_returns_false_when_absent(tmp_path: Path) -> None:
    store = _store(tmp_path)

    existed = store.delete(
        calendar_id="mxm_business_days_v1",
        contract_id="CME.ESM2025",
    )

    assert existed is False
