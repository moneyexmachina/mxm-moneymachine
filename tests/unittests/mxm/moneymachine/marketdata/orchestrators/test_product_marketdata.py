from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pytest

from mxm.moneymachine.marketdata.orchestrators import product_marketdata as pm
from mxm.refdata import RefDataReader

type AttemptValue = str | int | float | bool | None | pm.ProductStopReason
type AttemptPayload = dict[str, AttemptValue]
type StageCountValue = str | int | float | bool | None
type StageCounts = dict[str, StageCountValue]


class _FakeRefDataReader:
    """
    Narrow test double for the product-level refdata capability.

    These tests patch all stage runners, so no refdata methods are exercised.
    The fake exists only to satisfy and verify the explicit composition shape.
    """


@dataclass
class _FakeAttemptsStore:
    started: list[AttemptPayload]
    finished: list[AttemptPayload]

    def __init__(self) -> None:
        self.started = []
        self.finished = []

    def start_attempt(self, **kwargs: AttemptValue) -> str:
        self.started.append(dict(kwargs))
        return "attempt-uid-1"

    def finish_attempt(self, **kwargs: AttemptValue) -> None:
        self.finished.append(dict(kwargs))


def _refdata_reader() -> RefDataReader:
    return cast(
        RefDataReader,
        _FakeRefDataReader(),
    )


def _stage(
    *,
    name: str,
    status: pm.StageStatus = pm.StageStatus.OK,
    stop_reason: str | None = None,
    cost_used_usd: float = 0.0,
    counts: StageCounts | None = None,
    mapping_ready_for_ohlcv: bool | None = None,
) -> pm.StageEnvelope:
    return pm.StageEnvelope(
        name=name,
        status=status,
        stop_reason=stop_reason,
        cost_used_usd=float(cost_used_usd),
        counts=counts or {},
        raw_report={"name": name},
        mapping_ready_for_ohlcv=mapping_ready_for_ohlcv,
    )


def _stores(
    *,
    attempts: _FakeAttemptsStore,
) -> pm.ProductMarketDataStores:
    """
    Construct a ProductMarketDataStores bundle with dummy dataset stores.

    These are not used because tests patch the stage runners.
    """
    return pm.ProductMarketDataStores(
        backend=None,  # type: ignore[arg-type]
        product_attempts=attempts,  # type: ignore[arg-type]
        instrument_definitions_store=object(),  # type: ignore[arg-type]
        instrument_definition_mappings_store=object(),  # type: ignore[arg-type]
        ohlcv_1d_store=object(),  # type: ignore[arg-type]
        statistics_1d_store=object(),  # type: ignore[arg-type]
        daily_stats_store=object(),  # type: ignore[arg-type]
    )


def _fixed_run_ts() -> str:
    return "2020-01-01T00:00:00Z"


def _patch_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        pm,
        "utc_now_run_ts",
        _fixed_run_ts,
    )


def _stage_instrument_definitions_ok(
    **kwargs: object,
) -> pm.StageEnvelope:
    _ = kwargs
    return _stage(
        name="instrument_definitions",
        cost_used_usd=1.0,
    )


def _stage_mappings_ready(
    **kwargs: object,
) -> pm.StageEnvelope:
    _ = kwargs
    return _stage(
        name="instrument_definition_mappings",
        cost_used_usd=0.0,
        mapping_ready_for_ohlcv=True,
    )


def _stage_mappings_not_ready(
    **kwargs: object,
) -> pm.StageEnvelope:
    _ = kwargs
    return _stage(
        name="instrument_definition_mappings",
        cost_used_usd=0.0,
        mapping_ready_for_ohlcv=False,
    )


def _stage_ohlcv_ok(
    **kwargs: object,
) -> pm.StageEnvelope:
    _ = kwargs
    return _stage(
        name="ohlcv_1d",
        cost_used_usd=2.0,
    )


def _stage_ohlcv_halted_cost_cap(
    **kwargs: object,
) -> pm.StageEnvelope:
    _ = kwargs
    return _stage(
        name="ohlcv_1d",
        status=pm.StageStatus.HALTED,
        stop_reason="cost_cap",
        cost_used_usd=2.0,
    )


def _stage_statistics_ok(
    **kwargs: object,
) -> pm.StageEnvelope:
    _ = kwargs
    return _stage(
        name="statistics_1d",
        cost_used_usd=3.0,
    )


def _stage_daily_stats_ok(
    **kwargs: object,
) -> pm.StageEnvelope:
    _ = kwargs
    return _stage(
        name="daily_stats",
        cost_used_usd=0.0,
    )


def test_product_marketdata_success_path_stage_order_and_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)

    refdata_reader = _refdata_reader()
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definitions",
        _stage_instrument_definitions_ok,
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definition_mappings",
        _stage_mappings_ready,
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_ohlcv_1d",
        _stage_ohlcv_ok,
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_statistics_1d",
        _stage_statistics_ok,
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_daily_stats",
        _stage_daily_stats_ok,
    )
    rep = pm.ingest_product_marketdata(
        refdata_reader=refdata_reader,
        product_id="p",
        mode="update",
        cost_cap_usd=10.0,
        stores=stores,
        client=object(),
        dry_run=False,
        reset=False,
        force_reset=False,
        max_windows=None,
        max_contracts=None,
        run_ts_utc="2020-01-01T00:00:00Z",
    )

    assert rep.status is pm.ProductStatus.SUCCESS
    assert [stage.name for stage in rep.stages] == [
        "instrument_definitions",
        "instrument_definition_mappings",
        "ohlcv_1d",
        "statistics_1d",
        "daily_stats",
    ]

    assert rep.cost_used_usd == 6.0
    assert rep.remaining_usd == 4.0

    assert len(attempts.started) == 1
    assert len(attempts.finished) == 1
    assert attempts.finished[0]["status"] == "success"


