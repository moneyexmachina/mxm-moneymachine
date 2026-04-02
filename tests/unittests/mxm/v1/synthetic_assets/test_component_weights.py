# tests/unittests/mxm/v1/synthetic_assets/test_component_weights.py
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import mxm.v1.synthetic_assets.component_weights as cwmod
from mxm.v1.calendars.mxm_business_calendar import MXMBusinessCalendar
from mxm.v1.contracts.contract_series import ContractSeries
from mxm.v1.synthetic_assets.component_contracts import ComponentContracts
from mxm.v1.synthetic_assets.component_weights import (
    ComponentWeights,
    MisalignedAnchorSessions,
    UnsupportedComponentStructure,
    infer_component_pairs,
)
from mxm.v1.synthetic_assets.models import ComponentBinding


def _days(*xs: str) -> np.ndarray:
    return np.array(xs, dtype="datetime64[D]")


def _make_component_weights_frame(
    *,
    sessions: list[str],
    columns: dict[str, list[float]],
) -> pd.DataFrame:
    return pd.DataFrame(
        columns,
        index=pd.Index(np.array(sessions, dtype="datetime64[D]"), name="session"),
    )


def _make_component_contracts() -> ComponentContracts:
    frame = pd.DataFrame(
        {
            "cur": ["CLJ2026", "CLJ2026", "CLK2026", "CLK2026"],
            "nxt": ["CLK2026", "CLK2026", "CLM2026", "CLM2026"],
        },
        index=pd.Index(
            _days("2026-03-18", "2026-03-19", "2026-03-20", "2026-03-23"),
            name="session",
        ),
    )
    return ComponentContracts(
        asset_id="cl_cont",
        canonical_id="SYNTH::TEST",
        frame=frame,
    )


def _make_mxm_business_calendar() -> MXMBusinessCalendar:
    labels = _days(
        "2026-03-18",
        "2026-03-19",
        "2026-03-20",
        "2026-03-23",
        "2026-03-24",
    )
    start_ts = labels.astype("datetime64[ns]")
    end_ts = (start_ts + np.timedelta64(1, "D")).astype("datetime64[ns]")

    return MXMBusinessCalendar(
        calendar_id="mxm_v1_business",
        session_ids=np.arange(labels.size, dtype=np.int64),
        labels=labels,
        start_ts=start_ts,
        end_ts=end_ts,
    )


def _make_contract_series(
    *,
    product_id: str,
    rel_id: str,
    sessions: list[str],
    contract_ids: list[str],
) -> ContractSeries:
    return ContractSeries(
        product_id=product_id,
        canonical_relative_id=rel_id,
        short_rel_id=rel_id,
        sessions=_days(*sessions),
        contract_ids=contract_ids,
    )


