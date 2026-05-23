from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SyntheticAssetSpecRegistryLayout:
    """
    Filesystem layout for the MXM V1 SyntheticAssetSpec registry.

    This layout is V1-local and intentionally minimal.

    Layout principles (V1):
    - registry stores *static instrument definitions* only (SyntheticAssetSpec)
    - one YAML file per asset_id for auditability and simple discovery
    - role-bound legs and weights_rule_id live in the spec file
    - no derived time-series artefacts (weights/holdings/trades) stored here

    Directory structure (relative to root):
        synthetic_assets/
          spec_registry/
            assets/
              <asset_id>.yaml
    """

    root: Path

    # -------------------------
    # Registry root dirs
    # -------------------------

    def registry_dir(self) -> Path:
        return self.root / "synthetic_assets" / "spec_registry"

    def assets_dir(self) -> Path:
        return self.registry_dir() / "assets"

    # -------------------------
    # Asset spec paths
    # -------------------------

    def asset_spec_path(self, *, asset_id: str) -> Path:
        """
        Path to the YAML spec file for a given asset_id.

        The caller is responsible for ensuring asset_id is canonical.
        """
        return self.assets_dir() / f"{asset_id}.yaml"

    def tmp_asset_spec_path(self, *, asset_id: str) -> Path:
        """
        Temporary path used by writers/generators to stage atomic updates.

        Registry readers should never read from tmp paths.
        """
        return self.assets_dir() / f"{asset_id}.tmp.yaml"
