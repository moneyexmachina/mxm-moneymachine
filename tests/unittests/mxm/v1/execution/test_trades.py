import pandas as pd
import pandas.testing as pdt

from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle
from mxm.v1.execution.trades import build_target_trades


def test_build_target_trades_from_empty_initial_holdings_returns_target_holdings() -> (
    None
):
    initial_holdings = ContractBundle.empty()
    target_holdings = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 2.5,
            "corn_may2026": -1.0,
        }
    )

    result = build_target_trades(
        initial_holdings=initial_holdings,
        target_holdings=target_holdings,
    )

    expected = pd.Series(
        [2.5, -1.0],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_build_target_trades_to_empty_target_holdings_returns_negative_initial_holdings() -> (
    None
):
    initial_holdings = ContractBundle.from_dict(
        {
            "corn_mar2026": 2,
            "corn_may2026": -1,
        }
    )
    target_holdings = TargetContractBundle.empty()

    result = build_target_trades(
        initial_holdings=initial_holdings,
        target_holdings=target_holdings,
    )

    expected = pd.Series(
        [-2.0, 1.0],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_build_target_trades_handles_overlapping_contracts_correctly() -> None:
    initial_holdings = ContractBundle.from_dict(
        {
            "corn_mar2026": 2,
            "corn_may2026": -1,
        }
    )
    target_holdings = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 3.5,
            "corn_may2026": 2.0,
        }
    )

    result = build_target_trades(
        initial_holdings=initial_holdings,
        target_holdings=target_holdings,
    )

    expected = pd.Series(
        [1.5, 3.0],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_build_target_trades_aligns_on_union_of_contract_ids() -> None:
    initial_holdings = ContractBundle.from_dict(
        {
            "corn_mar2026": 2,
            "corn_may2026": -1,
        }
    )
    target_holdings = TargetContractBundle.from_dict(
        {
            "corn_may2026": 1.0,
            "wheat_jul2026": 4.5,
        }
    )

    result = build_target_trades(
        initial_holdings=initial_holdings,
        target_holdings=target_holdings,
    )

    expected = pd.Series(
        [-2.0, 2.0, 4.5],
        index=pd.Index(
            ["corn_mar2026", "corn_may2026", "wheat_jul2026"],
            name="contract_id",
        ),
        dtype="float64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_build_target_trades_prunes_zero_resulting_entries() -> None:
    initial_holdings = ContractBundle.from_dict(
        {
            "corn_mar2026": 2,
            "corn_may2026": -1,
        }
    )
    target_holdings = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 2.0,
            "corn_may2026": -1.0,
            "wheat_jul2026": 3.5,
        }
    )

    result = build_target_trades(
        initial_holdings=initial_holdings,
        target_holdings=target_holdings,
    )

    expected = pd.Series(
        [3.5],
        index=pd.Index(["wheat_jul2026"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_build_target_trades_preserves_fractional_target_quantities() -> None:
    initial_holdings = ContractBundle.from_dict(
        {
            "corn_mar2026": 1,
        }
    )
    target_holdings = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 1.25,
            "corn_may2026": -0.75,
        }
    )

    result = build_target_trades(
        initial_holdings=initial_holdings,
        target_holdings=target_holdings,
    )

    expected = pd.Series(
        [0.25, -0.75],
        index=pd.Index(["corn_mar2026", "corn_may2026"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_build_target_trades_returns_empty_bundle_when_initial_equals_target() -> None:
    initial_holdings = ContractBundle.from_dict(
        {
            "corn_mar2026": 2,
            "corn_may2026": -1,
        }
    )
    target_holdings = TargetContractBundle.from_dict(
        {
            "corn_mar2026": 2.0,
            "corn_may2026": -1.0,
        }
    )

    result = build_target_trades(
        initial_holdings=initial_holdings,
        target_holdings=target_holdings,
    )

    expected = pd.Series(dtype="float64", index=pd.Index([], name="contract_id"))

    assert result.is_empty()
    pdt.assert_series_equal(result.quantities, expected)


def test_build_target_trades_returns_target_contract_bundle() -> None:
    initial_holdings = ContractBundle.from_dict({"corn_mar2026": 1})
    target_holdings = TargetContractBundle.from_dict({"corn_mar2026": 2.5})

    result = build_target_trades(
        initial_holdings=initial_holdings,
        target_holdings=target_holdings,
    )

    assert isinstance(result, TargetContractBundle)
