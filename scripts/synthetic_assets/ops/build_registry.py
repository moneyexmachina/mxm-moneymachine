from __future__ import annotations

import argparse
from pathlib import Path

from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.refdata.models.products.futures_product import FuturesProduct
from mxm.v1.synthetic_assets.construction_policy import v1_policy
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.policy_compile import compile_specs_from_policy
from mxm.v1.synthetic_assets.spec_registry import SyntheticAssetSpecRegistry
from mxm.v1.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)


def default_registry_layout() -> SyntheticAssetSpecRegistryLayout:
    return SyntheticAssetSpecRegistryLayout(root=Path.home() / ".mxm")


def main() -> int:
    args = _parse_args()
    _validate_args(args)

    products = _load_products(product_id=args.product_id)
    specs = _compile_specs(products)
    layout = _make_registry_layout(args.registry_root)
    registry = SyntheticAssetSpecRegistry(layout=layout)

    if args.dry_run:
        _print_dry_run(
            specs=specs,
            registry=registry,
            prune=bool(args.prune),
        )
        return 0

    if args.prune:
        _prune_stale_specs(
            registry=registry,
            layout=layout,
            compiled_ids={spec.asset_id for spec in specs},
        )

    _save_specs(
        registry=registry,
        specs=specs,
        overwrite=bool(args.overwrite or args.prune),
    )

    print(f"done: {len(specs)} specs")
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--prune",
        action="store_true",
        help=(
            "Remove registry entries not present in the current compiled spec set. "
            "For safety, this cannot be used together with --product-id."
        ),
    )
    parser.add_argument("--product-id", default=None)
    parser.add_argument("--registry-root", default=None)
    return parser.parse_args()


def _validate_args(args: argparse.Namespace) -> None:
    if args.prune and args.product_id is not None:
        raise ValueError("--prune cannot be used together with --product-id")


def _load_products(*, product_id: str | None) -> list[FuturesProduct]:
    ref_api = RefDataAPI()
    products = list(ref_api.get_all_products())

    if not products:
        raise ValueError("No products returned by RefDataAPI.get_all_products()")

    if product_id is None:
        return products

    filtered = [product for product in products if product.product_id == product_id]

    if not filtered:
        raise ValueError(f"Unknown/filtered-out product_id={product_id!r}")

    return filtered


def _compile_specs(products: list[FuturesProduct]) -> list[SyntheticAssetSpec]:
    policy = v1_policy(product_ids=[product.product_id for product in products])
    return list(compile_specs_from_policy(products=products, policy=policy))


def _make_registry_layout(
    registry_root: str | None,
) -> SyntheticAssetSpecRegistryLayout:
    if registry_root is not None:
        return SyntheticAssetSpecRegistryLayout(root=Path(registry_root))

    return default_registry_layout()


def _print_dry_run(
    *,
    specs: list[SyntheticAssetSpec],
    registry: SyntheticAssetSpecRegistry,
    prune: bool,
) -> None:
    compiled_ids = {spec.asset_id for spec in specs}

    print(f"[DRY RUN] compiled specs: {len(specs)}")
    for spec in specs:
        print(f"[DRY RUN] SAVE   {spec.asset_id}")

    if prune:
        stale_ids = _find_stale_asset_ids(
            registry=registry,
            compiled_ids=compiled_ids,
        )
        print(f"[DRY RUN] prune stale specs: {len(stale_ids)}")
        for asset_id in stale_ids:
            print(f"[DRY RUN] REMOVE {asset_id}")

    print(f"done: {len(specs)} specs")


def _find_stale_asset_ids(
    *,
    registry: SyntheticAssetSpecRegistry,
    compiled_ids: set[str],
) -> list[str]:
    existing_ids = set(registry.list_asset_ids())
    return sorted(existing_ids - compiled_ids)


def _prune_stale_specs(
    *,
    registry: SyntheticAssetSpecRegistry,
    layout: SyntheticAssetSpecRegistryLayout,
    compiled_ids: set[str],
) -> None:
    stale_ids = _find_stale_asset_ids(
        registry=registry,
        compiled_ids=compiled_ids,
    )

    for asset_id in stale_ids:
        path = layout.asset_spec_path(asset_id=asset_id)
        if path.exists():
            path.unlink()
            print(f"[REMOVED] {asset_id}")


def _save_specs(
    *,
    registry: SyntheticAssetSpecRegistry,
    specs: list[SyntheticAssetSpec],
    overwrite: bool,
) -> None:
    for spec in specs:
        registry.save(spec=spec, overwrite=overwrite)
        print(f"[SAVED] {spec.asset_id}")


if __name__ == "__main__":
    raise SystemExit(main())
