from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd
import pytest

from mxm.refdata.models.contracts.futures_contract import (
    FuturesContract,  # type: ignore
)
from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.marketdata.datasets.daily_mark.builder import DailyMarkBuildDiagnostics
from mxm.v1.marketdata.datasets.daily_mark.store import (
    DailyMarkStore,
    DailyMarkWriteResult,
    StoreCoverageSnapshot,
)
from mxm.v1.marketdata.orchestrators import daily_mark as dm


@dataclass(frozen=True)
class _FakeContract:
    contract_id: str
    product_id: str
    first_day_of_interest: date
    last_trading_day: date


@dataclass(frozen=True)
class _FakeCoverageSnapshot:
    mark_path: Path
    exists: bool
    row_count: int
    min_session_id: int | None
    max_session_id: int | None
    meta_path: Path | None = None
    content_sha256: str | None = None
    artifact_sha256: str | None = None
    source_content_sha256: str | None = None


@dataclass(frozen=True)
class _FakeBusinessCalendar:
    session_ids: np.ndarray
    labels: np.ndarray

    def label_from_session_id(self, session_id: int) -> np.datetime64:
        return self.labels[session_id]

    def session_id_from_label(self, label: object) -> int:
        for i, x in enumerate(self.labels):
            if x == label:
                return int(i)
        raise KeyError(label)


class _FakeDailyMarkStore:
    def __init__(
        self,
        *,
        coverage: _FakeCoverageSnapshot | None = None,
        meta: dict[str, object] | None = None,
        write_result: DailyMarkWriteResult | None = None,
    ) -> None:
        self._coverage = cast(
            StoreCoverageSnapshot,
            coverage
            or _FakeCoverageSnapshot(
                mark_path=Path("/tmp/daily_mark.parquet"),
                exists=False,
                row_count=0,
                min_session_id=None,
                max_session_id=None,
            ),
        )
        self._meta = meta
        self._write_result: DailyMarkWriteResult = write_result or {
            "wrote": True,
            "rows": 2,
            "min_session_id": 1,
            "max_session_id": 2,
            "content_sha256": "daily-mark-sha",
            "artifact_sha256": "artifact-sha",
            "meta_path": Path("/tmp/daily_mark.meta.json"),
            "path": Path("/tmp/daily_mark.parquet"),
            "calendar_id": "mxm_business_days_v1",
        }

        self.delete_calls: list[dict[str, object]] = []
        self.scan_calls: list[dict[str, object]] = []
        self.read_meta_calls: list[dict[str, object]] = []
        self.write_calls: list[dict[str, object]] = []
        self.mark_path_calls: list[dict[str, object]] = []

    def delete(self, *, calendar_id: str, contract_id: str) -> bool:
        self.delete_calls.append(
            {"calendar_id": calendar_id, "contract_id": contract_id}
        )
        return True

    def mark_path(self, *, calendar_id: str, contract_id: str) -> Path:
        self.mark_path_calls.append(
            {"calendar_id": calendar_id, "contract_id": contract_id}
        )
        return Path(f"/tmp/{calendar_id}/{contract_id}/daily_mark.parquet")

    def scan_coverage(
        self,
        *,
        calendar_id: str,
        contract_id: str,
    ) -> StoreCoverageSnapshot:
        self.scan_calls.append({"calendar_id": calendar_id, "contract_id": contract_id})
        return self._coverage

    def read_meta(
        self,
        *,
        calendar_id: str,
        contract_id: str,
    ) -> dict[str, object] | None:
        self.read_meta_calls.append(
            {"calendar_id": calendar_id, "contract_id": contract_id}
        )
        return self._meta

    def write(
        self,
        *,
        calendar_id: str,
        contract_id: str,
        df_new: pd.DataFrame,
        source_content_sha256: str | None,
        skip_if_unchanged: bool,
    ) -> DailyMarkWriteResult:
        self.write_calls.append(
            {
                "calendar_id": calendar_id,
                "contract_id": contract_id,
                "df_new": df_new,
                "source_content_sha256": source_content_sha256,
                "skip_if_unchanged": skip_if_unchanged,
            }
        )
        return self._write_result


