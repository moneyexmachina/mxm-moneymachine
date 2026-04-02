from __future__ import annotations

"""
Smoke script: build and inspect realised ComponentWeights for a SyntheticAsset.

Usage:

    poetry run python scripts/synthetic_assets/smoke_component_weights.py \
        --asset-id <asset_id> \
        --start 2025-01-02 \
        --end 2025-02-28
 example asset_id: cme_emini_snp500_futures_cont_hmuz1_wr_lr_3_1
Optional overrides:

    poetry run python scripts/synthetic_assets/smoke_component_weights.py \
        --asset-id <asset_id> \
        --start 2025-01-02 \
        --end 2025-02-28 \
        --mxm-business-calendar-id mxm_v1_business

This is a human inspection tool, not a regression test.
"""

import argparse
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
import pandas as pd
from mxm_refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)

from mxm.v1.calendars.mxm_business_calendar_service import MXMBusinessCalendarService
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.synthetic_assets.component_contracts import (
    ComponentContracts,
    build_component_contracts,
)
from mxm.v1.synthetic_assets.component_weights import (
    ComponentWeights,
    build_component_weights,
)
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.spec_registry import SyntheticAssetSpecRegistry
from mxm.v1.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)

# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------

DEFAULT_MXM_BUSINESS_CALENDAR_ID = "mxm_v1_business"

# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke ComponentWeights build")

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
        help="Number of head rows to print (default: 10)",
    )
    p.add_argument(
        "--max-active",
        type=int,
        default=50,
        help="Maximum number of active-roll rows to print (default: 50)",
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

    print(frame.head(max_head).to_string())
    print()


def _active_mask(frame: pd.DataFrame, *, atol: float = 1e-12) -> np.ndarray:
    """
    Return rows where at least one component has a materially non-trivial weight
    strictly between 0 and 1 in absolute value.

    This highlights roll windows while ignoring flat fully-held rows.
    """
    values = frame.to_numpy(dtype=float)
    return np.any((np.abs(values) > atol) & (np.abs(values) < 1.0 - atol), axis=1)


def _print_active_rows(
    *,
    frame: pd.DataFrame,
    max_active: int,
) -> None:
    print("Active roll rows")
    if frame.empty:
        print("  <empty>")
        print()
        return

    mask = _active_mask(frame)
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


def _print_component_contract_snapshot(
    *,
    component_contracts: ComponentContracts,
    component_weights: ComponentWeights,
    max_rows: int,
) -> None:
    """
    Human-facing joined diagnostic view:
      session | component | contract_id | weight
    """
    cc_long = component_contracts.frame.stack().rename("contract_id").reset_index()
    cw_long = component_weights.frame.stack().rename("weight").reset_index()

    joined = cc_long.merge(
        cw_long,
        on=["session", "level_1"],
        how="inner",
        validate="one_to_one",
    )
    joined = joined.rename(columns={"level_1": "component"})

    print("Component contract/weight rows (head)")
    if joined.empty:
        print("  <empty>")
        print()
        return

    print(joined.head(max_rows).to_string(index=False))
    print()


def _print_invariants(
    *,
    spec: SyntheticAssetSpec,
    component_contracts: ComponentContracts,
    component_weights: ComponentWeights,
) -> None:
    print("Invariants")

    cc = component_contracts.frame
    cw = component_weights.frame

    print(f"  component_contracts rows: {len(cc)}")
    print(f"  component_weights rows:   {len(cw)}")
    print(f"  session index aligned:    {cc.index.equals(cw.index)}")
    print(f"  component columns aligned:{list(cc.columns) == list(cw.columns)}")
    print(f"  first session:            {cc.index[0] if len(cc.index) else '<empty>'}")
    print(f"  last session:             {cc.index[-1] if len(cc.index) else '<empty>'}")
    print()

    roles = list(spec.components.keys())
    role_set = set(roles)

    for role in roles:
        w = cw[role].to_numpy(dtype=float)
        print(
            f"  {role:>10s} : min={float(np.min(w)): .4f}  max={float(np.max(w)): .4f}"
        )

    if role_set == {"cur", "nxt"}:
        err = np.max(
            np.abs(
                cw["cur"].to_numpy(dtype=float) + cw["nxt"].to_numpy(dtype=float) - 1.0
            )
        )
        print(f"  pair sum max|cur+nxt-1|: {float(err):.12f}")

    elif role_set == {"near_cur", "near_nxt", "far_cur", "far_nxt"}:
        near = cw["near_cur"].to_numpy(dtype=float) + cw["near_nxt"].to_numpy(
            dtype=float
        )
        far = cw["far_cur"].to_numpy(dtype=float) + cw["far_nxt"].to_numpy(dtype=float)
        total = near + far

        print(f"  near sum max|near-1|:    {float(np.max(np.abs(near - 1.0))):.12f}")
        print(f"  far  sum max|far+1|:     {float(np.max(np.abs(far + 1.0))):.12f}")
        print(f"  total max|near+far|:     {float(np.max(np.abs(total))):.12f}")

    elif role_set == {"a_cur", "a_nxt", "b_cur", "b_nxt"}:
        a = cw["a_cur"].to_numpy(dtype=float) + cw["a_nxt"].to_numpy(dtype=float)
        b = cw["b_cur"].to_numpy(dtype=float) + cw["b_nxt"].to_numpy(dtype=float)
        total = a + b

        print(f"  a sum max|a-1|:          {float(np.max(np.abs(a - 1.0))):.12f}")
        print(f"  b sum max|b+1|:          {float(np.max(np.abs(b + 1.0))):.12f}")
        print(f"  total max|a+b|:          {float(np.max(np.abs(total))):.12f}")

    else:
        print("  no built-in invariant summary for this component structure")

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

    component_contracts = build_component_contracts(
        spec=spec,
        start_session=start,
        end_session=end,
        engine=engine,
        calendar_service=calendars,
        mxm_business_calendar=mxm_business_calendar,
    )

    component_weights = build_component_weights(
        spec=spec,
        component_contracts=component_contracts,
        engine=engine,
        calendar_service=calendars,
        mxm_business_calendar=mxm_business_calendar,
        refdata_api=refdata,
    )

    print("Range")
    print(f"  sessions: {len(component_weights.frame.index)}")
    print(
        f"  first:    {component_weights.frame.index[0] if len(component_weights.frame.index) else '<empty>'}"
    )
    print(
        f"  last:     {component_weights.frame.index[-1] if len(component_weights.frame.index) else '<empty>'}"
    )
    print(f"  components:{', '.join(list(component_weights.frame.columns))}")
    print()

    _print_frame_head(
        "ComponentContracts (head)",
        component_contracts.frame,
        args.max_head,
    )

    _print_frame_head(
        "ComponentWeights (head)",
        component_weights.frame,
        args.max_head,
    )

    _print_active_rows(
        frame=component_weights.frame,
        max_active=args.max_active,
    )

    _print_component_contract_snapshot(
        component_contracts=component_contracts,
        component_weights=component_weights,
        max_rows=args.max_head,
    )

    _print_invariants(
        spec=spec,
        component_contracts=component_contracts,
        component_weights=component_weights,
    )

    print("=" * 72)
    print("Done.")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
