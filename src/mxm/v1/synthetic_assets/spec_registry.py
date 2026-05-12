from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from mxm.types import JSONObj, JSONValue
from mxm.v1.synthetic_assets.models import ComponentBinding, SyntheticAssetSpec
from mxm.v1.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)
from mxm.v1.utils.json_normalise import JSONNormaliseError, json_value_from_obj


class SyntheticAssetSpecSchemaError(ValueError):
    pass


def _as_obj(v: JSONValue, *, field: str) -> JSONObj:
    if not isinstance(v, dict):
        raise SyntheticAssetSpecSchemaError(f"{field} must be a JSON object")
    return v


def _get_str(d: JSONObj, key: str, *, field: str) -> str:
    v = d.get(key)
    if not isinstance(v, str):
        raise SyntheticAssetSpecSchemaError(f"{field}.{key} must be a str")
    return v


def _get_number(d: JSONObj, key: str, *, field: str) -> float:
    v = d.get(key)
    # YAML numbers load as int/float; JSON normaliser preserves numeric types.
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise SyntheticAssetSpecSchemaError(f"{field}.{key} must be a number")
    return float(v)


def save_synthetic_asset_spec(
    *,
    spec: SyntheticAssetSpec,
    layout: SyntheticAssetSpecRegistryLayout,
    overwrite: bool = False,
) -> Path:
    """
    Save a SyntheticAssetSpec into the spec registry as YAML.

    Semantics:
    - One file per asset_id: <assets_dir>/<asset_id>.yaml
    - Writes via a temporary file and atomic rename.
    - Deterministic key ordering and role ordering for stable diffs.

    Args:
        spec: The validated SyntheticAssetSpec to write.
        layout: Registry layout defining filesystem locations.
        overwrite: If False, raise FileExistsError when the target file exists.

    Returns:
        Path to the written YAML file.

    Raises:
        FileExistsError: if target exists and overwrite is False.
        OSError: on filesystem failures.
    """
    assets_dir = layout.assets_dir()
    assets_dir.mkdir(parents=True, exist_ok=True)

    dst = layout.asset_spec_path(asset_id=spec.asset_id)
    tmp = layout.tmp_asset_spec_path(asset_id=spec.asset_id)

    if dst.exists() and not overwrite:
        raise FileExistsError(f"Spec already exists at {dst} (overwrite=False)")

    components_out: dict[str, dict[str, str]] = {}
    for component_id in sorted(spec.components.keys()):
        component = spec.components[component_id]
        components_out[component_id] = {
            "product_id": component.product_id,
            "selector_rule_id": component.selector_rule_id,
        }

    doc: dict[str, object] = {
        "asset_id": spec.asset_id,
        "canonical_id": spec.canonical_id,
        "currency": spec.currency,
        "unit": spec.unit,
        "size": spec.size,
        "weights_rule_id": spec.weights_rule_id,
        "components": components_out,
    }

    yml = yaml.safe_dump(
        doc,
        sort_keys=False,
        default_flow_style=False,
        allow_unicode=True,
    )

    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(yml, encoding="utf-8")

    tmp.replace(dst)
    return dst


def load_synthetic_asset_spec(path: Path) -> SyntheticAssetSpec:
    raw: object = yaml.safe_load(path.read_text(encoding="utf-8"))
    try:
        root_val: JSONValue = json_value_from_obj(raw)
    except JSONNormaliseError as e:
        raise SyntheticAssetSpecSchemaError(f"{path}: {e}") from e

    root = _as_obj(root_val, field="root")

    asset_id = _get_str(root, "asset_id", field="root")
    canonical_id = _get_str(root, "canonical_id", field="root")
    currency = _get_str(root, "currency", field="root")
    unit = _get_str(root, "unit", field="root")
    size = _get_number(root, "size", field="size")
    weights_rule_id = _get_str(root, "weights_rule_id", field="root")

    components_val = root.get("components")
    if components_val is None:
        raise SyntheticAssetSpecSchemaError("root.components is required")

    components_obj = _as_obj(components_val, field="root.components")

    components: dict[str, ComponentBinding] = {}
    for component_id, component_val in components_obj.items():
        # component_id is already str by construction of JSONValue (dict[str, JSONValue])
        component_obj = _as_obj(
            component_val, field=f"root.components[{component_id!r}]"
        )
        product_id = _get_str(
            component_obj, "product_id", field=f"root.components[{component_id!r}]"
        )
        selector_rule_id = _get_str(
            component_obj,
            "selector_rule_id",
            field=f"root.components[{component_id!r}]",
        )
        components[component_id] = ComponentBinding(
            product_id=product_id, selector_rule_id=selector_rule_id
        )

    return SyntheticAssetSpec(
        asset_id=asset_id,
        canonical_id=canonical_id,
        currency=currency,
        unit=unit,
        size=size,
        weights_rule_id=weights_rule_id,
        components=components,
    )


@dataclass(frozen=True)
class SyntheticAssetSpecRegistry:
    """
    Read-only registry for SyntheticAssetSpec definitions.

    This registry is filesystem-backed and loads one YAML file per asset_id.
    It manages only static SyntheticAssetSpec definitions (no time-series artefacts).
    """

    layout: SyntheticAssetSpecRegistryLayout

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def list_asset_ids(self) -> list[str]:
        """
        Return sorted list of available asset_ids.

        Ignores temporary (*.tmp.yaml) files.
        """
        assets_dir = self.layout.assets_dir()
        if not assets_dir.exists():
            return []

        ids: list[str] = []
        for p in assets_dir.glob("*.yaml"):
            if p.name.endswith(".tmp.yaml"):
                continue
            ids.append(p.stem)

        ids.sort()
        return ids

    # ------------------------------------------------------------------
    # Access
    # ------------------------------------------------------------------

    def spec_path(self, *, asset_id: str) -> Path:
        """
        Return the filesystem path to the spec YAML for a given asset_id.
        """
        return self.layout.asset_spec_path(asset_id=asset_id)

    def load(self, *, asset_id: str) -> SyntheticAssetSpec:
        """
        Load and validate the SyntheticAssetSpec for the given asset_id.

        Raises:
            FileNotFoundError
            SyntheticAssetSpecSchemaError
            ValueError (model-level validation failures)
        """
        path = self.spec_path(asset_id=asset_id)
        if not path.exists():
            raise FileNotFoundError(
                f"SyntheticAssetSpec not found for asset_id={asset_id!r} at {path}"
            )

        return load_synthetic_asset_spec(path)

    def save(self, *, spec: SyntheticAssetSpec, overwrite: bool = False) -> Path:
        return save_synthetic_asset_spec(
            spec=spec, layout=self.layout, overwrite=overwrite
        )