@dataclass
class _CallFlags:
    daily_stats: bool = False
    daily_stats_meta: bool = False
    build: bool = False


@dataclass
class _BuildFlag:
    called: bool = False


def _fixed_run_ts() -> str:
    return "2020-01-01T00:00:00Z"


def _patch_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(dm, "utc_now_run_ts", _fixed_run_ts)


def _business_calendar() -> MXMBusinessCalendar:
    labels = np.array(
        [
            np.datetime64("2025-01-01", "D"),
            np.datetime64("2025-01-02", "D"),
            np.datetime64("2025-01-03", "D"),
            np.datetime64("2025-01-06", "D"),
        ],
        dtype="datetime64[D]",
    )
    session_ids = np.arange(labels.size, dtype=np.int32)
    return cast(
        MXMBusinessCalendar,
        _FakeBusinessCalendar(session_ids=session_ids, labels=labels),
    )


def _contract(
    *,
    contract_id: str = "CME.ESM2025",
    product_id: str = "CME.ES",
    first_day_of_interest: date = date(2025, 1, 2),
    last_trading_day: date = date(2025, 1, 3),
) -> FuturesContract:
    return cast(
        FuturesContract,
        _FakeContract(
            contract_id=contract_id,
            product_id=product_id,
            first_day_of_interest=first_day_of_interest,
            last_trading_day=last_trading_day,
        ),
    )


def _daily_stats_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "trading_date": pd.to_datetime(
                [
                    "2025-01-02T00:00:00Z",
                    "2025-01-03T00:00:00Z",
                ],
                utc=True,
            ),
            "contract_id": ["CME.ESM2025", "CME.ESM2025"],
            "product_id": ["CME.ES", "CME.ES"],
            "instrument_id": [4916, 4916],
            "publisher_id": [1, 1],
            "dataset": ["GLBX.MDP3", "GLBX.MDP3"],
            "raw_symbol": ["ESM5", "ESM5"],
            "settle_px": [100.0, 101.0],
        }
    )


def _built_daily_mark_df() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "session_id": [1, 2],
            "contract_id": ["CME.ESM2025", "CME.ESM2025"],
            "mark_px": [100.0, 101.0],
            "mark_source": ["observed_settle", "observed_settle"],
            "mark_quality": ["final", "final"],
            "is_markable": [True, True],
            "is_carried": [False, False],
            "carry_streak": [0, 0],
        }
    )


def _build_diagnostics(contract_id: str = "CME.ESM2025") -> DailyMarkBuildDiagnostics:
    return DailyMarkBuildDiagnostics(
        contract_id=contract_id,
        sessions_total=2,
        observed_settle_n=2,
        observed_close_n=0,
        carry_forward_n=0,
        unavailable_n=0,
        max_carry_streak=0,
    )


def _store_pair(
    *,
    coverage: _FakeCoverageSnapshot | None = None,
    meta: dict[str, object] | None = None,
) -> tuple[_FakeDailyMarkStore, DailyMarkStore]:
    fake_store = _FakeDailyMarkStore(coverage=coverage, meta=meta)
    return fake_store, cast(DailyMarkStore, fake_store)


def _enumerate_one_contract(
    product_id: str,
    *,
    mode: dm.Mode,
) -> list[FuturesContract]:
    _ = product_id, mode
    return [_contract()]


def _enumerate_old_contract(
    product_id: str,
    *,
    mode: dm.Mode,
) -> list[FuturesContract]:
    _ = product_id, mode
    return [
        _contract(
            contract_id="CME.ESZ2000",
            first_day_of_interest=date(1995, 10, 2),
            last_trading_day=date(2000, 12, 15),
        )
    ]


