from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd
import pytest

from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.refdata.models import ProductUnit
from mxm.v1.synthetic_assets.component_contracts import ComponentContracts
from mxm.v1.synthetic_assets.component_weights import ComponentWeights
from mxm.v1.synthetic_assets.models import ComponentBinding, SyntheticAssetSpec
from mxm.v1.synthetic_assets.target_holdings import (
    TargetHoldings,
    build_target_holdings,
)
from mxm.v1.synthetic_assets.unit_conversion import UnitConverter
from mxm.v1.synthetic_assets.weights_rules import (
    WeightsRuleSpec,
    canonical_weights_rule_id,
)
from mxm.v1.utils.canonical_id_encoding import encode_canonical_id_component

_TEST_WR_ID = canonical_weights_rule_id(
    WeightsRuleSpec(
        kind="LINEAR_ROLL",
        roll_start_offset=3,
        roll_duration=1,
    )
)

_TEST_WR_ENC = encode_canonical_id_component(_TEST_WR_ID)

_TEST_CANONICAL_ID = (
    "SA::KIND=CONT"
    "::P0=cl"
    "::CUR=RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1"
    "::NXT=RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=2"
    f"::WR={_TEST_WR_ENC}"
)


@dataclass(frozen=True, slots=True)
class _StubContract:
    unit: ProductUnit
    contract_size: float


class _StubRefDataAPI:
    def __init__(self, contracts: dict[str, _StubContract]) -> None:
        self._contracts = contracts

    def get_contract_by_id(self, contract_id: str) -> _StubContract:
        return self._contracts[contract_id]


def _make_component_contracts(
    *,
    asset_id: str = "cl_cont",
    canonical_id: str = _TEST_CANONICAL_ID,
    sessions: list[str],
    columns: dict[str, list[str]],
) -> ComponentContracts:
    frame = pd.DataFrame(
        columns,
        index=pd.Index(np.array(sessions, dtype="datetime64[D]"), name="session"),
    )
    return ComponentContracts(
        asset_id=asset_id,
        canonical_id=canonical_id,
        frame=frame,
    )


def _make_component_weights(
    *,
    asset_id: str = "cl_cont",
    canonical_id: str = _TEST_CANONICAL_ID,
    weights_rule_id: str = _TEST_WR_ID,
    sessions: list[str],
    columns: dict[str, list[float]],
) -> ComponentWeights:
    frame = pd.DataFrame(
        columns,
        index=pd.Index(np.array(sessions, dtype="datetime64[D]"), name="session"),
    )
    return ComponentWeights(
        asset_id=asset_id,
        canonical_id=canonical_id,
        weights_rule_id=weights_rule_id,
        frame=frame,
    )


def _make_spec(
    *,
    asset_id: str = "cl_cont",
    canonical_id: str = _TEST_CANONICAL_ID,
    currency: str = "USD",
    unit: ProductUnit | str = ProductUnit.CONTRACT,
    size: float = 1000.0,
    weights_rule_id: str = _TEST_WR_ID,
    components: dict[str, ComponentBinding] | None = None,
) -> SyntheticAssetSpec:
    if components is None:
        components = {
            "cur": ComponentBinding(
                product_id="CL", selector_rule_id="REL::MONTH::N=1"
            ),
            "nxt": ComponentBinding(
                product_id="CL", selector_rule_id="REL::MONTH::N=2"
            ),
        }

    unit_value = unit.name if isinstance(unit, ProductUnit) else unit

    return SyntheticAssetSpec(
        asset_id=asset_id,
        canonical_id=canonical_id,
        currency=currency,
        unit=unit_value,
        size=size,
        weights_rule_id=weights_rule_id,
        components=components,
    )


