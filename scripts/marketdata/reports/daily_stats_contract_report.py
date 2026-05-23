from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

from mxm.moneymachine.marketdata.datasets.daily_stats.api import (
    read_daily_stats_contract,
)
from mxm.moneymachine.utils.time_utils import utc_now_ts

matplotlib.use("Agg")  # headless-safe


@dataclass(frozen=True)
class ReportMeta:
    report_kind: str
    created_at_utc: str
    root: str
    contract_id: str
    start: str | None
    end: str | None
    rows: int
    trading_date_min: str | None
    trading_date_max: str | None
    output_files: list[str]


def _slug(s: str) -> str:
    # filesystem-safe, deterministic
    return s.replace("/", "_").replace(" ", "_").replace(":", "_").replace(".", "_")


def _fmt_day(ts: pd.Timestamp | None) -> str | None:
    if ts is None:
        return None
    return ts.strftime("%Y-%m-%d")


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _plot_settle(df: pd.DataFrame, outpath: Path, *, title: str) -> None:
    if "settle_px" not in df.columns:
        raise ValueError("daily_stats df missing required column settle_px")

    d = df[["trading_date", "settle_px"]].dropna(subset=["settle_px"]).copy()
    d = d.sort_values("trading_date")

    plt.figure()
    plt.plot(d["trading_date"], d["settle_px"])
    plt.title(title)
    plt.xlabel("trading_date (UTC day label)")
    plt.ylabel("settle_px")
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()


def _plot_volume(df: pd.DataFrame, outpath: Path, *, title: str) -> None:
    if "cleared_volume_qty" not in df.columns:
        raise ValueError("daily_stats df missing required column cleared_volume_qty")

    d = (
        df[["trading_date", "cleared_volume_qty"]]
        .dropna(subset=["cleared_volume_qty"])
        .copy()
    )
    d = d.sort_values("trading_date")

    plt.figure()
    # Bar plot: one bar per trading day
    plt.bar(d["trading_date"], d["cleared_volume_qty"])
    plt.title(title)
    plt.xlabel("trading_date (UTC day label)")
    plt.ylabel("cleared_volume_qty")
    plt.tight_layout()
    plt.savefig(outpath, dpi=150)
    plt.close()


def main() -> int:
    p = argparse.ArgumentParser(
        description="MXM: daily_stats contract report (settle + volume)",
    )
    p.add_argument(
        "--contract-id", required=True, help="e.g. cme_emini_snp500_futures.Jun-2025"
    )
    p.add_argument("--root", default=None, help="MXM root (default: ~/.mxm)")
    p.add_argument(
        "--start",
        default=None,
        help="YYYY-MM-DD (inclusive), interpreted as UTC day label",
    )
    p.add_argument(
        "--end",
        default=None,
        help="YYYY-MM-DD (exclusive), interpreted as UTC day label",
    )
    p.add_argument(
        "--outdir",
        default="dev_plots/daily_stats/contract",
        help="output directory (default: dev_plots/daily_stats/contract)",
    )

    args = p.parse_args()

    root = Path(args.root) if args.root else (Path.home() / ".mxm")
    outdir = Path(args.outdir)
    _ensure_dir(outdir)

    df = read_daily_stats_contract(
        contract_id=args.contract_id,
        root=root,
        start=args.start,
        end=args.end,
    )

    if df.empty:
        print(f"[daily-stats-report] no data for contract_id={args.contract_id!r}")
        return 2

    td_min = pd.Timestamp(df["trading_date"].min())
    td_max = pd.Timestamp(df["trading_date"].max())

    start_s = args.start or "ALL"
    end_s = args.end or "ALL"
    stem = f"daily_stats__{_slug(args.contract_id)}__{start_s}__{end_s}"

    settle_path = outdir / f"{stem}__settle_px.png"
    vol_path = outdir / f"{stem}__cleared_volume_qty.png"
    meta_path = outdir / f"{stem}__meta.json"

    _plot_settle(
        df,
        settle_path,
        title=f"DailyStats settle_px — {args.contract_id} ({_fmt_day(td_min)}..{_fmt_day(td_max)})",
    )
    _plot_volume(
        df,
        vol_path,
        title=f"DailyStats cleared_volume_qty — {args.contract_id} ({_fmt_day(td_min)}..{_fmt_day(td_max)})",
    )

    meta = ReportMeta(
        report_kind="daily_stats_contract_report",
        created_at_utc=utc_now_ts().isoformat(),
        root=str(root),
        contract_id=args.contract_id,
        start=args.start,
        end=args.end,
        rows=len(df),
        trading_date_min=_fmt_day(td_min),
        trading_date_max=_fmt_day(td_max),
        output_files=[str(settle_path), str(vol_path)],
    )
    meta_path.write_text(
        json.dumps(asdict(meta), indent=2, default=str) + "\n", encoding="utf-8"
    )

    print(f"[daily-stats-report] wrote:\n  {settle_path}\n  {vol_path}\n  {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
