# tests/unittests/mxm/v1/marketdata/orchestrators/test_product_marketdata.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from mxm.v1.marketdata.orchestrators import product_marketdata as pm


@dataclass
class _FakeAttemptsStore:
    """
    Spy-only attempts store.

    We keep it minimal: capture start/finish calls and surface the last payload.
    """

    started: list[dict[str, Any]]
    finished: list[dict[str, Any]]

    def __init__(self) -> None:
        self.started = []
        self.finished = []

    def start_attempt(self, **kwargs: Any) -> str:
        self.started.append(dict(kwargs))
        return "attempt-uid-1"

    def finish_attempt(self, **kwargs: Any) -> None:
        self.finished.append(dict(kwargs))


def _stage(
    *,
    name: str,
    status: pm.StageStatus = pm.StageStatus.OK,
    stop_reason: str | None = None,
    cost_used_usd: float = 0.0,
    counts: dict[str, Any] | None = None,
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


def _stores(*, attempts: _FakeAttemptsStore) -> pm.ProductMarketDataStores:
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


def _patch_time(monkeypatch: pytest.MonkeyPatch) -> None:
    # Make reports deterministic.
    monkeypatch.setattr(pm, "utc_now_run_ts", lambda: "2020-01-01T00:00:00Z")


def test_product_marketdata_success_path_stage_order_and_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definitions",
        lambda **_: _stage(name="instrument_definitions", cost_used_usd=1.0),
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definition_mappings",
        lambda **_: _stage(
            name="instrument_definition_mappings",
            cost_used_usd=0.0,
            mapping_ready_for_ohlcv=True,
        ),
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_ohlcv_1d",
        lambda **_: _stage(name="ohlcv_1d", cost_used_usd=2.0),
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_statistics_1d",
        lambda **_: _stage(name="statistics_1d", cost_used_usd=3.0),
    )

    rep = pm.ingest_product_marketdata(
        product_id="p",
        mode="update",
        cost_cap_usd=10.0,
        stores=stores,
        client=object(),
        dry_run=False,
        reset=False,
        reset_local=False,
        max_windows=None,
        max_contracts=None,
        run_ts_utc="2020-01-01T00:00:00Z",
    )

    assert rep.status is pm.ProductStatus.SUCCESS
    assert [s.name for s in rep.stages] == [
        "instrument_definitions",
        "instrument_definition_mappings",
        "ohlcv_1d",
        "statistics_1d",
        "daily_stats",
    ]

    assert rep.cost_used_usd == pytest.approx(1.0 + 0.0 + 2.0 + 3.0 + 0)
    assert rep.remaining_usd == pytest.approx(10.0 - (1.0 + 0.0 + 2.0 + 3.0 + 0))

    # attempt ledger: start and finish written once
    assert len(attempts.started) == 1
    assert len(attempts.finished) == 1
    assert attempts.finished[0]["status"] == "success"