def _make_target_holdings_frame(
    *,
    rows: list[tuple[str, str, float]],
) -> pd.DataFrame:
    sessions = pd.Index(
        np.array([session for session, _, _ in rows], dtype="datetime64[D]"),
        name="session",
    )
    contract_ids = pd.Index(
        [contract_id for _, contract_id, _ in rows],
        name="contract_id",
    )

    index = pd.MultiIndex.from_arrays(
        [sessions, contract_ids],
        names=["session", "contract_id"],
    )

    frame = pd.DataFrame(
        {"target_holding": [value for _, _, value in rows]},
        index=index,
    ).sort_index()

    return frame


def test_target_holdings_accepts_valid_frame() -> None:
    frame = _make_target_holdings_frame(
        rows=[
            ("2026-03-18", "CLJ2026", 0.7),
            ("2026-03-18", "CLK2026", 0.3),
            ("2026-03-19", "CLK2026", 1.0),
        ]
    )

    out = TargetHoldings(
        asset_id="cl_cont",
        canonical_id="SA::TEST",
        frame=frame,
    )

    assert out.asset_id == "cl_cont"
    assert out.canonical_id == "SA::TEST"
    assert list(out.frame.columns) == ["target_holding"]
    assert list(out.frame.index.names) == ["session", "contract_id"]


def test_target_holdings_raises_on_non_multiindex() -> None:
    frame = pd.DataFrame(
        {"target_holding": [0.7, 0.3]},
        index=pd.Index(
            np.array(["2026-03-18", "2026-03-19"], dtype="datetime64[D]"),
            name="session",
        ),
    )

    with pytest.raises(ValueError, match="must be a pandas MultiIndex"):
        TargetHoldings(
            asset_id="cl_cont",
            canonical_id="SA::TEST",
            frame=frame,
        )


def test_target_holdings_raises_on_wrong_index_names() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (np.datetime64("2026-03-18"), "CLJ2026"),
            (np.datetime64("2026-03-19"), "CLK2026"),
        ],
        names=["date", "contract"],
    )
    frame = pd.DataFrame({"target_holding": [0.7, 0.3]}, index=index)

    with pytest.raises(ValueError, match="index names must be"):
        TargetHoldings(
            asset_id="cl_cont",
            canonical_id="SA::TEST",
            frame=frame,
        )


def test_target_holdings_raises_on_duplicate_index_rows() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (np.datetime64("2026-03-18"), "CLJ2026"),
            (np.datetime64("2026-03-18"), "CLJ2026"),
        ],
        names=["session", "contract_id"],
    )
    frame = pd.DataFrame({"target_holding": [0.7, 0.3]}, index=index)

    with pytest.raises(ValueError, match="contains duplicate"):
        TargetHoldings(
            asset_id="cl_cont",
            canonical_id="SA::TEST",
            frame=frame,
        )


def test_target_holdings_raises_on_null_session_index() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (np.datetime64("2026-03-18"), "CLJ2026"),
            (pd.NaT, "CLK2026"),
        ],
        names=["session", "contract_id"],
    )
    frame = pd.DataFrame({"target_holding": [0.7, 0.3]}, index=index)

    with pytest.raises(ValueError, match="session index contains null values"):
        TargetHoldings(
            asset_id="cl_cont",
            canonical_id="SA::TEST",
            frame=frame,
        )


def test_target_holdings_raises_on_non_numeric_values() -> None:
    frame = _make_target_holdings_frame(
        rows=[
            ("2026-03-18", "CLJ2026", 0.7),
            ("2026-03-19", "CLK2026", 0.3),
        ]
    ).astype({"target_holding": "object"})
    frame.loc[(np.datetime64("2026-03-18"), "CLJ2026"), "target_holding"] = "x"

    with pytest.raises(TypeError, match="must be numeric"):
        TargetHoldings(
            asset_id="cl_cont",
            canonical_id="SA::TEST",
            frame=frame,
        )


