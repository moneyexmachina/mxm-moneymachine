# scripts/synthetic_assets/ops/synthetic_asset_spec_inspect.py
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from mxm.v1.synthetic_assets.spec_registry import SyntheticAssetSpecRegistry
from mxm.v1.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)


def _default_root() -> Path:
    # Keep this simple for Session 24.
    # Users can override with --root.
    return Path.home() / ".mxm"


def _spec_to_dict(spec: Any) -> dict[str, Any]:
    # Avoid introducing a to_dict() contract in Session 24.
    # Keep output stable and explicit.
    legs: dict[str, dict[str, str]] = {}
    for role in sorted(spec.legs.keys()):
        leg = spec.legs[role]
        legs[role] = {
            "product_id": leg.product_id,
            "selector_rule_id": leg.selector_rule_id,
        }

    return {
        "asset_id": spec.asset_id,
        "currency": spec.currency,
        "unit": spec.unit,
        "weights_rule_id": spec.weights_rule_id,
        "legs": legs,
    }


def cmd_list(*, registry: SyntheticAssetSpecRegistry) -> int:
    for asset_id in registry.list_asset_ids():
        print(asset_id)
    return 0


def cmd_show(*, registry: SyntheticAssetSpecRegistry, asset_id: str) -> int:
    spec = registry.load(asset_id=asset_id)
    d = _spec_to_dict(spec)
    print(json.dumps(d, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="synthetic_asset_spec_inspect",
        description="Inspect MXM V1 SyntheticAssetSpec definitions (spec registry).",
    )
    p.add_argument(
        "--root",
        type=Path,
        default=_default_root(),
        help="MXM root directory (default: ~/.mxm).",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="List available synthetic asset specs.")

    p_show = sub.add_parser("show", help="Show one synthetic asset spec as JSON.")
    p_show.add_argument("--asset-id", required=True, help="Synthetic asset id.")

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    layout = SyntheticAssetSpecRegistryLayout(root=args.root)
    registry = SyntheticAssetSpecRegistry(layout=layout)

    if args.cmd == "list":
        return cmd_list(registry=registry)

    if args.cmd == "show":
        return cmd_show(registry=registry, asset_id=args.asset_id)

    raise RuntimeError(f"Unhandled command: {args.cmd!r}")


if __name__ == "__main__":
    raise SystemExit(main())
