from __future__ import annotations

"""
Smoke script: build and inspect a WeightsSeries from a SyntheticAssetSpec.

Usage:

    poetry run python scripts/synthetic_assets/smoke_weights_series.py \
        --asset-id <asset_id> \
        --start 2025-01-02 \
        --end 2025-02-28

This is a human inspection tool, not a regression test.
"""

import argparse
import sys
from pathlib import Path
from typing import Sequence

import numpy as np
from mxm_refdata.api.ref_data_api import (  # type: ignore[reportMissingTypeStubs]
    RefDataAPI,
)

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.contract_series import (
    ContractSeries,
    ContractSeriesSpec,
    build_contract_series,
)
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.contracts.selectors import SelectorRule
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec

# Adjust this import to your actual registry loader:
from mxm.v1.synthetic_assets.spec_registry import (
    SyntheticAssetSpecRegistry,
)
from mxm.v1.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)
from mxm.v1.synthetic_assets.weights_series import WeightsSeries, build_weights_series

# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke WeightsSeries build")

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

    return p.parse_args(argv)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _build_contract_series_by_role_for_smoke(
    *,
    spec: SyntheticAssetSpec,
    start_session: np.datetime64,
    end_session: np.datetime64,
    engine: ContractSelectorEngine,
    calendar_service: TradingCalendarService,
) -> dict[str, ContractSeries]:
    """
    Rebuild ContractSeries per role for smoke inspection.

    This is only for diagnostics so we can aggregate role weights onto actual
    contract_ids and inspect whether exposure is shifting between contracts.
    """
    out: dict[str, ContractSeries] = {}

    for role, leg in spec.legs.items():
        rule = SelectorRule.from_canonical_relative_id(leg.selector_rule_id)
        cs_spec = ContractSeriesSpec(
            product_id=leg.product_id,
            rule=rule,
            start_session=start_session,
            end_session=end_session,
        )
        out[role] = build_contract_series(
            engine=engine,
            calendar_service=calendar_service,
            spec=cs_spec,
        )

    return out


def _build_contract_weight_rows(
    *,
    role_contract_series: dict[str, ContractSeries],
    role_weights: dict[str, np.ndarray],
) -> list[dict[str, float]]:
    """
    Aggregate role-level weights onto actual contract_ids per session.

    For each session t:
        contract_weight[t, contract_id] = sum_role weight[role, t]
        where contract_id = ContractSeries(role).contract_ids[t]

    This is a smoke-only diagnostic view. It is useful because true roll events
    shift exposure between contract_ids, whereas role relabelling/reset may not.
    """
    roles = sorted(role_weights.keys())
    if not roles:
        return []

    n = len(role_weights[roles[0]])
    rows: list[dict[str, float]] = []

    for i in range(n):
        row: dict[str, float] = {}
        for role in roles:
            cs = role_contract_series[role]
            cid = cs.contract_ids[i]
            w = float(role_weights[role][i])
            row[cid] = row.get(cid, 0.0) + w

        # Drop tiny numerical noise
        row = {cid: w for cid, w in row.items() if abs(w) > 1e-12}
        rows.append(dict(sorted(row.items())))

    return rows


def _format_contract_weight_row(
    session: np.datetime64,
    contract_weights: dict[str, float],
) -> str:
    if not contract_weights:
        return f"  {session}  <empty>"

    parts = [f"{cid}={w: .4f}" for cid, w in contract_weights.items()]
    return f"  {session}  " + "  ".join(parts)


def _contract_weight_change_mask(
    rows: list[dict[str, float]],
    *,
    atol: float = 1e-12,
) -> np.ndarray:
    """
    Return rows where aggregated contract-weight exposure changed vs previous row.

    This is a better proxy for real roll activity than role-weight changes,
    because role relabelling may change cur/nxt weights without changing
    economic exposure by contract.
    """
    n = len(rows)
    if n == 0:
        return np.zeros(0, dtype=bool)

    out = np.zeros(n, dtype=bool)

    for i in range(1, n):
        prev = rows[i - 1]
        curr = rows[i]
        cids = set(prev.keys()) | set(curr.keys())

        changed = False
        for cid in cids:
            w0 = prev.get(cid, 0.0)
            w1 = curr.get(cid, 0.0)
            if abs(w1 - w0) > atol:
                changed = True
                break

        out[i] = changed

    return out


def _format_weight_row(
    session: np.datetime64,
    role_weights: dict[str, np.ndarray],
    idx: int,
) -> str:
    parts = [f"{role}={float(w[idx]): .4f}" for role, w in role_weights.items()]
    return f"  {session}  " + "  ".join(parts)


def _active_mask(role_weights: dict[str, np.ndarray]) -> np.ndarray:
    """
    Return rows where at least one role has a non-trivial absolute weight
    strictly between 0 and 1.

    This highlights roll windows and ignores flat fully-held rows.
    """
    roles = list(role_weights.keys())
    if not roles:
        return np.zeros(0, dtype=bool)

    n = len(role_weights[roles[0]])
    out = np.zeros(n, dtype=bool)

    for w in role_weights.values():
        aw = np.abs(w)
        out |= (aw > 0.0) & (aw < 1.0)

    return out


