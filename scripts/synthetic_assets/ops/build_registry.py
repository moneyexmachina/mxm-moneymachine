from __future__ import annotations

import argparse
from pathlib import Path

from mxm.refdata.api.ref_data_api import RefDataAPI
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
    ap.add_argument(
        "--prune",
        action="store_true",
        help=(
            "Remove registry entries not present in the current compiled spec set. "
            "For safety, this cannot be used together with --product-id."
        ),
    )
    ap.add_argument("--product-id", default=None)
    ap.add_argument("--registry-root", default=None)
    args = ap.parse_args()

    if args.prune and args.product_id is not None:
        raise ValueError("--prune cannot be used together with --product-id")

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

    compiled_ids = {s.asset_id for s in specs}

    # ------------------------------------------------------------------
    # Dry-run
    # ------------------------------------------------------------------
    if args.dry_run:
        print(f"[DRY RUN] compiled specs: {len(specs)}")
        for s in specs:
            print(f"[DRY RUN] SAVE   {s.asset_id}")

        if args.prune:
            existing_ids = set(registry.list_asset_ids())
            stale_ids = sorted(existing_ids - compiled_ids)
            print(f"[DRY RUN] prune stale specs: {len(stale_ids)}")
            for asset_id in stale_ids:
                print(f"[DRY RUN] REMOVE {asset_id}")

        print(f"done: {len(specs)} specs")
        return 0

    # ------------------------------------------------------------------
    # Optional prune
    # ------------------------------------------------------------------
    if args.prune:
        existing_ids = set(registry.list_asset_ids())
        stale_ids = sorted(existing_ids - compiled_ids)

        for asset_id in stale_ids:
            path = layout.asset_spec_path(asset_id=asset_id)
            if path.exists():
                path.unlink()
                print(f"[REMOVED] {asset_id}")

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------
    for s in specs:
        registry.save(spec=s, overwrite=args.overwrite or args.prune)
        print(f"[SAVED] {s.asset_id}")

    print(f"done: {len(specs)} specs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