def _enumerate_two_contracts(
    product_id: str,
    *,
    mode: dm.Mode,
) -> list[FuturesContract]:
    _ = product_id, mode
    return [
        _contract(contract_id="CME.ESM2025"),
        _contract(contract_id="CME.ESU2025"),
    ]


def _read_default_daily_stats_contract(
    *,
    contract_id: str,
    root: Path | None,
) -> pd.DataFrame:
    _ = contract_id, root
    return _daily_stats_df()


def _read_empty_daily_stats_contract(
    *,
    contract_id: str,
    root: Path | None,
) -> pd.DataFrame:
    _ = contract_id, root
    return pd.DataFrame()


def _read_default_daily_stats_contract_meta(
    *,
    contract_id: str,
    root: Path | None,
) -> dict[str, object]:
    _ = contract_id, root
    return {
        "content_sha256": "upstream-sha",
        "path": "/tmp/daily_stats.parquet",
    }


def _read_no_daily_stats_contract_meta(
    *,
    contract_id: str,
    root: Path | None,
) -> dict[str, object] | None:
    _ = contract_id, root
    return None


def _build_default_daily_mark(
    *,
    contract_id: str,
    session_ids: np.ndarray,
    business_calendar: MXMBusinessCalendar,
    daily_stats: pd.DataFrame,
) -> tuple[pd.DataFrame, DailyMarkBuildDiagnostics]:
    _ = session_ids, business_calendar, daily_stats
    return _built_daily_mark_df(), _build_diagnostics(contract_id)


def test_contract_session_ids_derives_inclusive_business_range() -> None:
    cal = _business_calendar()
    c = _contract(
        first_day_of_interest=date(2025, 1, 2),
        last_trading_day=date(2025, 1, 3),
    )

    session_range = dm._contract_session_ids(
        contract=c,
        business_calendar=cal,
    )

    assert session_range is not None
    start_sid, end_sid, session_ids = session_range

    assert start_sid == 1
    assert end_sid == 2
    assert session_ids.tolist() == [1, 2]


def test_contract_session_ids_clips_to_business_calendar_overlap() -> None:
    cal = _business_calendar()
    c = _contract(
        first_day_of_interest=date(2024, 12, 15),
        last_trading_day=date(2025, 1, 2),
    )

    session_range = dm._contract_session_ids(
        contract=c,
        business_calendar=cal,
    )

    assert session_range is not None
    start_sid, end_sid, session_ids = session_range

    assert start_sid == 0
    assert end_sid == 1
    assert session_ids.tolist() == [0, 1]


def test_contract_session_ids_returns_none_when_no_calendar_overlap() -> None:
    cal = _business_calendar()
    c = _contract(
        first_day_of_interest=date(1995, 10, 1),
        last_trading_day=date(2000, 12, 31),
    )

    session_range = dm._contract_session_ids(
        contract=c,
        business_calendar=cal,
    )

    assert session_range is None


def test_derive_daily_mark_for_product_skips_no_upstream_when_daily_stats_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    fake_store, store = _store_pair()

    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_one_contract)
    monkeypatch.setattr(
        dm, "read_daily_stats_contract", _read_empty_daily_stats_contract
    )
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_no_daily_stats_contract_meta,
    )

    build_flag = _BuildFlag()

    def _build(
        *,
        contract_id: str,
        session_ids: np.ndarray,
        business_calendar: MXMBusinessCalendar,
        daily_stats: pd.DataFrame,
    ) -> tuple[pd.DataFrame, DailyMarkBuildDiagnostics]:
        _ = contract_id, session_ids, business_calendar, daily_stats
        build_flag.called = True
        return _built_daily_mark_df(), _build_diagnostics()

    monkeypatch.setattr(dm, "build_daily_mark", _build)

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
    )

    assert rep.ts_utc == "2020-01-01T00:00:00Z"
    assert rep.contracts_total == 1
    assert rep.skipped_no_upstream == 1
    assert rep.built == 0
    assert rep.errors == 0
    assert len(rep.runs) == 1
    assert rep.runs[0].status == "skipped_no_upstream"
    assert rep.runs[0].requested_min_session_id == 1
    assert rep.runs[0].requested_max_session_id == 2
    assert build_flag.called is False
    assert len(fake_store.write_calls) == 0