def test_product_marketdata_early_stop_after_stage3_remaining_includes_stage3_cost(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Regression test: remaining budget must be decremented by st3 cost
    before early return finalization.
    """
    _patch_time(monkeypatch)
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definitions",
        lambda **_: _stage(name="instrument_definitions", cost_used_usd=1.0),
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definition_mappings",
        lambda **_: _stage(
            name="instrument_definition_mappings",
            cost_used_usd=0.0,
            mapping_ready_for_ohlcv=True,
        ),
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_ohlcv_1d",
        lambda **_: _stage(
            name="ohlcv_1d",
            status=pm.StageStatus.HALTED,
            stop_reason="cost_cap",
            cost_used_usd=2.0,
        ),
    )

    # Stage 4 must not run if Stage 3 halts/errors.
    called_stage4 = {"called": False}

    def _stage4(**_: Any) -> pm.StageEnvelope:
        called_stage4["called"] = True
        return _stage(name="statistics_1d", cost_used_usd=999.0)

    monkeypatch.setattr(pm, "_run_stage_statistics_1d", _stage4)

    rep = pm.ingest_product_marketdata(
        product_id="p",
        mode="update",
        cost_cap_usd=10.0,
        stores=stores,
        client=object(),
        dry_run=False,
        reset=False,
        reset_local=False,
        run_ts_utc="2020-01-01T00:00:00Z",
    )

    assert called_stage4["called"] is False
    assert rep.status is pm.ProductStatus.HALTED
    assert [s.name for s in rep.stages] == [
        "instrument_definitions",
        "instrument_definition_mappings",
        "ohlcv_1d",
    ]

    # st1 + st2 + st3 costs must be included.
    assert rep.cost_used_usd == pytest.approx(1.0 + 0.0 + 2.0)
    assert rep.remaining_usd == pytest.approx(10.0 - (1.0 + 0.0 + 2.0))
    assert rep.stop_reason in (
        pm.ProductStopReason.COST_CAP,
        pm.ProductStopReason.ERROR,
    )


def test_product_marketdata_mappings_gate_blocks_downstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definitions",
        lambda **_: _stage(name="instrument_definitions", cost_used_usd=1.0),
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definition_mappings",
        lambda **_: _stage(
            name="instrument_definition_mappings",
            cost_used_usd=0.0,
            mapping_ready_for_ohlcv=False,
        ),
    )

    called = {"ohlcv": False, "stats": False}

    def _ohlcv(**_: Any) -> pm.StageEnvelope:
        called["ohlcv"] = True
        return _stage(name="ohlcv_1d", cost_used_usd=1.0)

    def _stats(**_: Any) -> pm.StageEnvelope:
        called["stats"] = True
        return _stage(name="statistics_1d", cost_used_usd=1.0)

    monkeypatch.setattr(pm, "_run_stage_ohlcv_1d", _ohlcv)
    monkeypatch.setattr(pm, "_run_stage_statistics_1d", _stats)

    rep = pm.ingest_product_marketdata(
        product_id="p",
        mode="update",
        cost_cap_usd=10.0,
        stores=stores,
        client=object(),
        dry_run=False,
        reset=False,
        reset_local=False,
        run_ts_utc="2020-01-01T00:00:00Z",
    )

    assert called["ohlcv"] is False
    assert called["stats"] is False
    assert rep.status is pm.ProductStatus.HALTED
    assert rep.stop_reason is pm.ProductStopReason.DOWNSTREAM_BLOCKED
    assert rep.message == "ohlcv_1d blocked: mappings not ready"
    assert [s.name for s in rep.stages] == [
        "instrument_definitions",
        "instrument_definition_mappings",
    ]


def test_product_marketdata_exception_finishes_attempt_and_reraises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definitions",
        lambda **_: _stage(name="instrument_definitions", cost_used_usd=1.0),
    )
    monkeypatch.setattr(
        pm,
        "_run_stage_instrument_definition_mappings",
        lambda **_: _stage(
            name="instrument_definition_mappings",
            cost_used_usd=0.0,
            mapping_ready_for_ohlcv=True,
        ),
    )

    def _boom(**_: Any) -> pm.StageEnvelope:
        raise RuntimeError("boom")

    monkeypatch.setattr(pm, "_run_stage_ohlcv_1d", _boom)

    with pytest.raises(RuntimeError, match="boom"):
        pm.ingest_product_marketdata(
            product_id="p",
            mode="update",
            cost_cap_usd=10.0,
            stores=stores,
            client=object(),
            dry_run=False,
            reset=False,
            reset_local=False,
            run_ts_utc="2020-01-01T00:00:00Z",
        )

    assert len(attempts.started) == 1
    assert len(attempts.finished) == 1
    fin = attempts.finished[0]
    assert fin["status"] == "error"
    assert fin["stop_reason"] == pm.ProductStopReason.ERROR.value
    assert fin["error_type"] == "RuntimeError"
    assert "boom" in (fin["error_message"] or "")


def test_product_marketdata_cost_cap_must_be_positive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_time(monkeypatch)
    attempts = _FakeAttemptsStore()
    stores = _stores(attempts=attempts)

    with pytest.raises(ValueError, match="cost_cap_usd must be > 0"):
        pm.ingest_product_marketdata(
            product_id="p",
            mode="update",
            cost_cap_usd=0.0,
            stores=stores,
            client=object(),
        )