def test_build_target_holdings_cont_happy_path_identity_units() -> None:
    spec = _make_spec(
        unit=ProductUnit.CONTRACT,
        size=1000.0,
    )

    component_contracts = _make_component_contracts(
        sessions=["2026-03-18", "2026-03-19"],
        columns={
            "cur": ["CLJ2026", "CLK2026"],
            "nxt": ["CLK2026", "CLM2026"],
        },
    )
    component_weights = _make_component_weights(
        sessions=["2026-03-18", "2026-03-19"],
        columns={
            "cur": [0.7, 0.2],
            "nxt": [0.3, 0.8],
        },
    )

    refdata_api = _StubRefDataAPI(
        {
            "CLJ2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
            "CLK2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
            "CLM2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
        }
    )
    unit_converter = UnitConverter()

    out = build_target_holdings(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
        refdata_api=cast(RefDataAPI, refdata_api),
        unit_converter=unit_converter,
    )

    expected = _make_target_holdings_frame(
        rows=[
            ("2026-03-18", "CLJ2026", 0.7),
            ("2026-03-18", "CLK2026", 0.3),
            ("2026-03-19", "CLK2026", 0.2),
            ("2026-03-19", "CLM2026", 0.8),
        ]
    )

    pd.testing.assert_frame_equal(out.frame, expected)


def test_build_target_holdings_aggregates_same_contract_across_components() -> None:
    spec = _make_spec(
        unit=ProductUnit.CONTRACT,
        size=1000.0,
    )

    component_contracts = _make_component_contracts(
        sessions=["2026-03-18"],
        columns={
            "cur": ["CLK2026"],
            "nxt": ["CLK2026"],
        },
    )
    component_weights = _make_component_weights(
        sessions=["2026-03-18"],
        columns={
            "cur": [0.4],
            "nxt": [0.6],
        },
    )

    refdata_api = _StubRefDataAPI(
        {
            "CLK2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
        }
    )
    unit_converter = UnitConverter()

    out = build_target_holdings(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
        refdata_api=cast(RefDataAPI, refdata_api),
        unit_converter=unit_converter,
    )

    expected = _make_target_holdings_frame(
        rows=[
            ("2026-03-18", "CLK2026", 1.0),
        ]
    )

    pd.testing.assert_frame_equal(out.frame, expected)


def test_build_target_holdings_applies_size_scaling() -> None:
    spec = _make_spec(
        unit=ProductUnit.CONTRACT,
        size=2000.0,
    )

    component_contracts = _make_component_contracts(
        sessions=["2026-03-18"],
        columns={
            "cur": ["CLJ2026"],
            "nxt": ["CLK2026"],
        },
    )
    component_weights = _make_component_weights(
        sessions=["2026-03-18"],
        columns={
            "cur": [0.7],
            "nxt": [0.3],
        },
    )

    refdata_api = _StubRefDataAPI(
        {
            "CLJ2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
            "CLK2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
        }
    )
    unit_converter = UnitConverter()

    out = build_target_holdings(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
        refdata_api=cast(RefDataAPI, refdata_api),
        unit_converter=unit_converter,
    )

    expected = _make_target_holdings_frame(
        rows=[
            ("2026-03-18", "CLJ2026", 1.4),
            ("2026-03-18", "CLK2026", 0.6),
        ]
    )

    pd.testing.assert_frame_equal(out.frame, expected)


def test_build_target_holdings_applies_unit_conversion() -> None:
    spec = _make_spec(
        unit=ProductUnit.GRAM,
        size=31.1034768,
    )

    component_contracts = _make_component_contracts(
        sessions=["2026-03-18"],
        columns={
            "cur": ["GCJ2026"],
            "nxt": ["GCK2026"],
        },
    )
    component_weights = _make_component_weights(
        sessions=["2026-03-18"],
        columns={
            "cur": [0.5],
            "nxt": [0.5],
        },
    )

    refdata_api = _StubRefDataAPI(
        {
            "GCJ2026": _StubContract(
                unit=ProductUnit.TROY_OUNCE,
                contract_size=1.0,
            ),
            "GCK2026": _StubContract(
                unit=ProductUnit.TROY_OUNCE,
                contract_size=1.0,
            ),
        }
    )
    unit_converter = UnitConverter(
        conversion_factors={
            (ProductUnit.GRAM, ProductUnit.TROY_OUNCE): 1.0 / 31.1034768,
        }
    )

    out = build_target_holdings(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
        refdata_api=cast(RefDataAPI, refdata_api),
        unit_converter=unit_converter,
    )

    expected = _make_target_holdings_frame(
        rows=[
            ("2026-03-18", "GCJ2026", 0.5),
            ("2026-03-18", "GCK2026", 0.5),
        ]
    )

    pd.testing.assert_frame_equal(out.frame, expected)