def test_derive_daily_mark_for_product_skips_out_of_calendar_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    fake_store, store = _store_pair()

    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_old_contract)

    read_called = _CallFlags()

    def _read_daily_stats_contract(
        *,
        contract_id: str,
        root: Path | None,
    ) -> pd.DataFrame:
        _ = contract_id, root
        read_called.daily_stats = True
        return _daily_stats_df()

    def _read_daily_stats_contract_meta(
        *,
        contract_id: str,
        root: Path | None,
    ) -> dict[str, object] | None:
        _ = contract_id, root
        read_called.daily_stats_meta = True
        return {
            "content_sha256": "upstream-sha",
            "path": "/tmp/daily_stats.parquet",
        }

    def _build(
        *,
        contract_id: str,
        session_ids: np.ndarray,
        business_calendar: MXMBusinessCalendar,
        daily_stats: pd.DataFrame,
    ) -> tuple[pd.DataFrame, DailyMarkBuildDiagnostics]:
        _ = contract_id, session_ids, business_calendar, daily_stats
        read_called.build = True
        return _built_daily_mark_df(), _build_diagnostics("CME.ESZ2000")

    monkeypatch.setattr(dm, "read_daily_stats_contract", _read_daily_stats_contract)
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_daily_stats_contract_meta,
    )
    monkeypatch.setattr(dm, "build_daily_mark", _build)

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
    )

    assert rep.contracts_total == 1
    assert rep.skipped_out_of_calendar_range == 1
    assert rep.built == 0
    assert rep.skipped_no_upstream == 0
    assert rep.errors == 0
    assert len(rep.runs) == 1

    run = rep.runs[0]
    assert run.status == "skipped_out_of_calendar_range"
    assert run.requested_min_session_id is None
    assert run.requested_max_session_id is None

    assert read_called.daily_stats is False
    assert read_called.daily_stats_meta is False
    assert read_called.build is False
    assert len(fake_store.write_calls) == 0


def test_derive_daily_mark_for_product_builds_and_writes_on_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    fake_store, store = _store_pair()

    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_one_contract)
    monkeypatch.setattr(
        dm, "read_daily_stats_contract", _read_default_daily_stats_contract
    )
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_default_daily_stats_contract_meta,
    )
    monkeypatch.setattr(dm, "build_daily_mark", _build_default_daily_mark)

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
    )

    assert rep.contracts_total == 1
    assert rep.built == 1
    assert rep.skipped_unchanged == 0
    assert rep.skipped_no_upstream == 0
    assert rep.skipped_out_of_calendar_range == 0
    assert rep.errors == 0
    assert len(rep.runs) == 1

    run = rep.runs[0]
    assert run.status == "built"
    assert run.requested_min_session_id == 1
    assert run.requested_max_session_id == 2
    assert run.upstream_exists is True
    assert run.upstream_rows == 2
    assert run.upstream_content_sha256 == "upstream-sha"
    assert run.daily_stats_path == "/tmp/daily_stats.parquet"
    assert run.downstream_rows == 2
    assert run.downstream_min_session_id == 1
    assert run.downstream_max_session_id == 2
    assert run.downstream_content_sha256 == "daily-mark-sha"
    assert run.downstream_source_content_sha256 == "upstream-sha"
    assert run.observed_settle_n == 2
    assert run.observed_close_n == 0
    assert run.carry_forward_n == 0
    assert run.unavailable_n == 0
    assert run.max_carry_streak == 0

    assert len(fake_store.write_calls) == 1
    assert fake_store.write_calls[0]["calendar_id"] == "mxm_business_days_v1"
    assert fake_store.write_calls[0]["contract_id"] == "CME.ESM2025"
    assert fake_store.write_calls[0]["source_content_sha256"] == "upstream-sha"