def _make_spec_cont() -> SimpleNamespace:
    components = {
        "cur": ComponentBinding(product_id="CL", selector_rule_id="REL::MONTH::N=1"),
        "nxt": ComponentBinding(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
    }
    return SimpleNamespace(
        asset_id="cl_cont",
        canonical_id="SYNTH::TEST",
        weights_rule_id="WR::KIND=LINEAR_ROLL::ROLL_START_OFFSET=N1::ROLL_DURATION=3",
        components=components,
    )


# -----------------------------------------------------------------------------
# infer_component_pairs
# -----------------------------------------------------------------------------


def test_infer_component_pairs_cont() -> None:
    components = {
        "cur": ComponentBinding(product_id="CL", selector_rule_id="REL::MONTH::N=1"),
        "nxt": ComponentBinding(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
    }

    out = infer_component_pairs(components)

    assert out == [("cur", "nxt", 1.0)]


def test_infer_component_pairs_ts() -> None:
    components = {
        "near_cur": ComponentBinding(
            product_id="CL", selector_rule_id="REL::MONTH::N=1"
        ),
        "near_nxt": ComponentBinding(
            product_id="CL", selector_rule_id="REL::MONTH::N=2"
        ),
        "far_cur": ComponentBinding(
            product_id="CL", selector_rule_id="REL::MONTH::N=2"
        ),
        "far_nxt": ComponentBinding(
            product_id="CL", selector_rule_id="REL::MONTH::N=3"
        ),
    }

    out = infer_component_pairs(components)

    assert out == [
        ("near_cur", "near_nxt", 1.0),
        ("far_cur", "far_nxt", -1.0),
    ]


def test_infer_component_pairs_ps() -> None:
    components = {
        "a_cur": ComponentBinding(product_id="CL", selector_rule_id="REL::MONTH::N=1"),
        "a_nxt": ComponentBinding(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
        "b_cur": ComponentBinding(product_id="NG", selector_rule_id="REL::MONTH::N=1"),
        "b_nxt": ComponentBinding(product_id="NG", selector_rule_id="REL::MONTH::N=2"),
    }

    out = infer_component_pairs(components)

    assert out == [
        ("a_cur", "a_nxt", 1.0),
        ("b_cur", "b_nxt", -1.0),
    ]


def test_infer_component_pairs_raises_on_unknown_structure() -> None:
    components = {
        "foo": ComponentBinding(product_id="CL", selector_rule_id="REL::MONTH::N=1"),
        "bar": ComponentBinding(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
    }

    with pytest.raises(UnsupportedComponentStructure):
        infer_component_pairs(components)


# -----------------------------------------------------------------------------
# ComponentWeights schema validation
# -----------------------------------------------------------------------------


def test_component_weights_accepts_valid_frame() -> None:
    frame = _make_component_weights_frame(
        sessions=["2026-03-18", "2026-03-19", "2026-03-20"],
        columns={
            "cur": [1.0, 0.5, 0.0],
            "nxt": [0.0, 0.5, 1.0],
        },
    )

    out = ComponentWeights(
        asset_id="cl_cont",
        canonical_id="SYNTH::TEST",
        weights_rule_id="WR::KIND=LINEAR_ROLL::ROLL_START_OFFSET=N1::ROLL_DURATION=5",
        frame=frame,
    )

    assert out.asset_id == "cl_cont"
    assert out.canonical_id == "SYNTH::TEST"
    assert out.weights_rule_id.startswith("WR::KIND=LINEAR_ROLL")
    assert list(out.frame.columns) == ["cur", "nxt"]
    assert out.frame.index.name == "session"


def test_component_weights_raises_on_duplicate_columns() -> None:
    frame = pd.DataFrame(
        [[1.0, 0.0], [0.5, 0.5]],
        index=pd.Index(
            np.array(["2026-03-18", "2026-03-19"], dtype="datetime64[D]"),
            name="session",
        ),
        columns=["cur", "cur"],
    )

    with pytest.raises(ValueError, match="columns must be unique"):
        ComponentWeights(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            weights_rule_id="WR::TEST",
            frame=frame,
        )


def test_component_weights_raises_on_missing_session_index_name() -> None:
    frame = pd.DataFrame(
        {"cur": [1.0, 0.5], "nxt": [0.0, 0.5]},
        index=pd.Index(np.array(["2026-03-18", "2026-03-19"], dtype="datetime64[D]")),
    )

    with pytest.raises(ValueError, match="index name must be 'session'"):
        ComponentWeights(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            weights_rule_id="WR::TEST",
            frame=frame,
        )


def test_component_weights_raises_on_non_numeric_values() -> None:
    frame = pd.DataFrame(
        {"cur": ["x", "y"], "nxt": ["a", "b"]},
        index=pd.Index(
            np.array(["2026-03-18", "2026-03-19"], dtype="datetime64[D]"),
            name="session",
        ),
    )

    with pytest.raises(TypeError, match="values must be numeric"):
        ComponentWeights(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            weights_rule_id="WR::TEST",
            frame=frame,
        )


def test_component_weights_raises_on_null_values() -> None:
    frame = _make_component_weights_frame(
        sessions=["2026-03-18", "2026-03-19"],
        columns={
            "cur": [1.0, np.nan],
            "nxt": [0.0, 0.5],
        },
    )

    with pytest.raises(ValueError, match="contains null weight values"):
        ComponentWeights(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            weights_rule_id="WR::TEST",
            frame=frame,
        )


# -----------------------------------------------------------------------------
# Helper-level business-session mapping
# -----------------------------------------------------------------------------


def test_map_anchor_contract_ids_to_business_sessions_carries_forward_previous_state() -> (
    None
):
    series = _make_contract_series(
        product_id="CL",
        rel_id="M1",
        sessions=["2026-03-18", "2026-03-20", "2026-03-24"],
        contract_ids=["A", "B", "C"],
    )

    business_sessions = _days(
        "2026-03-18",
        "2026-03-19",
        "2026-03-20",
        "2026-03-23",
        "2026-03-24",
    )

    out = cwmod._map_anchor_contract_ids_to_business_sessions(
        series=series,
        business_sessions=business_sessions,
    )

    # prev mapping:
    # 18 -> 18 -> A
    # 19 -> 18 -> A
    # 20 -> 20 -> B
    # 23 -> 20 -> B
    # 24 -> 24 -> C
    assert out == ["A", "A", "B", "B", "C"]


# -----------------------------------------------------------------------------
# build_component_weights orchestration
# -----------------------------------------------------------------------------


def test_build_component_weights_returns_business_session_indexed_weights(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _make_spec_cont()
    component_contracts = _make_component_contracts()
    mxm_business_calendar = _make_mxm_business_calendar()

    captured: dict[str, object] = {}

    def fake_build_raw_anchor_contract_series_for_component(
        *,
        component: object,
        start_session: np.datetime64,
        end_session: np.datetime64,
        engine: object,
        calendar_service: object,
    ) -> ContractSeries:
        # One raw anchor series on trading support
        return _make_contract_series(
            product_id="CL",
            rel_id="M1",
            sessions=["2026-03-18", "2026-03-20", "2026-03-24"],
            contract_ids=["ANCHOR_A", "ANCHOR_B", "ANCHOR_C"],
        )

    monkeypatch.setattr(
        cwmod,
        "_build_raw_anchor_contract_series_for_component",
        fake_build_raw_anchor_contract_series_for_component,
    )

    class _FakeTradingDays:
        def __init__(self, sessions: np.ndarray, vals: list[int]) -> None:
            self.sessions = sessions
            self.trading_days_to_ltd = np.array(vals, dtype=np.int64)

    def fake_build_trading_days_to_ltd_on_business_sessions(
        *,
        product_id: str,
        sessions: np.ndarray,
        contract_ids: list[str],
        calendar_service: object,
        refdata_api: object,
    ) -> _FakeTradingDays:
        captured["product_id"] = product_id
        captured["sessions"] = sessions.copy()
        captured["contract_ids"] = list(contract_ids)

        # 4 sessions -> simple descending clock
        return _FakeTradingDays(sessions, [3, 2, 1, 0])

    monkeypatch.setattr(
        cwmod,
        "build_trading_days_to_ltd_on_business_sessions",
        fake_build_trading_days_to_ltd_on_business_sessions,
    )

    class _FakeRollModel:
        def compute_weights_from_bdays_to_ltd(
            self, *, bdays_to_ltd: np.ndarray
        ) -> tuple[np.ndarray, np.ndarray]:
            # simple deterministic transform for test visibility
            w_cur = bdays_to_ltd.astype(float)
            w_nxt = -bdays_to_ltd.astype(float)
            return w_cur, w_nxt

    monkeypatch.setattr(
        cwmod,
        "_build_roll_model",
        lambda weights_rule_id: _FakeRollModel(),
    )

    out = cwmod.build_component_weights(
        spec=spec,
        component_contracts=component_contracts,
        engine=object(),
        calendar_service=object(),
        mxm_business_calendar=mxm_business_calendar,
        refdata_api=object(),
    )

    expected_sessions = _days("2026-03-18", "2026-03-19", "2026-03-20", "2026-03-23")

    # The anchor ids should have been projected with prev mapping:
    # 18 -> 18 -> ANCHOR_A
    # 19 -> 18 -> ANCHOR_A
    # 20 -> 20 -> ANCHOR_B
    # 23 -> 20 -> ANCHOR_B
    assert captured["product_id"] == "CL"
    assert np.array_equal(captured["sessions"], expected_sessions)
    assert captured["contract_ids"] == ["ANCHOR_A", "ANCHOR_A", "ANCHOR_B", "ANCHOR_B"]

    expected = pd.DataFrame(
        {
            "cur": [3.0, 2.0, 1.0, 0.0],
            "nxt": [-3.0, -2.0, -1.0, -0.0],
        },
        index=pd.Index(expected_sessions, name="session"),
    )

    pd.testing.assert_frame_equal(out.frame, expected)
    assert out.asset_id == "cl_cont"
    assert out.canonical_id == "SYNTH::TEST"


def test_build_component_weights_raises_when_bdays_sessions_do_not_match_component_contracts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _make_spec_cont()
    component_contracts = _make_component_contracts()
    mxm_business_calendar = _make_mxm_business_calendar()

    def fake_build_raw_anchor_contract_series_for_component(
        *,
        component: object,
        start_session: np.datetime64,
        end_session: np.datetime64,
        engine: object,
        calendar_service: object,
    ) -> ContractSeries:
        return _make_contract_series(
            product_id="CL",
            rel_id="M1",
            sessions=["2026-03-18", "2026-03-20"],
            contract_ids=["ANCHOR_A", "ANCHOR_B"],
        )

    monkeypatch.setattr(
        cwmod,
        "_build_raw_anchor_contract_series_for_component",
        fake_build_raw_anchor_contract_series_for_component,
    )

    class _FakeTradingDays:
        def __init__(self) -> None:
            self.sessions = _days("2026-03-18", "2026-03-19")  # wrong length/support
            self.trading_days_to_ltd = np.array([1, 0], dtype=np.int64)

    monkeypatch.setattr(
        cwmod,
        "build_trading_days_to_ltd_on_business_sessions",
        lambda **kwargs: _FakeTradingDays(),
    )

    class _FakeRollModel:
        def compute_weights_from_bdays_to_ltd(
            self, *, bdays_to_ltd: np.ndarray
        ) -> tuple[np.ndarray, np.ndarray]:
            return bdays_to_ltd.astype(float), bdays_to_ltd.astype(float)

    monkeypatch.setattr(
        cwmod,
        "_build_roll_model",
        lambda weights_rule_id: _FakeRollModel(),
    )

    with pytest.raises(MisalignedAnchorSessions, match="Anchor sessions differ"):
        cwmod.build_component_weights(
            spec=spec,
            component_contracts=component_contracts,
            engine=object(),
            calendar_service=object(),
            mxm_business_calendar=mxm_business_calendar,
            refdata_api=object(),
        )


def test_realise_component_weights_threads_business_calendar_through_builders(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _make_spec_cont()
    mxm_business_calendar = _make_mxm_business_calendar()

    component_contracts = _make_component_contracts()

    captured: dict[str, object] = {}

    def fake_build_component_contracts(**kwargs):
        captured["build_component_contracts_kwargs"] = dict(kwargs)
        return component_contracts

    def fake_build_component_weights(**kwargs):
        captured["build_component_weights_kwargs"] = dict(kwargs)
        return ComponentWeights(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            weights_rule_id=spec.weights_rule_id,
            frame=_make_component_weights_frame(
                sessions=["2026-03-18", "2026-03-19"],
                columns={"cur": [1.0, 0.0], "nxt": [0.0, 1.0]},
            ),
        )

    monkeypatch.setattr(
        cwmod, "build_component_contracts", fake_build_component_contracts
    )
    monkeypatch.setattr(cwmod, "build_component_weights", fake_build_component_weights)

    out = cwmod.realise_component_weights(
        spec=spec,
        start_session=np.datetime64("2026-03-18", "D"),
        end_session=np.datetime64("2026-03-19", "D"),
        engine=object(),
        calendar_service=object(),
        mxm_business_calendar=mxm_business_calendar,
        refdata_api=object(),
    )

    assert (
        captured["build_component_contracts_kwargs"]["mxm_business_calendar"]
        is mxm_business_calendar
    )
    assert (
        captured["build_component_weights_kwargs"]["mxm_business_calendar"]
        is mxm_business_calendar
    )
    assert out.asset_id == "cl_cont"
