from __future__ import annotations

"""
Smoke script: build a realised SyntheticAsset, run a short historical
backtest, and construct session / contract-level PnL.

Usage:

    poetry run python scripts/pnl/smoke_synthetic_asset_pnl.py \
        --asset-id cme_emini_snp500_futures_cont_hmuz1_wr_lr_3_1 \
        --start 2025-01-02 \
        --end 2025-01-16

Optional overrides:

    poetry run python scripts/pnl/smoke_synthetic_asset_pnl.py \
        --asset-id cme_emini_snp500_futures_cont_hmuz1_wr_lr_3_1 \
        --start 2025-01-02 \
        --end 2025-01-16 \
        --mxm-business-base-calendar-id cmes \
        --mxm-business-calendar-id mxm_v1_business

This is a human inspection tool, not a regression test.
"""

import json
from dataclasses import asdict, dataclass

import matplotlib

matplotlib.use("Agg")
import argparse
import sys
from pathlib import Path
from typing import Sequence

import matplotlib.pyplot as plt  # type: ignore[reportUnknownVariableType]
import numpy as np
import pandas as pd
from mxm_refdata.api.ref_data_api import (
    RefDataAPI,  # type: ignore[reportMissingTypeStubs]
)

from mxm.v1.calendars.mxm_business_calendar_service import MXMBusinessCalendarService
from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.execution.backtester import Backtester, BacktestResult
from mxm.v1.execution.executor import PerfectBacktestExecutor
from mxm.v1.execution.orders import OrderGenerationPolicy, OrderGenerator
from mxm.v1.execution.price_accessors import (
    DailyMarkExecutionPriceAccessor,
    DailyMarkPriceAccessor,
)
from mxm.v1.execution.session_engine import SessionEngine
from mxm.v1.fx.spot_fx_converter import IdentitySpotFXConverter
from mxm.v1.pnl.constructor import build_pnl_series
from mxm.v1.pnl.models import PnLSeries
from mxm.v1.synthetic_assets.models import SyntheticAssetSpec
from mxm.v1.synthetic_assets.runtime import SyntheticAsset, build_synthetic_asset
from mxm.v1.synthetic_assets.spec_registry import SyntheticAssetSpecRegistry
from mxm.v1.synthetic_assets.spec_registry_layout import (
    SyntheticAssetSpecRegistryLayout,
)
from mxm.v1.synthetic_assets.unit_conversion import build_default_unit_converter
from mxm.v1.utils.date_utils import coerce_np_day

# ---------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------
DEFAULT_CALENDAR_ID = "mxm_business_days_v1"
DEFAULT_CALENDAR_START = "2010-01-01"
DEFAULT_CALENDAR_END = "2050-12-31"

# ---------------------------------------------------------------------
# Plotting helpers
# ---------------------------------------------------------------------


@dataclass(frozen=True)
class PnLSmokeMeta:
    report_kind: str
    asset_id: str
    created_at_utc: str
    start: str
    end: str
    price_surface: str
    target_currency: str
    session_count: int
    cumulative_total_pnl: float | None
    cumulative_price_move_pnl: float | None
    cumulative_trade_pnl: float | None
    output_files: list[str]


