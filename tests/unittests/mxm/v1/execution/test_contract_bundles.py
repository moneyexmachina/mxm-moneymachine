import pandas as pd
import pandas.testing as pdt
import pytest

from mxm.v1.execution.contract_bundles import ContractBundle, TargetContractBundle


def test_contract_bundle_empty_is_canonical() -> None:
    bundle = ContractBundle.empty()

    expected = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))

    assert bundle.is_empty()
    assert len(bundle) == 0
    pdt.assert_series_equal(bundle.quantities, expected)


def test_target_contract_bundle_empty_is_canonical() -> None:
    bundle = TargetContractBundle.empty()

    expected = pd.Series(dtype="float64", index=pd.Index([], name="contract_id"))

    assert bundle.is_empty()
    assert len(bundle) == 0
    pdt.assert_series_equal(bundle.quantities, expected)


def test_contract_bundle_sorts_index_and_drops_zero_entries() -> None:
    series = pd.Series(
        [0, 2, -1],
        index=pd.Index(["c", "a", "b"], name="whatever"),
    )

    bundle = ContractBundle(series)

    expected = pd.Series(
        [2, -1],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(bundle.quantities, expected)


def test_target_contract_bundle_sorts_index_and_drops_zero_entries() -> None:
    series = pd.Series(
        [0.0, 2.5, -1.25],
        index=pd.Index(["c", "a", "b"], name="whatever"),
    )

    bundle = TargetContractBundle(series)

    expected = pd.Series(
        [2.5, -1.25],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(bundle.quantities, expected)


def test_contract_bundle_renames_index_to_contract_id() -> None:
    series = pd.Series(
        [1, 2],
        index=pd.Index(["x", "y"], name="old_name"),
    )

    bundle = ContractBundle(series)

    assert bundle.quantities.index.name == "contract_id"


def test_contract_bundle_accepts_integer_series() -> None:
    series = pd.Series(
        [1, -2],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="int64",
    )

    bundle = ContractBundle(series)

    expected = pd.Series(
        [1, -2],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(bundle.quantities, expected)


def test_contract_bundle_accepts_integral_float_values() -> None:
    series = pd.Series(
        [1.0, -2.0],
        index=pd.Index(["a", "b"], name="contract_id"),
    )

    bundle = ContractBundle(series)

    expected = pd.Series(
        [1, -2],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(bundle.quantities, expected)


def test_contract_bundle_rejects_fractional_values() -> None:
    series = pd.Series(
        [1.5, -2.0],
        index=pd.Index(["a", "b"], name="contract_id"),
    )

    with pytest.raises(ValueError, match="integer lot quantities"):
        ContractBundle(series)


def test_contract_bundle_rejects_missing_values() -> None:
    series = pd.Series(
        [1.0, None],
        index=pd.Index(["a", "b"], name="contract_id"),
    )

    with pytest.raises(ValueError, match="does not allow missing quantities"):
        ContractBundle(series)


def test_target_contract_bundle_accepts_float_values() -> None:
    series = pd.Series(
        [1.25, -2.5],
        index=pd.Index(["a", "b"], name="contract_id"),
    )

    bundle = TargetContractBundle(series)

    expected = pd.Series(
        [1.25, -2.5],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(bundle.quantities, expected)


def test_target_contract_bundle_coerces_integer_values_to_float() -> None:
    series = pd.Series(
        [1, -2],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="int64",
    )

    bundle = TargetContractBundle(series)

    expected = pd.Series(
        [1.0, -2.0],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(bundle.quantities, expected)


def test_target_contract_bundle_rejects_missing_values() -> None:
    series = pd.Series(
        [1.0, None],
        index=pd.Index(["a", "b"], name="contract_id"),
    )

    with pytest.raises(ValueError, match="does not allow missing quantities"):
        TargetContractBundle(series)


def test_target_contract_bundle_rejects_non_numeric_values() -> None:
    series = pd.Series(
        ["abc", "def"],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="object",
    )

    with pytest.raises(TypeError, match="requires numeric quantities"):
        TargetContractBundle(series)


def test_contract_bundle_missing_contract_quantity_defaults_to_zero() -> None:
    bundle = ContractBundle.from_dict({"a": 2, "b": -1})

    assert bundle.quantity("a") == 2
    assert bundle.quantity("missing") == 0


def test_target_contract_bundle_missing_contract_quantity_defaults_to_zero() -> None:
    bundle = TargetContractBundle.from_dict({"a": 2.5, "b": -1.25})

    assert bundle.quantity("a") == 2.5
    assert bundle.quantity("missing") == 0.0


def test_all_zero_input_produces_empty_contract_bundle() -> None:
    bundle = ContractBundle.from_dict({"a": 0, "b": 0})

    expected = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))

    assert bundle.is_empty()
    pdt.assert_series_equal(bundle.quantities, expected)


def test_all_zero_input_produces_empty_target_contract_bundle() -> None:
    bundle = TargetContractBundle.from_dict({"a": 0.0, "b": 0.0})

    expected = pd.Series(dtype="float64", index=pd.Index([], name="contract_id"))

    assert bundle.is_empty()
    pdt.assert_series_equal(bundle.quantities, expected)


def test_contract_bundle_addition_aligns_on_union_of_contract_ids() -> None:
    left = ContractBundle.from_dict({"a": 2, "b": -1})
    right = ContractBundle.from_dict({"b": 3, "c": 4})

    result = left + right

    expected = pd.Series(
        [2, 2, 4],
        index=pd.Index(["a", "b", "c"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_contract_bundle_subtraction_aligns_on_union_of_contract_ids() -> None:
    left = ContractBundle.from_dict({"a": 2, "b": -1})
    right = ContractBundle.from_dict({"b": 3, "c": 4})

    result = left - right

    expected = pd.Series(
        [2, -4, -4],
        index=pd.Index(["a", "b", "c"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_contract_bundle_negation_flips_signs() -> None:
    bundle = ContractBundle.from_dict({"a": 2, "b": -1})

    result = -bundle

    expected = pd.Series(
        [-2, 1],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_contract_bundle_addition_prunes_resulting_zero_entries() -> None:
    left = ContractBundle.from_dict({"a": 2, "b": -1})
    right = ContractBundle.from_dict({"a": -2, "b": 1})

    result = left + right

    expected = pd.Series(dtype="int64", index=pd.Index([], name="contract_id"))

    assert result.is_empty()
    pdt.assert_series_equal(result.quantities, expected)


def test_target_contract_bundle_addition_preserves_fractional_values() -> None:
    left = TargetContractBundle.from_dict({"a": 0.25, "b": -1.5})
    right = TargetContractBundle.from_dict({"b": 0.5, "c": 2.25})

    result = left + right

    expected = pd.Series(
        [0.25, -1.0, 2.25],
        index=pd.Index(["a", "b", "c"], name="contract_id"),
        dtype="float64",
    )

    pdt.assert_series_equal(result.quantities, expected)


def test_mixed_bundle_arithmetic_raises_type_error() -> None:
    left = ContractBundle.from_dict({"a": 1})
    right = TargetContractBundle.from_dict({"a": 1.0})

    with pytest.raises(TypeError, match="matching bundle types"):
        _ = left + right


def test_contract_bundle_equality_is_based_on_canonical_form() -> None:
    left = ContractBundle.from_dict({"b": -1, "a": 2, "c": 0})
    right = ContractBundle(
        pd.Series(
            [2.0, -1.0],
            index=pd.Index(["a", "b"], name="other_name"),
        )
    )

    assert left == right


def test_target_contract_bundle_equality_is_based_on_canonical_form() -> None:
    left = TargetContractBundle.from_dict({"b": -1.0, "a": 2.5, "c": 0.0})
    right = TargetContractBundle(
        pd.Series(
            [2.5, -1.0],
            index=pd.Index(["a", "b"], name="different_name"),
        )
    )

    assert left == right


def test_bundles_with_same_quantities_but_different_concrete_types_are_not_equal() -> (
    None
):
    realised = ContractBundle.from_dict({"a": 1})
    target = TargetContractBundle.from_dict({"a": 1.0})

    assert realised != target


def test_quantities_property_returns_defensive_copy() -> None:
    bundle = ContractBundle.from_dict({"a": 2, "b": -1})

    external = bundle.quantities
    external.loc["a"] = 999

    expected = pd.Series(
        [2, -1],
        index=pd.Index(["a", "b"], name="contract_id"),
        dtype="int64",
    )

    pdt.assert_series_equal(bundle.quantities, expected)
