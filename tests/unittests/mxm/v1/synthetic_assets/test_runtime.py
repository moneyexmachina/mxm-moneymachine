from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import cast

import numpy as np
import pandas as pd
import pytest

import mxm.v1.synthetic_assets.runtime as rtmod
from mxm.refdata.api.ref_data_api import RefDataAPI  # type: ignore
from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.synthetic_assets.component_contracts import ComponentContracts
from mxm.v1.synthetic_assets.component_weights import ComponentWeights
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.runtime import SyntheticAsset
from mxm.v1.synthetic_assets.target_holdings import TargetHoldings
from mxm.v1.synthetic_assets.unit_conversion import UnitConverter


def _days(*xs: str) -> np.ndarray:
    return np.array(xs, dtype="datetime64[D]")


def _unused_engine() -> ContractSelectorEngine:
    return cast(ContractSelectorEngine, object())


def _unused_calendar_service() -> TradingCalendarService:
    return cast(TradingCalendarService, object())


def _unused_refdata_api() -> RefDataAPI:
    return cast(RefDataAPI, object())


def _unused_unit_converter() -> UnitConverter:
    return cast(UnitConverter, object())


def _make_spec() -> SyntheticAssetSpec:
    components = {
        "cur": SimpleNamespace(product_id="CL", selector_rule_id="REL::MONTH::N=1"),
        "nxt": SimpleNamespace(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
    }
    return cast(
        SyntheticAssetSpec,
        SimpleNamespace(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            weights_rule_id="WR::KIND=LINEAR_ROLL::ROLL_START_OFFSET=N1::ROLL_DURATION=3",
            components=components,
            unit="bbl",
            size=1.0,
        ),
    )


def _make_mxm_business_calendar() -> MXMBusinessCalendar:
    labels = _days("2026-03-18", "2026-03-19", "2026-03-20")
    start_ts = labels.astype("datetime64[ns]")
    end_ts = (start_ts + np.timedelta64(1, "D")).astype("datetime64[ns]")

    return MXMBusinessCalendar(
        calendar_id="mxm_v1_business",
        session_ids=np.arange(labels.size, dtype=np.int64),
        labels=labels,
        start_ts=start_ts,
        end_ts=end_ts,
    )


def _make_component_contracts(
    *,
    asset_id: str = "cl_cont",
    canonical_id: str = "SYNTH::TEST",
    columns: tuple[str, ...] = ("cur", "nxt"),
    sessions: tuple[str, ...] = ("2026-03-18", "2026-03-19", "2026-03-20"),
) -> ComponentContracts:
    data = {
        columns[0]: ["CLJ2026", "CLJ2026", "CLK2026"],
        columns[1]: ["CLK2026", "CLK2026", "CLM2026"],
    }
    frame = pd.DataFrame(
        data,
        index=pd.Index(_days(*sessions), name="session"),
    )
    return ComponentContracts(
        asset_id=asset_id,
        canonical_id=canonical_id,
        frame=frame,
    )


def _make_component_weights(
    *,
    asset_id: str = "cl_cont",
    canonical_id: str = "SYNTH::TEST",
    weights_rule_id: str = "WR::KIND=LINEAR_ROLL::ROLL_START_OFFSET=N1::ROLL_DURATION=3",
    columns: tuple[str, ...] = ("cur", "nxt"),
    sessions: tuple[str, ...] = ("2026-03-18", "2026-03-19", "2026-03-20"),
) -> ComponentWeights:
    data = {
        columns[0]: [1.0, 0.5, 0.0],
        columns[1]: [0.0, 0.5, 1.0],
    }
    frame = pd.DataFrame(
        data,
        index=pd.Index(_days(*sessions), name="session"),
    )
    return ComponentWeights(
        asset_id=asset_id,
        canonical_id=canonical_id,
        weights_rule_id=weights_rule_id,
        frame=frame,
    )


def _make_target_holdings(
    *,
    asset_id: str = "cl_cont",
    canonical_id: str = "SYNTH::TEST",
) -> TargetHoldings:
    idx = pd.MultiIndex.from_tuples(
        [
            (np.datetime64("2026-03-18", "D"), "CLJ2026"),
            (np.datetime64("2026-03-18", "D"), "CLK2026"),
            (np.datetime64("2026-03-19", "D"), "CLJ2026"),
            (np.datetime64("2026-03-19", "D"), "CLK2026"),
            (np.datetime64("2026-03-20", "D"), "CLK2026"),
            (np.datetime64("2026-03-20", "D"), "CLM2026"),
        ],
        names=["session", "contract_id"],
    )
    frame = pd.DataFrame(
        {"target_holding": [1.0, 0.0, 0.5, 0.5, 0.0, 1.0]},
        index=idx,
    )
    return TargetHoldings(
        asset_id=asset_id,
        canonical_id=canonical_id,
        frame=frame,
    )


@dataclass
class _BuildCapture:
    contracts_kwargs: dict[str, object] | None = None
    weights_kwargs: dict[str, object] | None = None
    holdings_kwargs: dict[str, object] | None = None


_build_capture = _BuildCapture()
_build_component_contracts_result: ComponentContracts | None = None
_build_component_weights_result: ComponentWeights | None = None
_build_target_holdings_result: TargetHoldings | None = None


def _reset_build_fakes(
    *,
    component_contracts: ComponentContracts,
    component_weights: ComponentWeights,
    target_holdings: TargetHoldings,
) -> None:
    global _build_component_contracts_result
    global _build_component_weights_result
    global _build_target_holdings_result

    _build_capture.contracts_kwargs = None
    _build_capture.weights_kwargs = None
    _build_capture.holdings_kwargs = None

    _build_component_contracts_result = component_contracts
    _build_component_weights_result = component_weights
    _build_target_holdings_result = target_holdings


def _fake_build_component_contracts(
    *,
    spec: SyntheticAssetSpec,
    start_session: np.datetime64,
    end_session: np.datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    mxm_business_calendar: MXMBusinessCalendar,
) -> ComponentContracts:
    _build_capture.contracts_kwargs = {
        "spec": spec,
        "start_session": start_session,
        "end_session": end_session,
        "engine": engine,
        "calendar_service": calendar_service,
        "mxm_business_calendar": mxm_business_calendar,
    }

    if _build_component_contracts_result is None:
        raise RuntimeError("_build_component_contracts_result not initialized")

    return _build_component_contracts_result


def _fake_build_component_weights(
    *,
    spec: SyntheticAssetSpec,
    component_contracts: ComponentContracts,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
    mxm_business_calendar: MXMBusinessCalendar,
    refdata_api: RefDataAPI,
) -> ComponentWeights:
    _build_capture.weights_kwargs = {
        "spec": spec,
        "component_contracts": component_contracts,
        "engine": engine,
        "calendar_service": calendar_service,
        "mxm_business_calendar": mxm_business_calendar,
        "refdata_api": refdata_api,
    }

    if _build_component_weights_result is None:
        raise RuntimeError("_build_component_weights_result not initialized")

    return _build_component_weights_result


def _fake_build_target_holdings(
    *,
    spec: SyntheticAssetSpec,
    component_contracts: ComponentContracts,
    component_weights: ComponentWeights,
    unit_converter: UnitConverter,
) -> TargetHoldings:
    _build_capture.holdings_kwargs = {
        "spec": spec,
        "component_contracts": component_contracts,
        "component_weights": component_weights,
        "unit_converter": unit_converter,
    }

    if _build_target_holdings_result is None:
        raise RuntimeError("_build_target_holdings_result not initialized")

    return _build_target_holdings_result


def _patch_builders(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        rtmod,
        "build_component_contracts",
        _fake_build_component_contracts,
    )
    monkeypatch.setattr(
        rtmod,
        "build_component_weights",
        _fake_build_component_weights,
    )
    monkeypatch.setattr(
        rtmod,
        "build_target_holdings",
        _fake_build_target_holdings,
    )


# -----------------------------------------------------------------------------
# SyntheticAsset validation
# -----------------------------------------------------------------------------


def test_synthetic_asset_accepts_aligned_inputs() -> None:
    spec = _make_spec()
    contracts = _make_component_contracts()
    weights = _make_component_weights()
    holdings = _make_target_holdings()

    out = SyntheticAsset(
        spec=spec,
        component_contracts=contracts,
        component_weights=weights,
        target_holdings=holdings,
    )

    assert out.spec is spec
    assert out.component_contracts is contracts
    assert out.component_weights is weights
    assert out.target_holdings is holdings
    assert out.first_session() == np.datetime64("2026-03-18", "D")
    assert out.last_session() == np.datetime64("2026-03-20", "D")


def test_synthetic_asset_raises_on_component_contracts_asset_id_mismatch() -> None:
    spec = _make_spec()
    contracts = _make_component_contracts(asset_id="wrong_asset")
    weights = _make_component_weights()
    holdings = _make_target_holdings()

    with pytest.raises(
        ValueError,
        match=r"component_contracts.asset_id=.*does not match spec.asset_id",
    ):
        SyntheticAsset(
            spec=spec,
            component_contracts=contracts,
            component_weights=weights,
            target_holdings=holdings,
        )


def test_synthetic_asset_raises_on_component_weights_canonical_id_mismatch() -> None:
    spec = _make_spec()
    contracts = _make_component_contracts()
    weights = _make_component_weights(canonical_id="WRONG::ID")
    holdings = _make_target_holdings()

    with pytest.raises(
        ValueError,
        match=r"component_weights.canonical_id=.*does not match spec.canonical_id",
    ):
        SyntheticAsset(
            spec=spec,
            component_contracts=contracts,
            component_weights=weights,
            target_holdings=holdings,
        )


def test_synthetic_asset_raises_on_target_holdings_asset_id_mismatch() -> None:
    spec = _make_spec()
    contracts = _make_component_contracts()
    weights = _make_component_weights()
    holdings = _make_target_holdings(asset_id="wrong_asset")

    with pytest.raises(
        ValueError,
        match=r"target_holdings.asset_id=.*does not match spec.asset_id",
    ):
        SyntheticAsset(
            spec=spec,
            component_contracts=contracts,
            component_weights=weights,
            target_holdings=holdings,
        )


def test_synthetic_asset_raises_on_weights_rule_id_mismatch() -> None:
    spec = _make_spec()
    contracts = _make_component_contracts()
    weights = _make_component_weights(weights_rule_id="WR::OTHER")
    holdings = _make_target_holdings()

    with pytest.raises(
        ValueError,
        match=r"component_weights.weights_rule_id=.*does not match spec.weights_rule_id",
    ):
        SyntheticAsset(
            spec=spec,
            component_contracts=contracts,
            component_weights=weights,
            target_holdings=holdings,
        )


def test_synthetic_asset_raises_on_component_contract_column_order_mismatch() -> None:
    spec = _make_spec()
    contracts = _make_component_contracts(columns=("nxt", "cur"))
    weights = _make_component_weights()
    holdings = _make_target_holdings()

    with pytest.raises(
        ValueError,
        match=r"ComponentContracts columns do not match spec.components order",
    ):
        SyntheticAsset(
            spec=spec,
            component_contracts=contracts,
            component_weights=weights,
            target_holdings=holdings,
        )


def test_synthetic_asset_raises_on_component_weight_column_order_mismatch() -> None:
    spec = _make_spec()
    contracts = _make_component_contracts()
    weights = _make_component_weights(columns=("nxt", "cur"))
    holdings = _make_target_holdings()

    with pytest.raises(
        ValueError,
        match=r"ComponentWeights columns do not match spec.components order",
    ):
        SyntheticAsset(
            spec=spec,
            component_contracts=contracts,
            component_weights=weights,
            target_holdings=holdings,
        )


def test_synthetic_asset_raises_on_contract_and_weight_session_index_mismatch() -> None:
    spec = _make_spec()
    contracts = _make_component_contracts(
        sessions=("2026-03-18", "2026-03-19", "2026-03-20")
    )
    weights = _make_component_weights(
        sessions=("2026-03-18", "2026-03-19", "2026-03-21")
    )
    holdings = _make_target_holdings()

    with pytest.raises(
        ValueError,
        match="ComponentContracts and ComponentWeights session indices do not match",
    ):
        SyntheticAsset(
            spec=spec,
            component_contracts=contracts,
            component_weights=weights,
            target_holdings=holdings,
        )


# -----------------------------------------------------------------------------
# build_synthetic_asset orchestration
# -----------------------------------------------------------------------------


def test_build_synthetic_asset_threads_mxm_business_calendar_to_component_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _make_spec()
    mxm_business_calendar = _make_mxm_business_calendar()

    component_contracts = _make_component_contracts()
    component_weights = _make_component_weights()
    target_holdings = _make_target_holdings()

    _reset_build_fakes(
        component_contracts=component_contracts,
        component_weights=component_weights,
        target_holdings=target_holdings,
    )
    _patch_builders(monkeypatch)

    out = rtmod.build_synthetic_asset(
        spec=spec,
        start_session=np.datetime64("2026-03-18", "D"),
        end_session=np.datetime64("2026-03-20", "D"),
        engine=_unused_engine(),
        calendar_service=_unused_calendar_service(),
        mxm_business_calendar=mxm_business_calendar,
        refdata_api=_unused_refdata_api(),
        unit_converter=_unused_unit_converter(),
    )

    contracts_kwargs = _build_capture.contracts_kwargs
    assert contracts_kwargs is not None
    assert contracts_kwargs["mxm_business_calendar"] is mxm_business_calendar

    weights_kwargs = _build_capture.weights_kwargs
    assert weights_kwargs is not None
    assert weights_kwargs["mxm_business_calendar"] is mxm_business_calendar
    assert weights_kwargs["component_contracts"] is component_contracts

    holdings_kwargs = _build_capture.holdings_kwargs
    assert holdings_kwargs is not None
    assert holdings_kwargs["component_contracts"] is component_contracts
    assert holdings_kwargs["component_weights"] is component_weights

    assert out.component_contracts is component_contracts
    assert out.component_weights is component_weights
    assert out.target_holdings is target_holdings


def test_build_synthetic_asset_returns_synthetic_asset_from_builder_outputs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _make_spec()
    mxm_business_calendar = _make_mxm_business_calendar()

    component_contracts = _make_component_contracts()
    component_weights = _make_component_weights()
    target_holdings = _make_target_holdings()

    _reset_build_fakes(
        component_contracts=component_contracts,
        component_weights=component_weights,
        target_holdings=target_holdings,
    )
    _patch_builders(monkeypatch)

    out = rtmod.build_synthetic_asset(
        spec=spec,
        start_session=np.datetime64("2026-03-18", "D"),
        end_session=np.datetime64("2026-03-20", "D"),
        engine=_unused_engine(),
        calendar_service=_unused_calendar_service(),
        mxm_business_calendar=mxm_business_calendar,
        refdata_api=_unused_refdata_api(),
        unit_converter=_unused_unit_converter(),
    )

    assert isinstance(out, SyntheticAsset)
    assert out.spec is spec
    assert out.component_contracts is component_contracts
    assert out.component_weights is component_weights
    assert out.target_holdings is target_holdings
    assert out.first_session() == np.datetime64("2026-03-18", "D")
    assert out.last_session() == np.datetime64("2026-03-20", "D")