def _slug(s: str) -> str:
    return s.replace("/", "_").replace(" ", "_").replace(":", "_").replace(".", "_")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke SyntheticAsset PnL pipeline")

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
        "--max-contract-pnl",
        type=int,
        default=20,
        help="Maximum number of contract-level pnl rows to print (default: 20)",
    )
    p.add_argument(
        "--outdir",
        default="dev_plots/pnl/synthetic_asset",
        help="output directory for saved plots (default: dev_plots/pnl/synthetic_asset)",
    )
    p.add_argument(
        "--calendar-id",
        default=DEFAULT_CALENDAR_ID,
        help="MXM business calendar base identifier.",
    )
    p.add_argument(
        "--calendar-start",
        default=DEFAULT_CALENDAR_START,
        help="Inclusive MXM business calendar start label (YYYY-MM-DD).",
    )
    p.add_argument(
        "--calendar-end",
        default=DEFAULT_CALENDAR_END,
        help="Inclusive MXM business calendar end label (YYYY-MM-DD).",
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

    print(frame.head(max_head).to_string())
    print()


def _active_holdings_mask(frame: pd.DataFrame, *, atol: float = 1e-12) -> np.ndarray:
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

    active = frame.loc[_active_holdings_mask(frame)]

    print(f"  count: {len(active)}")
    if active.empty:
        print("  <none>")
        print()
        return

    print(active.head(max_active).to_string())
    if len(active) > max_active:
        print(f"  ... truncated after {max_active} rows")
    print()


def _print_asset_invariants(asset: SyntheticAsset) -> None:
    print("Synthetic asset invariants")

    cc = asset.component_contracts.frame
    cw = asset.component_weights.frame
    th = asset.target_holdings.frame

    print(f"  component_contracts rows:  {len(cc)}")
    print(f"  component_weights rows:    {len(cw)}")
    print(f"  target_holdings rows:      {len(th)}")
    print(f"  session index aligned:     {cc.index.equals(cw.index)}")
    print(f"  component columns aligned: {list(cc.columns) == list(cw.columns)}")
    print(f"  first session:             {cc.index[0] if len(cc.index) else '<empty>'}")
    print(
        f"  last session:              {cc.index[-1] if len(cc.index) else '<empty>'}"
    )
    print()


def _print_backtest_summary(backtest_result: BacktestResult) -> None:
    print("Backtest summary")
    print(f"  session_results: {len(backtest_result.session_results)}")

    if backtest_result.is_empty():
        print("  first session:   <empty>")
        print("  last session:    <empty>")
    else:
        print(f"  first session:   {backtest_result.first_session()}")
        print(f"  last session:    {backtest_result.last_session()}")
    print()


def _print_pnl_summary(pnl_series: PnLSeries) -> None:
    df = pnl_series.to_cumulative_dataframe()

    print("PnL summary")
    print(f"  session_pnls:    {len(pnl_series.session_pnls)}")

    if df.empty:
        print("  cumulative total pnl:       <empty>")
        print("  cumulative price_move pnl:  <empty>")
        print("  cumulative trade pnl:       <empty>")
        print()
        return

    print(f"  cumulative total pnl:       {df['cumulative_total_pnl'].iloc[-1]:.6f}")
    print(
        f"  cumulative price_move pnl:  {df['cumulative_price_move_pnl'].iloc[-1]:.6f}"
    )
    print(f"  cumulative trade pnl:       {df['cumulative_trade_pnl'].iloc[-1]:.6f}")
    print()


def _print_contract_pnl_head(
    *,
    pnl_series: PnLSeries,
    max_contract_pnl: int,
) -> None:
    print("Contract-level PnL (head)")

    df = pnl_series.to_contract_dataframe()
    # check unique increments
    increments = df["price_move_pnl"].dropna().unique()
    print(sorted(set(increments[:100])))

    if df.empty:
        print("  <empty>")
        print()
        return

    print(df.head(max_contract_pnl).to_string(index=False))
    if len(df) > max_contract_pnl:
        print(f"  ... truncated after {max_contract_pnl} rows")
    print()


def _save_cumulative_pnl_plot(
    *,
    pnl_series: PnLSeries,
    asset_id: str,
    outpath: Path,
) -> None:
    df = pnl_series.to_cumulative_dataframe()
    if df.empty:
        raise ValueError("No PnL rows available to plot.")

    fig, ax = plt.subplots(figsize=(10, 6))  # pyright: ignore[reportUnknownMemberType]
    ax.plot(  # pyright: ignore[reportUnknownMemberType]
        df["session"], df["cumulative_total_pnl"], label="Total"
    )
    ax.plot(  # pyright: ignore[reportUnknownMemberType]
        df["session"], df["cumulative_price_move_pnl"], label="Price move"
    )
    ax.plot(  # pyright: ignore[reportUnknownMemberType]
        df["session"], df["cumulative_trade_pnl"], label="Trade"
    )
    ax.set_title(f"Cumulative PnL — {asset_id}")  # pyright: ignore[reportUnknownMemberType]
    ax.set_xlabel("Session")  # pyright: ignore[reportUnknownMemberType]
    ax.set_ylabel("PnL")  # pyright: ignore[reportUnknownMemberType]
    ax.legend()  # pyright: ignore[reportUnknownMemberType]
    fig.tight_layout()  # pyright: ignore[reportUnknownMemberType]
    fig.savefig(outpath, dpi=150)  # pyright: ignore[reportUnknownMemberType]
    plt.close(fig)  # pyright: ignore[reportUnknownMemberType]


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    asset_id = args.asset_id
    start = coerce_np_day(args.start)
    end = coerce_np_day(args.end)

    # --- Build real services ---
    refdata = RefDataAPI()
    calendars = TradingCalendarService(refdata_api=refdata)
    engine = ContractSelectorEngine.build(refdata=refdata, calendars=calendars)
    unit_converter = build_default_unit_converter()
    mxm_business_calendar_service = MXMBusinessCalendarService(
        calendar_base_id=str(args.calendar_id),
        start_label=coerce_np_day(args.calendar_start),
        end_label=coerce_np_day(args.calendar_end),
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
    print(f"  calendar_base_id: {args.calendar_id}")
    print(f"  calendar_start:   {coerce_np_day(args.calendar_start)}")
    print(f"  calendar_end:     {coerce_np_day(args.calendar_end)}")
    print(f"  calendar_id:      {mxm_business_calendar.calendar_id}")
    print()

    # --- Build real synthetic asset ---
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
    _print_asset_invariants(asset)

    if asset.target_holdings.frame.empty:
        raise ValueError("SyntheticAsset.target_holdings is empty.")

    # --- Build real execution / backtest infrastructure ---
    order_policy = OrderGenerationPolicy(default_min_block_size=1)
    order_generator = OrderGenerator(
        policy=order_policy,
        ref_data_api=refdata,
        calendar_service=calendars,
    )
    execution_price_accessor = DailyMarkExecutionPriceAccessor(
        mxm_business_calendar=mxm_business_calendar,
        ref_data_api=refdata,
    )
    executor = PerfectBacktestExecutor(
        execution_price_accessor=execution_price_accessor
    )

    session_engine = SessionEngine(
        ref_data_api=refdata,
        order_generator=order_generator,
        executor=executor,
    )
    backtester = Backtester(session_engine=session_engine)

    # --- Run historical backtest ---
    backtest_result = backtester.run_target_holdings(
        target_holdings=asset.target_holdings
    )
    _print_backtest_summary(backtest_result)

    if backtest_result.is_empty():
        raise ValueError("BacktestResult is empty.")

    # --- Build PnL ---
    mark_price_accessor = DailyMarkPriceAccessor(
        mxm_business_calendar=mxm_business_calendar,
        ref_data_api=refdata,
    )

    fx_converter = IdentitySpotFXConverter()

    pnl_series = build_pnl_series(
        session_results=backtest_result.session_results,
        mark_price_accessor=mark_price_accessor,
        spot_fx_converter=fx_converter,
        ref_data_api=refdata,
        target_currency=spec.currency,
    )

    _print_pnl_summary(pnl_series)

    session_df = pnl_series.to_cumulative_dataframe()

    _print_frame_head(
        "Session-level PnL (head)",
        session_df,
        args.max_head,
    )
    _print_contract_pnl_head(
        pnl_series=pnl_series,
        max_contract_pnl=args.max_contract_pnl,
    )

    if not session_df.empty:
        total_trade_pnl = float(session_df["trade_pnl"].sum())
        if abs(total_trade_pnl) > 1e-12:
            print(
                "WARNING: non-zero aggregate trade PnL detected under perfect-fill "
                f"execution: {total_trade_pnl:.12f}"
            )
            print()

    outdir = Path(args.outdir)
    _ensure_dir(outdir)

    start_s = str(args.start)
    end_s = str(args.end)
    stem = f"synthetic_asset_pnl__{_slug(asset_id)}__{start_s}__{end_s}__daily_mark"

    plot_path = outdir / f"{stem}__cumulative_pnl.png"
    meta_path = outdir / f"{stem}__meta.json"

    _save_cumulative_pnl_plot(
        pnl_series=pnl_series,
        asset_id=asset_id,
        outpath=plot_path,
    )

    if session_df.empty:
        cumulative_total = None
        cumulative_price_move = None
        cumulative_trade = None
    else:
        cumulative_total = float(session_df["cumulative_total_pnl"].iloc[-1])
        cumulative_price_move = float(session_df["cumulative_price_move_pnl"].iloc[-1])
        cumulative_trade = float(session_df["cumulative_trade_pnl"].iloc[-1])

    meta = PnLSmokeMeta(
        report_kind="synthetic_asset_pnl_smoke",
        asset_id=asset_id,
        created_at_utc=pd.Timestamp.utcnow().isoformat(),
        start=str(args.start),
        end=str(args.end),
        price_surface="daily_mark",
        target_currency=spec.currency,
        session_count=int(len(session_df)),
        cumulative_total_pnl=cumulative_total,
        cumulative_price_move_pnl=cumulative_price_move,
        cumulative_trade_pnl=cumulative_trade,
        output_files=[str(plot_path)],
    )

    meta_path.write_text(
        json.dumps(asdict(meta), indent=2, default=str) + "\n",
        encoding="utf-8",
    )

    print("Saved outputs")
    print(f"  {plot_path}")
    print(f"  {meta_path}")
    print()

    print("=" * 72)
    print("Done.")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