def test_build_target_holdings_raises_on_component_contracts_asset_mismatch() -> None:
    spec = _make_spec(asset_id="cl_cont")

    component_contracts = _make_component_contracts(
        asset_id="other_asset",
        sessions=["2026-03-18"],
        columns={"cur": ["CLJ2026"], "nxt": ["CLK2026"]},
    )
    component_weights = _make_component_weights(
        asset_id="cl_cont",
        sessions=["2026-03-18"],
        columns={"cur": [0.7], "nxt": [0.3]},
    )

    refdata_api = _StubRefDataAPI(
        {
            "CLJ2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
            "CLK2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
        }
    )
    unit_converter = UnitConverter()

    with pytest.raises(ValueError, match=r"component_contracts.asset_id"):
        _ = build_target_holdings(
            spec=spec,
            component_contracts=component_contracts,
            component_weights=component_weights,
            refdata_api=cast(RefDataAPI, refdata_api),
            unit_converter=unit_converter,
        )


def test_build_target_holdings_raises_on_component_column_mismatch() -> None:
    spec = _make_spec(
        components={
            "cur": ComponentBinding(
                product_id="CL", selector_rule_id="REL::MONTH::N=1"
            ),
            "nxt": ComponentBinding(
                product_id="CL", selector_rule_id="REL::MONTH::N=2"
            ),
        }
    )

    component_contracts = _make_component_contracts(
        sessions=["2026-03-18"],
        columns={"cur": ["CLJ2026"], "far": ["CLK2026"]},
    )
    component_weights = _make_component_weights(
        sessions=["2026-03-18"],
        columns={"cur": [0.7], "far": [0.3]},
    )

    refdata_api = _StubRefDataAPI(
        {
            "CLJ2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
            "CLK2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
        }
    )
    unit_converter = UnitConverter()

    with pytest.raises(ValueError, match=r"columns do not match spec.components"):
        _ = build_target_holdings(
            spec=spec,
            component_contracts=component_contracts,
            component_weights=component_weights,
            refdata_api=cast(RefDataAPI, refdata_api),
            unit_converter=unit_converter,
        )


def test_build_target_holdings_raises_on_session_index_mismatch() -> None:
    spec = _make_spec()

    component_contracts = _make_component_contracts(
        sessions=["2026-03-18", "2026-03-19"],
        columns={
            "cur": ["CLJ2026", "CLK2026"],
            "nxt": ["CLK2026", "CLM2026"],
        },
    )
    component_weights = _make_component_weights(
        sessions=["2026-03-18", "2026-03-20"],
        columns={
            "cur": [0.7, 0.2],
            "nxt": [0.3, 0.8],
        },
    )

    refdata_api = _StubRefDataAPI(
        {
            "CLJ2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
            "CLK2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
            "CLM2026": _StubContract(unit=ProductUnit.CONTRACT, contract_size=1000.0),
        }
    )
    unit_converter = UnitConverter()

    with pytest.raises(ValueError, match="session indices do not match"):
        _ = build_target_holdings(
            spec=spec,
            component_contracts=component_contracts,
            component_weights=component_weights,
            refdata_api=cast(RefDataAPI, refdata_api),
            unit_converter=unit_converter,
        )