def test_derive_daily_mark_for_product_skips_unchanged_when_source_hash_calendar_and_exact_range_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    fake_store, store = _store_pair(
        coverage=_FakeCoverageSnapshot(
            mark_path=Path("/tmp/daily_mark.parquet"),
            exists=True,
            row_count=2,
            min_session_id=1,
            max_session_id=2,
            content_sha256="daily-mark-sha",
            artifact_sha256="artifact-sha",
            source_content_sha256="upstream-sha",
        ),
        meta={"calendar_id": "mxm_business_days_v1"},
    )

    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_one_contract)
    monkeypatch.setattr(
        dm, "read_daily_stats_contract", _read_default_daily_stats_contract
    )
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_default_daily_stats_contract_meta,
    )

    build_flag = _BuildFlag()

    def _build(
        *,
        contract_id: str,
        session_ids: np.ndarray,
        business_calendar: MXMBusinessCalendar,
        daily_stats: pd.DataFrame,
    ) -> tuple[pd.DataFrame, DailyMarkBuildDiagnostics]:
        _ = contract_id, session_ids, business_calendar, daily_stats
        build_flag.called = True
        return _built_daily_mark_df(), _build_diagnostics()

    monkeypatch.setattr(dm, "build_daily_mark", _build)

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
    )

    assert rep.skipped_unchanged == 1
    assert rep.built == 0
    assert rep.errors == 0
    assert len(rep.runs) == 1
    assert rep.runs[0].status == "skipped_unchanged"
    assert build_flag.called is False
    assert len(fake_store.write_calls) == 0


def test_derive_daily_mark_for_product_honours_dry_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    fake_store, store = _store_pair()

    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_one_contract)
    monkeypatch.setattr(
        dm, "read_daily_stats_contract", _read_default_daily_stats_contract
    )
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_default_daily_stats_contract_meta,
    )

    build_flag = _BuildFlag()

    def _build(
        *,
        contract_id: str,
        session_ids: np.ndarray,
        business_calendar: MXMBusinessCalendar,
        daily_stats: pd.DataFrame,
    ) -> tuple[pd.DataFrame, DailyMarkBuildDiagnostics]:
        _ = contract_id, session_ids, business_calendar, daily_stats
        build_flag.called = True
        return _built_daily_mark_df(), _build_diagnostics()

    monkeypatch.setattr(dm, "build_daily_mark", _build)

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
        dry_run=True,
    )

    assert rep.dry_run_n == 1
    assert rep.built == 0
    assert rep.errors == 0
    assert rep.runs[0].status == "dry_run"
    assert build_flag.called is False
    assert len(fake_store.write_calls) == 0


def test_derive_daily_mark_for_product_honours_force_reset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    fake_store, store = _store_pair()

    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_one_contract)
    monkeypatch.setattr(
        dm, "read_daily_stats_contract", _read_default_daily_stats_contract
    )
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_default_daily_stats_contract_meta,
    )
    monkeypatch.setattr(dm, "build_daily_mark", _build_default_daily_mark)

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
        force_reset=True,
    )

    assert rep.built == 1
    assert len(fake_store.delete_calls) == 1
    assert fake_store.delete_calls[0] == {
        "calendar_id": "mxm_business_days_v1",
        "contract_id": "CME.ESM2025",
    }


def test_derive_daily_mark_for_product_filters_contract_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    _, store = _store_pair()

    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_two_contracts)
    monkeypatch.setattr(
        dm, "read_daily_stats_contract", _read_empty_daily_stats_contract
    )
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_no_daily_stats_contract_meta,
    )

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
        contract_ids={"CME.ESU2025"},
    )

    assert rep.contracts_total == 1
    assert len(rep.runs) == 1
    assert rep.runs[0].contract_id == "CME.ESU2025"


