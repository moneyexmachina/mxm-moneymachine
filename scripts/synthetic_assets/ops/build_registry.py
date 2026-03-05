from __future__ import annotations

import argparse
from pathlib import Path

from mxm_refdata.api.ref_data_api import RefDataAPI

from mxm.v1.synthetic_assets.construction_policy import v1_policy
from mxm.v1.synthetic_assets.policy_compile import compile_specs_from_policy
from mxm.v1.synthetic_assets.spec_registry import SyntheticAssetSpecRegistry
from mxm.v1.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)


def default_registry_layout() -> SyntheticAssetSpecRegistryLayout:
    return SyntheticAssetSpecRegistryLayout(root=Path.home() / ".mxm")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--product-id", default=None)
    ap.add_argument("--registry-root", default=None)
    args = ap.parse_args()

    # ------------------------------------------------------------------
    # Products (authoritative)
    # ------------------------------------------------------------------
    ref_api = RefDataAPI()
    products = list(ref_api.get_all_products())
    if not products:
        raise ValueError("No products returned by RefDataAPI.get_all_products()")

    if args.product_id is not None:
        products = [p for p in products if p.product_id == args.product_id]
        if not products:
            raise ValueError(f"Unknown/filtered-out product_id={args.product_id!r}")

    # ------------------------------------------------------------------
    # Policy + compile
    # ------------------------------------------------------------------
    policy = v1_policy(product_ids=[p.product_id for p in products])
    specs = compile_specs_from_policy(products=products, policy=policy)

    # ------------------------------------------------------------------
    # Registry
    # ------------------------------------------------------------------
    if args.registry_root is not None:
        layout = SyntheticAssetSpecRegistryLayout(root=Path(args.registry_root))
    else:
        layout = default_registry_layout()

    registry = SyntheticAssetSpecRegistry(layout=layout)

    # ------------------------------------------------------------------
    # Save / Dry-run
    # ------------------------------------------------------------------
    for s in specs:
        if args.dry_run:
            print(f"[DRY RUN] {s.asset_id}")
        else:
            registry.save(spec=s, overwrite=args.overwrite)
            print(f"[SAVED] {s.asset_id}")

    print(f"done: {len(specs)} specs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
