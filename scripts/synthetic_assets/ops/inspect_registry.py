from __future__ import annotations

import argparse
import json
from pathlib import Path

from mxm.moneymachine.synthetic_assets.spec_registry import SyntheticAssetSpecRegistry
from mxm.moneymachine.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)


def default_registry_layout() -> SyntheticAssetSpecRegistryLayout:
    return SyntheticAssetSpecRegistryLayout(root=Path.home() / ".mxm")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--registry-root", default=None)
    ap.add_argument("--head", type=int, default=25)
    ap.add_argument("--asset-id", default=None, help="Load and print one spec")
    args = ap.parse_args()

    if args.registry_root is not None:
        layout = SyntheticAssetSpecRegistryLayout(root=Path(args.registry_root))
    else:
        layout = default_registry_layout()

    reg = SyntheticAssetSpecRegistry(layout=layout)

    asset_ids = reg.list_asset_ids()
    print(f"registry: {layout.assets_dir()}")
    print(f"count: {len(asset_ids)}")

    if args.asset_id is None:
        for a in asset_ids[: args.head]:
            print(a)
        if len(asset_ids) > args.head:
            print(f"... ({len(asset_ids) - args.head} more)")
        return 0

    spec = reg.load(asset_id=args.asset_id)

    # Prefer JSON-ish print because it is stable and greppable.
    doc = {
        "asset_id": spec.asset_id,
        "canonical_id": spec.canonical_id,
        "currency": spec.currency,
        "unit": spec.unit,
        "size": spec.size,
        "weights_rule_id": spec.weights_rule_id,
        "legs": {
            k: {"product_id": v.product_id, "selector_rule_id": v.selector_rule_id}
            for k, v in spec.legs.items()
        },
    }
    print(json.dumps(doc, indent=2, sort_keys=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