def _print_invariants(spec: SyntheticAssetSpec, ws: WeightsSeries) -> None:
    print("Invariants")

    roles = sorted(ws.role_weights.keys())
    for role in roles:
        w = ws.role_weights[role]
        print(
            f"  {role:>10s} : min={float(np.min(w)): .4f}  max={float(np.max(w)): .4f}"
        )

    role_set = set(roles)

    if role_set == {"cur", "nxt"}:
        err = np.max(np.abs(ws.role_weights["cur"] + ws.role_weights["nxt"] - 1.0))
        print(f"  pair sum max|cur+nxt-1|: {float(err):.12f}")

    elif role_set == {"near_cur", "near_nxt", "far_cur", "far_nxt"}:
        near = ws.role_weights["near_cur"] + ws.role_weights["near_nxt"]
        far = ws.role_weights["far_cur"] + ws.role_weights["far_nxt"]
        total = near + far

        print(f"  near sum max|near-1|:    {float(np.max(np.abs(near - 1.0))):.12f}")
        print(f"  far  sum max|far+1|:     {float(np.max(np.abs(far + 1.0))):.12f}")
        print(f"  total max|near+far|:     {float(np.max(np.abs(total))):.12f}")

    elif role_set == {"a_cur", "a_nxt", "b_cur", "b_nxt"}:
        a = ws.role_weights["a_cur"] + ws.role_weights["a_nxt"]
        b = ws.role_weights["b_cur"] + ws.role_weights["b_nxt"]
        total = a + b

        print(f"  a sum max|a-1|:          {float(np.max(np.abs(a - 1.0))):.12f}")
        print(f"  b sum max|b+1|:          {float(np.max(np.abs(b + 1.0))):.12f}")
        print(f"  total max|a+b|:          {float(np.max(np.abs(total))):.12f}")

    else:
        print("  no built-in invariant summary for this role structure")

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

    # --- Load real synthetic asset spec ---
    if args.registry_root is not None:
        layout = SyntheticAssetSpecRegistryLayout(root=Path(args.registry_root))
    else:
        layout = SyntheticAssetSpecRegistryLayout(root=Path.home() / ".mxm")

    registry = SyntheticAssetSpecRegistry(layout=layout)

    spec = registry.load(asset_id=asset_id)

    print("=" * 72)
    print("Building WeightsSeries")
    print(f"asset_id:       {spec.asset_id}")
    print(f"canonical_id:   {spec.canonical_id}")
    print(f"weights_rule:   {spec.weights_rule_id}")
    print(f"start:          {start}")
    print(f"end:            {end}")
    print("=" * 72)

    print()
    print("Leg bindings")
    for role, leg in spec.legs.items():
        print(
            f"  {role:>10s} -> product_id={leg.product_id}  "
            f"selector_rule_id={leg.selector_rule_id}"
        )

    ws = build_weights_series(
        spec=spec,
        start_session=start,
        end_session=end,
        engine=engine,
        calendar_service=calendars,
        refdata_api=refdata,
    )

    print()
    print("Range")
    print(f"  sessions: {len(ws.sessions)}")
    print(f"  first:    {ws.sessions[0]}")
    print(f"  last:     {ws.sessions[-1]}")
    print(f"  roles:    {', '.join(sorted(ws.role_weights.keys()))}")

    print()
    print(f"Head (first {args.max_head} rows)")
    for i in range(min(args.max_head, len(ws.sessions))):
        session_i = np.datetime64(ws.sessions[i], "D")
        print(_format_weight_row(session_i, ws.role_weights, i))

    active = _active_mask(ws.role_weights)
    active_idx = np.flatnonzero(active)

    print()
    print(f"Active roll rows: {len(active_idx)}")
    for i in active_idx[: args.max_active]:
        ii = int(i)
        session_i = np.datetime64(ws.sessions[ii], "D")
        print(_format_weight_row(session_i, ws.role_weights, ii))

    if len(active_idx) > args.max_active:
        print(f"  ... truncated after {args.max_active} rows")
    # ------------------------------------------------------------------
    # Contract-weight diagnostic view
    # ------------------------------------------------------------------
    role_contract_series = _build_contract_series_by_role_for_smoke(
        spec=spec,
        start_session=start,
        end_session=end,
        engine=engine,
        calendar_service=calendars,
    )

    contract_weight_rows = _build_contract_weight_rows(
        role_contract_series=role_contract_series,
        role_weights=ws.role_weights,
    )
    contract_change = _contract_weight_change_mask(contract_weight_rows)
    contract_change_idx = np.flatnonzero(contract_change)

    print()
    print("Contract-weight head (first 10 rows)")
    for i in range(min(10, len(ws.sessions))):
        session_i = np.datetime64(ws.sessions[i], "D")
        print(_format_contract_weight_row(session_i, contract_weight_rows[i]))

    print()
    print(f"Contract-weight change rows: {len(contract_change_idx)}")
    for i in contract_change_idx[: args.max_active]:
        ii = int(i)
        session_i = np.datetime64(ws.sessions[ii], "D")
        print(_format_contract_weight_row(session_i, contract_weight_rows[ii]))

    if len(contract_change_idx) > args.max_active:
        print(f"  ... truncated after {args.max_active} rows")
    print()
    _print_invariants(spec, ws)

    print("=" * 72)
    print("Done.")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
