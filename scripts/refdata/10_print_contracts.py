#!/usr/bin/env python3
"""
Pretty-print contracts for a futures product from mxm-refdata.

This is a Session-6-era inspection/proof script. It favors clarity over permanence.
If it becomes a regular operator tool, promote it into mxm.v1.bin or a Typer CLI.

Examples:
  poetry run python scripts/refdata/10_print_contracts.py --product-id cme_emini_snp500_futures
  poetry run python scripts/refdata/10_print_contracts.py --product-id cme_emini_snp500_futures --as-of 2026-01-15
  poetry run python scripts/refdata/10_print_contracts.py --product-id cme_emini_snp500_futures --as-of 2026-01-15 --active-only
  poetry run python scripts/refdata/10_print_contracts.py --product-id cme_emini_snp500_futures --as-of 2026-01-15 --active-only --limit 12
"""

from __future__ import annotations

import argparse
from datetime import date
from typing import Any

import pandas as pd
from rich.console import Console
from rich.table import Table

from mxm.refdata.api.ref_data_api import RefDataAPI


def _parse_date(s: str) -> date:
    try:
        y, m, d = s.split("-")
        return date(int(y), int(m), int(d))
    except Exception as e:
        raise argparse.ArgumentTypeError(f"Invalid date '{s}'. Use YYYY-MM-DD.") from e


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, date):
        return v.isoformat()
    return str(v)


def _contracts_to_df(contracts: list[Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for c in contracts:
        rows.append(
            {
                "contract_id": getattr(c, "contract_id", ""),
                "period_id": getattr(c, "period_id", ""),
                "first_day_of_interest": getattr(c, "first_day_of_interest", None),
                "last_trading_day": getattr(c, "last_trading_day", None),
            }
        )
    df = pd.DataFrame(rows)
    if not df.empty:
        df.insert(0, "idx", range(1, len(df) + 1))
    return df


def _print_df_as_rich_table(df: pd.DataFrame, *, title: str | None = None) -> None:
    import sys

    console = Console(file=sys.stdout, force_terminal=True)

    if df.empty:
        console.print("No rows.")
        return

    table = Table(title=title, show_lines=False)

    for col in df.columns:
        if col == "contract_id":
            table.add_column(str(col), no_wrap=True, overflow="ellipsis")
        else:
            table.add_column(str(col), overflow="fold")

    for _, row in df.iterrows():
        table.add_row(*[_fmt(row[col]) for col in df.columns])

    console.print(table)
    sys.stdout.flush()


def _print_df_plain(df: pd.DataFrame) -> None:
    if df.empty:
        print("(no rows)")
        return
    # Plain fallback; keep it stable and readable.
    print(df.to_string(index=False))


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Print ordered futures contracts for a product."
    )
    ap.add_argument("--product-id", required=True, help="MXM FuturesProduct.product_id")
    ap.add_argument(
        "--as-of", type=_parse_date, default=None, help="As-of date (YYYY-MM-DD)"
    )
    ap.add_argument(
        "--active-only",
        action="store_true",
        help="If set, prints only contracts active as-of --as-of (requires --as-of).",
    )
    ap.add_argument(
        "--limit", type=int, default=None, help="Limit number of rows printed."
    )
    ap.add_argument(
        "--format",
        choices=["rich", "plain"],
        default="rich",
        help="Output format. 'rich' uses the Rich table renderer; 'plain' uses pandas to_string.",
    )
    args = ap.parse_args()

    api = RefDataAPI()

    contracts = api.get_contracts_for_product(args.product_id)
    if args.active_only:
        if args.as_of is None:
            raise SystemExit("--active-only requires --as-of YYYY-MM-DD")
        active = api.get_active_contracts(args.as_of, product_id=args.product_id)
        active_ids = {c.contract_id for c in active}
        contracts = [c for c in contracts if c.contract_id in active_ids]

    if args.limit is not None:
        contracts = contracts[: args.limit]

    df = _contracts_to_df(contracts)

    title_bits = [f"product_id={args.product_id}"]
    if args.as_of is not None:
        title_bits.append(f"as_of={args.as_of.isoformat()}")
    if args.active_only:
        title_bits.append("active_only=True")

    title = f"Contracts ({', '.join(title_bits)}): {len(df)}"

    if args.format == "rich":
        _print_df_as_rich_table(df, title=title)
    else:
        print(title)
        _print_df_plain(df)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
