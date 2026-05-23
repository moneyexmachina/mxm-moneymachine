from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from mxm.moneymachine.synthetic_assets.component_contracts import ComponentContracts


def _make_component_contracts_frame(
    *,
    sessions: list[str],
    columns: dict[str, list[str]],
) -> pd.DataFrame:
    frame = pd.DataFrame(
        columns,
        index=pd.Index(np.array(sessions, dtype="datetime64[D]"), name="session"),
    )
    return frame


def test_component_contracts_accepts_valid_frame() -> None:
    frame = _make_component_contracts_frame(
        sessions=["2026-03-18", "2026-03-19", "2026-03-20"],
        columns={
            "cur": ["CLJ2026", "CLK2026", "CLK2026"],
            "nxt": ["CLK2026", "CLM2026", "CLM2026"],
        },
    )

    out = ComponentContracts(
        asset_id="cl_cont",
        canonical_id="SYNTH::TEST",
        frame=frame,
    )

    assert out.asset_id == "cl_cont"
    assert out.canonical_id == "SYNTH::TEST"
    assert list(out.frame.columns) == ["cur", "nxt"]
    assert out.frame.index.name == "session"


def test_component_contracts_raises_on_multiindex() -> None:
    index = pd.MultiIndex.from_tuples(
        [
            (np.datetime64("2026-03-18"), "cur"),
            (np.datetime64("2026-03-18"), "nxt"),
        ],
        names=["session", "component"],
    )

    frame = pd.DataFrame(
        {"contract_id": ["CLJ2026", "CLK2026"]},
        index=index,
    )

    with pytest.raises(ValueError, match="must not be a MultiIndex"):
        ComponentContracts(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            frame=frame,
        )


def test_component_contracts_raises_on_missing_session_index_name() -> None:
    frame = pd.DataFrame(
        {
            "cur": ["CLJ2026", "CLK2026"],
            "nxt": ["CLK2026", "CLM2026"],
        },
        index=pd.Index(np.array(["2026-03-18", "2026-03-19"], dtype="datetime64[D]")),
    )

    with pytest.raises(ValueError, match="index name must be 'session'"):
        ComponentContracts(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            frame=frame,
        )


def test_component_contracts_raises_on_duplicate_columns() -> None:
    frame = pd.DataFrame(
        [["CLJ2026", "CLK2026"], ["CLK2026", "CLM2026"]],
        index=pd.Index(
            np.array(["2026-03-18", "2026-03-19"], dtype="datetime64[D]"),
            name="session",
        ),
        columns=["cur", "cur"],
    )

    with pytest.raises(ValueError, match="columns must be unique"):
        ComponentContracts(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            frame=frame,
        )


def test_component_contracts_raises_on_empty_columns() -> None:
    frame = pd.DataFrame(
        index=pd.Index(
            np.array(["2026-03-18", "2026-03-19"], dtype="datetime64[D]"),
            name="session",
        ),
    )

    with pytest.raises(ValueError, match="must contain at least one component column"):
        ComponentContracts(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            frame=frame,
        )


def test_component_contracts_raises_on_unsorted_index() -> None:
    frame = _make_component_contracts_frame(
        sessions=["2026-03-19", "2026-03-18"],
        columns={
            "cur": ["CLK2026", "CLJ2026"],
            "nxt": ["CLM2026", "CLK2026"],
        },
    )

    with pytest.raises(ValueError, match="index must be sorted by session"):
        ComponentContracts(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            frame=frame,
        )


def test_component_contracts_raises_on_null_session_index() -> None:
    frame = pd.DataFrame(
        {
            "cur": ["CLJ2026", "CLK2026"],
            "nxt": ["CLK2026", "CLM2026"],
        },
        index=pd.Index(
            [np.datetime64("2026-03-18"), pd.NaT],
            name="session",
        ),
    )

    with pytest.raises(ValueError, match="index contains null session values"):
        ComponentContracts(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            frame=frame,
        )


def test_component_contracts_raises_on_null_contract_id_values() -> None:
    frame = _make_component_contracts_frame(
        sessions=["2026-03-18", "2026-03-19"],
        columns={
            "cur": ["CLJ2026", None],  # type: ignore[list-item]
            "nxt": ["CLK2026", "CLM2026"],
        },
    )

    with pytest.raises(ValueError, match="contains null contract_id values"):
        ComponentContracts(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            frame=frame,
        )


def test_component_contracts_raises_on_non_string_values() -> None:
    frame = pd.DataFrame(
        {
            "cur": ["CLJ2026", 123],
            "nxt": ["CLK2026", "CLM2026"],
        },
        index=pd.Index(
            np.array(["2026-03-18", "2026-03-19"], dtype="datetime64[D]"),
            name="session",
        ),
    )

    with pytest.raises(TypeError, match="must contain only contract_id strings"):
        ComponentContracts(
            asset_id="cl_cont",
            canonical_id="SYNTH::TEST",
            frame=frame,
        )