def test_product_marketdata_early_stop_after_stage3_remaining_includes_stage3_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Regression test: remaining budget must be decremented by stage 3 cost
    before early return finalization.
    """
    _patch_time(monkeypatch)

    refdata_reader = _refdata_reader()
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definitions",
        _stage_instrument_definitions_ok,
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definition_mappings",
        _stage_mappings_ready,
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_ohlcv_1d",
        _stage_ohlcv_halted_cost_cap,
    )

    called_stage4 = {"called": False}

    def _stage4(
        **_: object,
    ) -> pm.StageEnvelope:
        called_stage4["called"] = True
        return _stage(
            name="statistics_1d",
            cost_used_usd=999.0,
        )

    monkeypatch.setattr(
        pm,
        "_run_stage_statistics_1d",
        _stage4,
    )

    rep = pm.ingest_product_marketdata(
        refdata_reader=refdata_reader,
        product_id="p",
        mode="update",
        cost_cap_usd=10.0,
        stores=stores,
        client=object(),
        dry_run=False,
        reset=False,
        force_reset=False,
        run_ts_utc="2020-01-01T00:00:00Z",
    )

    assert called_stage4["called"] is False
    assert rep.status is pm.ProductStatus.HALTED
    assert [stage.name for stage in rep.stages] == [
        "instrument_definitions",
        "instrument_definition_mappings",
        "ohlcv_1d",
    ]

    assert rep.cost_used_usd == 3.0
    assert rep.remaining_usd == 7.0
    assert rep.stop_reason in (
        pm.ProductStopReason.COST_CAP,
        pm.ProductStopReason.ERROR,
    )


def test_product_marketdata_mappings_gate_blocks_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)

    refdata_reader = _refdata_reader()
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definitions",
        _stage_instrument_definitions_ok,
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definition_mappings",
        _stage_mappings_not_ready,
    )

    called = {
        "ohlcv": False,
        "stats": False,
    }

    def _ohlcv(
        **_: object,
    ) -> pm.StageEnvelope:
        called["ohlcv"] = True
        return _stage(
            name="ohlcv_1d",
            cost_used_usd=1.0,
        )

    def _stats(
        **_: object,
    ) -> pm.StageEnvelope:
        called["stats"] = True
        return _stage(
            name="statistics_1d",
            cost_used_usd=1.0,
        )

    monkeypatch.setattr(
        pm,
        "_run_stage_ohlcv_1d",
        _ohlcv,
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_statistics_1d",
        _stats,
    )

    rep = pm.ingest_product_marketdata(
        refdata_reader=refdata_reader,
        product_id="p",
        mode="update",
        cost_cap_usd=10.0,
        stores=stores,
        client=object(),
        dry_run=False,
        reset=False,
        force_reset=False,
        run_ts_utc="2020-01-01T00:00:00Z",
    )

    assert called["ohlcv"] is False
    assert called["stats"] is False

    assert rep.status is pm.ProductStatus.HALTED
    assert rep.stop_reason is pm.ProductStopReason.DOWNSTREAM_BLOCKED
    assert rep.message == "ohlcv_1d blocked: mappings not ready"

    assert [stage.name for stage in rep.stages] == [
        "instrument_definitions",
        "instrument_definition_mappings",
    ]


def test_product_marketdata_exception_finishes_attempt_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)

    refdata_reader = _refdata_reader()
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definitions",
        _stage_instrument_definitions_ok,
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definition_mappings",
        _stage_mappings_ready,
    )

    def _boom(
        **_: object,
    ) -> pm.StageEnvelope:
        raise RuntimeError("boom")

    monkeypatch.setattr(
        pm,
        "_run_stage_ohlcv_1d",
        _boom,
    )

    with pytest.raises(
        RuntimeError,
        match="boom",
    ):
        pm.ingest_product_marketdata(
            refdata_reader=refdata_reader,
            product_id="p",
            mode="update",
            cost_cap_usd=10.0,
            stores=stores,
            client=object(),
            dry_run=False,
            reset=False,
            force_reset=False,
            run_ts_utc="2020-01-01T00:00:00Z",
        )

    assert len(attempts.started) == 1
    assert len(attempts.finished) == 1

    finished = attempts.finished[0]

    assert finished["status"] == "error"
    assert finished["stop_reason"] == pm.ProductStopReason.ERROR.value
    assert finished["error_type"] == "RuntimeError"

    error_message = finished["error_message"]
    assert isinstance(error_message, str)
    assert "boom" in error_message


def test_product_marketdata_cost_cap_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)

    refdata_reader = _refdata_reader()
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    with pytest.raises(
        ValueError,
        match="cost_cap_usd must be > 0",
    ):
        pm.ingest_product_marketdata(
            refdata_reader=refdata_reader,
            product_id="p",
            mode="update",
            cost_cap_usd=0.0,
            stores=stores,
            client=object(),
        )
