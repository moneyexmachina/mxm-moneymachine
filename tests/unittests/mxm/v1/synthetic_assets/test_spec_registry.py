# tests/unittests/mxm/v1/synthetic_assets/test_spec_registry.py
from __future__ import annotations

from pathlib import Path

import pytest

from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.spec_registry import (
    SyntheticAssetSpecRegistry,
    SyntheticAssetSpecSchemaError,
    load_synthetic_asset_spec,
)
from mxm.v1.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)

# A canonical id string that should satisfy structural validation for CONT.
_CANON_CONT = (
    "SA::KIND=CONT"
    "::P0=cme_emini_snp500_futures"
    "::CUR=RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1"
    "::NXT=RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=2"
    "::WR=roll.linear.ltd_end.window_5"
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_load_synthetic_asset_spec_minimal_ok(tmp_path: Path) -> None:
    p = tmp_path / "asset.yaml"
    _write(
        p,
        f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
  m2:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.second
""".lstrip(),
    )

    spec = load_synthetic_asset_spec(p)
    assert spec.asset_id == "cme_es_front"
    assert spec.canonical_id.startswith("SA::KIND=CONT")
    assert spec.currency == "USD"
    assert spec.unit == "contract"
    assert spec.size == 1000
    assert spec.weights_rule_id == "roll.linear.ltd_end.window_5"
    assert set(spec.legs.keys()) == {"m1", "m2"}
    assert spec.legs["m1"].product_id == "cme_emini_snp500_futures"
    assert spec.legs["m1"].selector_rule_id == "cme_emini_snp500_futures.front"


def test_load_synthetic_asset_spec_missing_canonical_id_schema_error(
    tmp_path: Path,
) -> None:
    p = tmp_path / "missing_canonical_id.yaml"
    _write(
        p,
        """
asset_id: cme_es_front
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
""".lstrip(),
    )

    with pytest.raises(SyntheticAssetSpecSchemaError) as e:
        _ = load_synthetic_asset_spec(p)

    assert "canonical_id" in str(e.value)


def test_load_synthetic_asset_spec_invalid_canonical_id_fails_model_validation(
    tmp_path: Path,
) -> None:
    p = tmp_path / "bad_canonical_id.yaml"
    _write(
        p,
        """
asset_id: cme_es_front
canonical_id: "SA::KIND=CONT::P0=x::WR=w"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
  m2:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.second
""".lstrip(),
    )

    # Should fail in SyntheticAssetSpec.__post_init__ via validate_synthetic_asset_canonical_id.
    with pytest.raises(ValueError):
        _ = load_synthetic_asset_spec(p)


@pytest.mark.parametrize(
    "bad_yaml, expected_substr",
    [
        # Missing required top-level field (currency)
        (
            f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
""".lstrip(),
            "currency",
        ),
        # legs missing
        (
            f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
""".lstrip(),
            "root.legs is required",
        ),
        # legs not an object
        (
            f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs: []
""".lstrip(),
            "root.legs must be a JSON object",
        ),
        # leg missing required field
        (
            f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
""".lstrip(),
            "selector_rule_id",
        ),
    ],
)
def test_load_synthetic_asset_spec_schema_errors(
    tmp_path: Path, bad_yaml: str, expected_substr: str
) -> None:
    p = tmp_path / "bad.yaml"
    _write(p, bad_yaml)

    with pytest.raises(SyntheticAssetSpecSchemaError) as e:
        _ = load_synthetic_asset_spec(p)

    assert expected_substr in str(e.value)


def test_load_synthetic_asset_spec_invalid_asset_id_fails_model_validation(
    tmp_path: Path,
) -> None:
    p = tmp_path / "bad_asset_id.yaml"
    _write(
        p,
        f"""
asset_id: CME-ES-FRONT
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
""".lstrip(),
    )

    with pytest.raises(ValueError):
        _ = load_synthetic_asset_spec(p)


def test_load_synthetic_asset_spec_invalid_role_key_fails_model_validation(
    tmp_path: Path,
) -> None:
    p = tmp_path / "bad_role.yaml"
    _write(
        p,
        f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  M1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
""".lstrip(),
    )

    with pytest.raises(ValueError):
        _ = load_synthetic_asset_spec(p)


def test_load_synthetic_asset_spec_rejects_non_json_yaml_types(tmp_path: Path) -> None:
    p = tmp_path / "timestamp.yaml"
    _write(
        p,
        f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
# YAML timestamp-like value: safe_load may materialise a date/datetime object.
metadata:
  created: 2020-01-01
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
""".lstrip(),
    )

    with pytest.raises(SyntheticAssetSpecSchemaError) as e:
        _ = load_synthetic_asset_spec(p)

    msg = str(e.value)
    assert "timestamp.yaml" in msg
    assert (
        "JSON" in msg
        or "serial" in msg
        or "not JSON" in msg
        or "not JSON-serialisable" in msg
    )


def test_spec_registry_list_asset_ids_empty_when_assets_dir_missing(
    tmp_path: Path,
) -> None:
    layout = SyntheticAssetSpecRegistryLayout(root=tmp_path)
    reg = SyntheticAssetSpecRegistry(layout=layout)
    assert reg.list_asset_ids() == []


def test_spec_registry_list_and_load(tmp_path: Path) -> None:
    layout = SyntheticAssetSpecRegistryLayout(root=tmp_path)
    reg = SyntheticAssetSpecRegistry(layout=layout)

    _write(
        layout.asset_spec_path(asset_id="cme_es_front"),
        f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
  m2:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.second
""".lstrip(),
    )

    _write(
        layout.asset_spec_path(asset_id="cme_nq_front"),
        f"""
asset_id: cme_nq_front
canonical_id: "SA::KIND=CONT::P0=cme_emini_nasdaq_futures::CUR=RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=1::NXT=RC::PT=MONTH::CYCLE=NONE::RANK=LTD::N=2::WR=roll.linear.ltd_end.window_5"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_nasdaq_futures
    selector_rule_id: cme_emini_nasdaq_futures.front
  m2:
    product_id: cme_emini_nasdaq_futures
    selector_rule_id: cme_emini_nasdaq_futures.second
""".lstrip(),
    )

    _write(layout.tmp_asset_spec_path(asset_id="ignore_me"), "asset_id: ignore_me\n")

    ids = reg.list_asset_ids()
    assert ids == ["cme_es_front", "cme_nq_front"]

    spec = reg.load(asset_id="cme_es_front")
    assert spec.asset_id == "cme_es_front"
    assert spec.canonical_id.startswith("SA::KIND=CONT")
    assert spec.legs["m1"].selector_rule_id.endswith(".front")


def test_spec_registry_load_missing_asset_raises_filenotfound(tmp_path: Path) -> None:
    layout = SyntheticAssetSpecRegistryLayout(root=tmp_path)
    reg = SyntheticAssetSpecRegistry(layout=layout)

    with pytest.raises(FileNotFoundError):
        _ = reg.load(asset_id="does_not_exist")


def test_spec_registry_save_round_trip(tmp_path: Path) -> None:
    layout = SyntheticAssetSpecRegistryLayout(root=tmp_path)
    reg = SyntheticAssetSpecRegistry(layout=layout)

    # Start from a YAML-loaded spec so we do not depend on direct dataclass construction
    # details here (and we reuse the existing minimal fixture shape).
    p = tmp_path / "seed.yaml"
    _write(
        p,
        f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
  m2:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.second
""".lstrip(),
    )

    spec = load_synthetic_asset_spec(p)

    out_path = reg.save(spec=spec)
    assert out_path == layout.asset_spec_path(asset_id="cme_es_front")
    assert out_path.exists()

    loaded = reg.load(asset_id="cme_es_front")
    assert loaded.asset_id == spec.asset_id
    assert loaded.canonical_id == spec.canonical_id
    assert loaded.currency == spec.currency
    assert loaded.unit == spec.unit
    assert loaded.weights_rule_id == spec.weights_rule_id
    assert set(loaded.legs.keys()) == set(spec.legs.keys())
    for role, leg in spec.legs.items():
        assert loaded.legs[role].product_id == leg.product_id
        assert loaded.legs[role].selector_rule_id == leg.selector_rule_id


def test_spec_registry_save_refuses_overwrite_by_default(tmp_path: Path) -> None:
    layout = SyntheticAssetSpecRegistryLayout(root=tmp_path)
    reg = SyntheticAssetSpecRegistry(layout=layout)

    p = tmp_path / "seed.yaml"
    _write(
        p,
        f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
""".lstrip(),
    )
    spec = load_synthetic_asset_spec(p)

    _ = reg.save(spec=spec)
    with pytest.raises(FileExistsError):
        _ = reg.save(spec=spec, overwrite=False)


def test_spec_registry_save_overwrite_true_replaces(tmp_path: Path) -> None:
    layout = SyntheticAssetSpecRegistryLayout(root=tmp_path)
    reg = SyntheticAssetSpecRegistry(layout=layout)

    p = tmp_path / "seed.yaml"
    _write(
        p,
        f"""
asset_id: cme_es_front
canonical_id: "{_CANON_CONT}"
currency: USD
unit: contract
size: 1000
weights_rule_id: roll.linear.ltd_end.window_5
legs:
  m1:
    product_id: cme_emini_snp500_futures
    selector_rule_id: cme_emini_snp500_futures.front
""".lstrip(),
    )
    spec1 = load_synthetic_asset_spec(p)

    _ = reg.save(spec=spec1)

    # Modify one field (weights_rule_id) and save with overwrite=True.
    # We keep canonical_id unchanged here because this test is about overwrite mechanics,
    # not canonical-id consistency policies.
    spec2 = SyntheticAssetSpec(
        asset_id=spec1.asset_id,
        canonical_id=spec1.canonical_id,
        currency=spec1.currency,
        unit=spec1.unit,
        size=spec1.size,
        weights_rule_id="roll.linear.ltd_end.window_10",
        legs=spec1.legs,
    )

    _ = reg.save(spec=spec2, overwrite=True)
    loaded = reg.load(asset_id="cme_es_front")
    assert loaded.weights_rule_id == "roll.linear.ltd_end.window_10"

    # Optional hygiene: tmp file should not remain after save.
    assert not layout.tmp_asset_spec_path(asset_id="cme_es_front").exists()
