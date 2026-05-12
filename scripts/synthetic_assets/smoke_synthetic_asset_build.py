"""
Smoke script: build and inspect a realised SyntheticAsset.

Usage:

    poetry run python scripts/synthetic_assets/smoke_synthetic_asset_build.py \
        --asset-id <asset_id> \
        --start 2025-01-02 \
        --end 2025-02-28

Optional overrides:

    poetry run python scripts/synthetic_assets/smoke_synthetic_asset_build.py \
        --asset-id <asset_id> \
        --start 2025-01-02 \
        --end 2025-02-28 \
        --mxm-business-calendar-id mxm_v1_business

This is a human inspection tool, not a regression test.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd

from mxm.refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)
from mxm.v1.calendars.mxm_business_calendar_service import MXMBusinessCalendarService
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.runtime import (
    SyntheticAsset,
    build_synthetic_asset,
)
from mxm.v1.synthetic_assets.spec_registry import SyntheticAssetSpecRegistry
from mxm.v1.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)
from mxm.v1.synthetic_assets.unit_conversion import build_default_unit_converter

# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------

DEFAULT_MXM_BUSINESS_CALENDAR_ID = "mxm_v1_business"

# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke SyntheticAsset build")

    p.add_argument("--asset-id", required=True)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")
    p.add_argument(
        "--registry-root",
        default=None,
        help="Synthetic asset registry root (default: ~/.mxm)",
    )
    p.add_argument(
        "--max-head",
        type=int,
        default=10,
        help="Number of head rows to print per section (default: 10)",
    )
    p.add_argument(
        "--max-active",
        type=int,
        default=50,
        help="Maximum number of active holdings rows to print (default: 50)",
    )
    p.add_argument(
        "--mxm-business-calendar-id",
        default=DEFAULT_MXM_BUSINESS_CALENDAR_ID,
        help=(
            "Runtime id assigned to the MXM business calendar "
            f"(default: {DEFAULT_MXM_BUSINESS_CALENDAR_ID})"
        ),
    )

    return p.parse_args(argv)


# ---------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------


def _print_spec_summary(spec: SyntheticAssetSpec) -> None:
    print("=" * 72)
    print("SyntheticAssetSpec")
    print(f"asset_id:       {spec.asset_id}")
    print(f"canonical_id:   {spec.canonical_id}")
    print(f"currency:       {spec.currency}")
    print(f"unit:           {spec.unit}")
    print(f"size:           {spec.size}")
    print(f"weights_rule:   {spec.weights_rule_id}")
    print("=" * 72)
    print()
    print("Component bindings")
    for component_id, component in spec.components.items():
        print(
            f"  {component_id:>10s} -> product_id={component.product_id}  "
            f"selector_rule_id={component.selector_rule_id}"
        )
    print()


def _print_frame_head(title: str, frame: pd.DataFrame, max_head: int) -> None:
    print(title)
    if frame.empty:
        print("  <empty>")
        print()
        return

    head = frame.head(max_head)
    print(head.to_string())
    print()


def _active_holdings_mask(frame: pd.DataFrame, *, atol: float = 1e-12) -> np.ndarray:
    """
    Return mask for rows with materially non-zero target holdings.
    """
    values = frame["target_holding"].to_numpy(dtype=float)
    return np.abs(values) > atol


def _print_active_target_holdings(
    *,
    frame: pd.DataFrame,
    max_active: int,
) -> None:
    print("Active target holdings rows")
    if frame.empty:
        print("  <empty>")
        print()
        return

    mask = _active_holdings_mask(frame)
    active = frame.loc[mask]

    print(f"  count: {len(active)}")
    if active.empty:
        print("  <none>")
        print()
        return

    print(active.head(max_active).to_string())
    if len(active) > max_active:
        print(f"  ... truncated after {max_active} rows")
    print()


def _print_invariants(asset: SyntheticAsset) -> None:
    print("Invariants")

    cc = asset.component_contracts.frame
    cw = asset.component_weights.frame
    th = asset.target_holdings.frame

    print(f"  component_contracts rows: {len(cc)}")
    print(f"  component_weights rows:   {len(cw)}")
    print(f"  target_holdings rows:     {len(th)}")

    print(f"  session index aligned:    {cc.index.equals(cw.index)}")
    print(f"  component columns aligned:{list(cc.columns) == list(cw.columns)}")

    print(f"  first session:            {cc.index[0] if len(cc.index) else '<empty>'}")
    print(f"  last session:             {cc.index[-1] if len(cc.index) else '<empty>'}")

    print()


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    asset_id = args.asset_id
    start = np.datetime64(args.start)
    end = np.datetime64(args.end)

    # --- Build real services ---
    refdata = RefDataAPI()
    calendars = TradingCalendarService(refdata_api=refdata)
    engine = ContractSelectorEngine.build(refdata=refdata, calendars=calendars)
    unit_converter = build_default_unit_converter()

    mxm_business_calendar_service = MXMBusinessCalendarService(
        calendar_id=args.mxm_business_calendar_id,
        start_label=start,
        end_label=end,
    )
    mxm_business_calendar = mxm_business_calendar_service.get_calendar()

    # --- Load real synthetic asset spec ---
    if args.registry_root is not None:
        layout = SyntheticAssetSpecRegistryLayout(root=Path(args.registry_root))
    else:
        layout = SyntheticAssetSpecRegistryLayout(root=Path.home() / ".mxm")

    registry = SyntheticAssetSpecRegistry(layout=layout)
    spec = registry.load(asset_id=asset_id)

    _print_spec_summary(spec)

    print("Build range")
    print(f"  start: {start}")
    print(f"  end:   {end}")
    print()

    print("MXM business calendar")
    print(f"  calendar_id: {mxm_business_calendar.calendar_id}")
    print(f"  first_label: {mxm_business_calendar.labels[0]}")
    print(f"  last_label:  {mxm_business_calendar.labels[-1]}")
    print(f"  sessions:    {len(mxm_business_calendar)}")
    print()

    asset = build_synthetic_asset(
        spec=spec,
        start_session=start,
        end_session=end,
        engine=engine,
        calendar_service=calendars,
        mxm_business_calendar=mxm_business_calendar,
        refdata_api=refdata,
        unit_converter=unit_converter,
    )

    _print_frame_head(
        "ComponentContracts (head)",
        asset.component_contracts.frame,
        args.max_head,
    )

    _print_frame_head(
        "ComponentWeights (head)",
        asset.component_weights.frame,
        args.max_head,
    )

    _print_frame_head(
        "TargetHoldings (head)",
        asset.target_holdings.frame,
        args.max_head,
    )

    _print_active_target_holdings(
        frame=asset.target_holdings.frame,
        max_active=args.max_active,
    )

    _print_invariants(asset)

    print("=" * 72)
    print("Done.")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
