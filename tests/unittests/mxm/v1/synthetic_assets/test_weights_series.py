# tests/unittests/mxm/v1/synthetic_assets/test_weights_series.py
from __future__ import annotations

import numpy as np
import pytest

from mxm.v1.contracts.contract_series import ContractSeries
from mxm.v1.synthetic_assets.models import LegBinding
from mxm.v1.synthetic_assets.weights_series import (
    MisalignedLegSessions,
    UnsupportedLegRoleStructure,
    assert_identical_sessions,
    infer_role_pairs,
)


def _make_contract_series(
    *,
    product_id: str = "TEST",
    sessions: list[str],
    contract_ids: list[str],
) -> ContractSeries:
    return ContractSeries(
        product_id=product_id,
        canonical_relative_id="REL",
        short_rel_id="R",
        sessions=np.array(sessions, dtype="datetime64[D]"),
        contract_ids=contract_ids,
    )


def test_infer_role_pairs_cont() -> None:
    legs = {
        "cur": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=1"),
        "nxt": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
    }

    out = infer_role_pairs(legs)

    assert out == [("cur", "nxt", 1.0)]


def test_infer_role_pairs_ts() -> None:
    legs = {
        "near_cur": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=1"),
        "near_nxt": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
        "far_cur": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
        "far_nxt": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=3"),
    }

    out = infer_role_pairs(legs)

    assert out == [
        ("near_cur", "near_nxt", 1.0),
        ("far_cur", "far_nxt", -1.0),
    ]


def test_infer_role_pairs_ps() -> None:
    legs = {
        "a_cur": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=1"),
        "a_nxt": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
        "b_cur": LegBinding(product_id="NG", selector_rule_id="REL::MONTH::N=1"),
        "b_nxt": LegBinding(product_id="NG", selector_rule_id="REL::MONTH::N=2"),
    }

    out = infer_role_pairs(legs)

    assert out == [
        ("a_cur", "a_nxt", 1.0),
        ("b_cur", "b_nxt", -1.0),
    ]


def test_infer_role_pairs_raises_on_unknown_structure() -> None:
    legs = {
        "foo": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=1"),
        "bar": LegBinding(product_id="CL", selector_rule_id="REL::MONTH::N=2"),
    }

    with pytest.raises(UnsupportedLegRoleStructure):
        infer_role_pairs(legs)


def test_assert_identical_sessions_passes() -> None:
    cs1 = _make_contract_series(
        sessions=["2026-03-18", "2026-03-19", "2026-03-20"],
        contract_ids=["C1", "C1", "C2"],
    )
    cs2 = _make_contract_series(
        sessions=["2026-03-18", "2026-03-19", "2026-03-20"],
        contract_ids=["C5", "C5", "C6"],
    )

    out = assert_identical_sessions([cs1, cs2])

    assert out.dtype == np.dtype("datetime64[D]")
    assert out.tolist() == [
        np.datetime64("2026-03-18"),
        np.datetime64("2026-03-19"),
        np.datetime64("2026-03-20"),
    ]


def test_assert_identical_sessions_raises_on_mismatch() -> None:
    cs1 = _make_contract_series(
        sessions=["2026-03-18", "2026-03-19", "2026-03-20"],
        contract_ids=["C1", "C1", "C2"],
    )
    cs2 = _make_contract_series(
        sessions=["2026-03-18", "2026-03-20", "2026-03-21"],
        contract_ids=["C5", "C6", "C6"],
    )

    with pytest.raises(MisalignedLegSessions):
        assert_identical_sessions([cs1, cs2])


def test_assert_identical_sessions_raises_on_empty_iterable() -> None:
    with pytest.raises(ValueError):
        assert_identical_sessions([])
