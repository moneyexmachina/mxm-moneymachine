# tests/unittests/mxm/v1/synthetic_assets/test_component_contracts_build.py
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

import mxm.v1.synthetic_assets.component_contracts as ccmod
from mxm.v1.calendars.mxm_business_calendar import MxMBusinessCalendar
from mxm.v1.contracts.contract_series import ContractSeries


def _days(*xs: str) -> np.ndarray:
    return np.array(xs, dtype="datetime64[D]")


def _make_mxm_business_calendar() -> MxMBusinessCalendar:
    """
    Business-day surface with a weekend-like gap:

        2025-01-02
        2025-01-03
        2025-01-06
        2025-01-07
        2025-01-08
    """
    return MxMBusinessCalendar(
        calendar_id="mxm_v1_business",
        business_days=_days(
            "2025-01-02",
            "2025-01-03",
            "2025-01-06",
            "2025-01-07",
            "2025-01-08",
        ),
        observed_end=np.datetime64("2025-01-08", "D"),
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


def _make_spec() -> SimpleNamespace:
    """
    Minimal duck-typed SyntheticAssetSpec replacement for unit tests.

    component_contracts.py currently only relies on:
      - spec.asset_id
      - spec.canonical_id
      - spec.components
      - component.product_id
      - component.selector_rule_id
    """
    components = {
        "cur": SimpleNamespace(
            product_id="prod_cur",
            selector_rule_id="M1",
        ),
        "nxt": SimpleNamespace(
            product_id="prod_nxt",
            selector_rule_id="M2",
        ),
    }
    return SimpleNamespace(
        asset_id="asset_test",
        canonical_id="SYNTH::TEST",
        components=components,
    )


# ---------------------------------------------------------------------------
# _target_business_sessions
# ---------------------------------------------------------------------------


def test_target_business_sessions_normalizes_start_forward_and_end_backward() -> None:
    cal = _make_mxm_business_calendar()

    out = ccmod._target_business_sessions(
        mxm_business_calendar=cal,
        start_session=np.datetime64("2025-01-01", "D"),  # -> next => 2025-01-02
        end_session=np.datetime64("2025-01-05", "D"),  # -> prev => 2025-01-03
    )

    assert np.array_equal(
        out,
        _days("2025-01-02", "2025-01-03"),
    )


def test_target_business_sessions_keeps_exact_business_day_endpoints() -> None:
    cal = _make_mxm_business_calendar()

    out = ccmod._target_business_sessions(
        mxm_business_calendar=cal,
        start_session=np.datetime64("2025-01-03", "D"),
        end_session=np.datetime64("2025-01-07", "D"),
    )

    assert np.array_equal(
        out,
        _days("2025-01-03", "2025-01-06", "2025-01-07"),
    )


# ---------------------------------------------------------------------------
# _map_contract_series_to_business_sessions
# ---------------------------------------------------------------------------


def test_map_contract_series_to_business_sessions_returns_identity_on_exact_support() -> (
    None
):
    series = _make_contract_series(
        product_id="prod_cur",
        rel_id="M1",
        sessions=["2025-01-02", "2025-01-03", "2025-01-06"],
        contract_ids=["A", "B", "C"],
    )

    out = ccmod._map_contract_series_to_business_sessions(
        series=series,
        business_sessions=_days("2025-01-02", "2025-01-03", "2025-01-06"),
    )

    assert out == ["A", "B", "C"]


def test_map_contract_series_to_business_sessions_carries_forward_previous_trading_state() -> (
    None
):
    series = _make_contract_series(
        product_id="prod_cur",
        rel_id="M1",
        sessions=["2025-01-02", "2025-01-03", "2025-01-06"],
        contract_ids=["A", "B", "C"],
    )

    out = ccmod._map_contract_series_to_business_sessions(
        series=series,
        business_sessions=_days("2025-01-02", "2025-01-04", "2025-01-05", "2025-01-06"),
    )

    # prev mapping:
    #   2025-01-02 -> 2025-01-02 -> A
    #   2025-01-04 -> 2025-01-03 -> B
    #   2025-01-05 -> 2025-01-03 -> B
    #   2025-01-06 -> 2025-01-06 -> C
    assert out == ["A", "B", "B", "C"]


# ---------------------------------------------------------------------------
# _assemble_component_contracts_frame
# ---------------------------------------------------------------------------


def test_assemble_component_contracts_frame_projects_components_onto_business_sessions() -> (
    None
):
    spec = _make_spec()
    business_sessions = _days("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07")

    contract_series_by_component = {
        "cur": _make_contract_series(
            product_id="prod_cur",
            rel_id="M1",
            sessions=["2025-01-02", "2025-01-03", "2025-01-06"],
            contract_ids=["CUR_A", "CUR_B", "CUR_C"],
        ),
        "nxt": _make_contract_series(
            product_id="prod_nxt",
            rel_id="M2",
            sessions=["2025-01-02", "2025-01-06", "2025-01-07"],
            contract_ids=["NXT_A", "NXT_B", "NXT_C"],
        ),
    }

    frame = ccmod._assemble_component_contracts_frame(
        spec=spec,
        business_sessions=business_sessions,
        contract_series_by_component=contract_series_by_component,
    )

    expected = pd.DataFrame(
        {
            "cur": ["CUR_A", "CUR_B", "CUR_C", "CUR_C"],
            "nxt": ["NXT_A", "NXT_A", "NXT_B", "NXT_C"],
        },
        index=pd.Index(business_sessions, name="session"),
    )

    assert frame.index.name == "session"
    assert list(frame.columns) == ["cur", "nxt"]
    pd.testing.assert_frame_equal(frame, expected)


def test_assemble_component_contracts_frame_raises_on_component_key_mismatch() -> None:
    spec = _make_spec()

    contract_series_by_component = {
        "cur": _make_contract_series(
            product_id="prod_cur",
            rel_id="M1",
            sessions=["2025-01-02"],
            contract_ids=["CUR_A"],
        ),
        # "nxt" intentionally missing
    }

    with pytest.raises(ValueError, match="Component key mismatch"):
        ccmod._assemble_component_contracts_frame(
            spec=spec,
            business_sessions=_days("2025-01-02"),
            contract_series_by_component=contract_series_by_component,
        )


# ---------------------------------------------------------------------------
# build_component_contracts
# ---------------------------------------------------------------------------


def test_build_component_contracts_returns_business_session_indexed_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _make_spec()
    mxm_business_calendar = _make_mxm_business_calendar()

    captured: dict[str, object] = {}

    def fake_build_contract_series_by_component(
        *,
        spec: object,
        start_session: np.datetime64,
        end_session: np.datetime64,
        engine: object,
        calendar_service: object,
    ) -> dict[str, ContractSeries]:
        captured["start_session"] = start_session
        captured["end_session"] = end_session

        return {
            "cur": _make_contract_series(
                product_id="prod_cur",
                rel_id="M1",
                sessions=["2025-01-02", "2025-01-03", "2025-01-06"],
                contract_ids=["CUR_A", "CUR_B", "CUR_C"],
            ),
            "nxt": _make_contract_series(
                product_id="prod_nxt",
                rel_id="M2",
                sessions=["2025-01-02", "2025-01-06"],
                contract_ids=["NXT_A", "NXT_B"],
            ),
        }

    monkeypatch.setattr(
        ccmod,
        "_build_contract_series_by_component",
        fake_build_contract_series_by_component,
    )

    out = ccmod.build_component_contracts(
        spec=spec,
        start_session=np.datetime64("2025-01-01", "D"),  # normalize -> 2025-01-02
        end_session=np.datetime64("2025-01-07", "D"),  # exact
        engine=object(),
        calendar_service=object(),  # not used by patched helper
        mxm_business_calendar=mxm_business_calendar,
    )

    # Raw builder receives normalized business-session endpoints.
    assert captured["start_session"] == np.datetime64("2025-01-02", "D")
    assert captured["end_session"] == np.datetime64("2025-01-07", "D")

    expected = pd.DataFrame(
        {
            "cur": ["CUR_A", "CUR_B", "CUR_C", "CUR_C"],
            "nxt": ["NXT_A", "NXT_A", "NXT_B", "NXT_B"],
        },
        index=pd.Index(
            _days("2025-01-02", "2025-01-03", "2025-01-06", "2025-01-07"),
            name="session",
        ),
    )

    assert out.asset_id == "asset_test"
    assert out.canonical_id == "SYNTH::TEST"
    pd.testing.assert_frame_equal(out.frame, expected)


def test_build_component_contracts_raises_when_normalized_business_interval_is_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = _make_spec()
    mxm_business_calendar = _make_mxm_business_calendar()

    def fake_build_contract_series_by_component(
        *,
        spec: object,
        start_session: np.datetime64,
        end_session: np.datetime64,
        engine: object,
        calendar_service: object,
    ) -> dict[str, ContractSeries]:
        raise AssertionError(
            "_build_contract_series_by_component should not be reached "
            "when business-session normalization produces an invalid interval"
        )

    monkeypatch.setattr(
        ccmod,
        "_build_contract_series_by_component",
        fake_build_contract_series_by_component,
    )

    with pytest.raises(ValueError, match=r"start .* is after end .*"):
        ccmod.build_component_contracts(
            spec=spec,
            start_session=np.datetime64("2025-01-04", "D"),
            end_session=np.datetime64("2025-01-05", "D"),
            engine=object(),
            calendar_service=object(),
            mxm_business_calendar=mxm_business_calendar,
        )