def test_derive_daily_mark_for_product_limits_max_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    _, store = _store_pair()

    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_two_contracts)
    monkeypatch.setattr(
        dm, "read_daily_stats_contract", _read_empty_daily_stats_contract
    )
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_no_daily_stats_contract_meta,
    )

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
        max_contracts=1,
    )

    assert rep.contracts_total == 1
    assert len(rep.runs) == 1


def test_derive_daily_mark_for_product_records_error_when_builder_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    _, store = _store_pair()

    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_one_contract)
    monkeypatch.setattr(
        dm, "read_daily_stats_contract", _read_default_daily_stats_contract
    )
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_default_daily_stats_contract_meta,
    )

    def _boom(
        *,
        contract_id: str,
        session_ids: np.ndarray,
        business_calendar: MXMBusinessCalendar,
        daily_stats: pd.DataFrame,
    ) -> tuple[pd.DataFrame, DailyMarkBuildDiagnostics]:
        _ = contract_id, session_ids, business_calendar, daily_stats
        raise RuntimeError("boom")

    monkeypatch.setattr(dm, "build_daily_mark", _boom)

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
    )

    assert rep.errors == 1
    assert rep.built == 0
    assert len(rep.runs) == 1
    assert rep.runs[0].status == "error"
    assert rep.runs[0].status_detail is not None
    assert "RuntimeError" in rep.runs[0].status_detail


def test_derive_daily_mark_for_product_records_unmapped_when_daily_stats_mapping_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    cal = _business_calendar()
    fake_store, store = _store_pair()

    class _FakeInstrumentNotMappedError(Exception):
        pass

    monkeypatch.setattr(dm, "InstrumentNotMappedError", _FakeInstrumentNotMappedError)
    monkeypatch.setattr(dm, "_enumerate_contracts", _enumerate_one_contract)

    def _raise_unmapped(
        *,
        contract_id: str,
        root: Path | None,
    ) -> pd.DataFrame:
        _ = contract_id, root
        raise _FakeInstrumentNotMappedError(
            "No Databento instrument mapping found for "
            "(product_id=CME.ES, period_id=Mar-2025, contract=2025-03)."
        )

    monkeypatch.setattr(dm, "read_daily_stats_contract", _raise_unmapped)
    monkeypatch.setattr(
        dm,
        "read_daily_stats_contract_meta",
        _read_no_daily_stats_contract_meta,
    )

    build_flag = _BuildFlag()

    def _build(
        *,
        contract_id: str,
        session_ids: np.ndarray,
        business_calendar: MXMBusinessCalendar,
        daily_stats: pd.DataFrame,
    ) -> tuple[pd.DataFrame, DailyMarkBuildDiagnostics]:
        _ = contract_id, session_ids, business_calendar, daily_stats
        build_flag.called = True
        return _built_daily_mark_df(), _build_diagnostics()

    monkeypatch.setattr(dm, "build_daily_mark", _build)

    rep = dm.derive_daily_mark_for_product(
        product_id="CME.ES",
        calendar_id="mxm_business_days_v1_2025-01-01_2025-01-06",
        business_calendar=cal,
        daily_mark_store=store,
        root=None,
        mode="bootstrap",
    )

    assert rep.contracts_total == 1
    assert rep.unmapped == 1
    assert rep.built == 0
    assert rep.skipped_no_upstream == 0
    assert rep.skipped_out_of_calendar_range == 0
    assert rep.errors == 0
    assert len(rep.runs) == 1

    run = rep.runs[0]
    assert run.status == "unmapped"
    assert run.requested_min_session_id == 1
    assert run.requested_max_session_id == 2
    assert run.upstream_exists is False
    assert run.upstream_rows == 0
    assert run.daily_stats_path is None
    assert run.daily_mark_path is None
    assert run.status_detail is not None
    assert "_FakeInstrumentNotMappedError" in run.status_detail

    assert build_flag.called is False
    assert len(fake_store.write_calls) == 0
