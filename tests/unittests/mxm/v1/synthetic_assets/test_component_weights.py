# tests/unittests/mxm/v1/synthetic_assets/test_component_weights.py
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mxm.v1.synthetic_assets.component_weights import (
    ComponentWeights,
    UnsupportedComponentStructure,
    infer_component_pairs,
)
from mxm.v1.synthetic_assets.models import ComponentBinding


def _make_component_weights_frame(
    *,
    sessions: list[str],
    columns: dict[str, list[float]],
) -> pd.DataFrame:
    frame = pd.DataFrame(
        columns,
        index=pd.Index(np.array(sessions, dtype="datetime64[D]"), name="session"),
    )
    return frame


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
