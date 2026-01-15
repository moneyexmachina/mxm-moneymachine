#!/usr/bin/env python3
"""
scripts/databento/21_map_product_contracts.py

Session 6 proof script (metadata-side only; no rated time-series requests):

- Enumerate MXM contracts for a product_id (via mxm-refdata).
- Resolve Databento parent symbology via a small code-maintained mapping table.
- Use Databento *reference/symbology* APIs (via mxm.v1.vendor_mapping.databento) to:
    - enumerate instruments under the parent
    - retrieve instrument definitions (expiration anchors)
    - normalize into a join-friendly vendor table

- Apply guardrails suited for metadata endpoints:
    - cap number of instruments fetched (default --max-instruments 5000)
    - allow --no-fetch for a dry run

This version prints:
- MXM contracts table (with year/month)
- existing sqlite mapping rows (likely empty)
- vendor definitions preview + summary

This version does NOT yet:
- join MXM contracts to vendor table
- persist mapping rows

Those are the next incremental steps once vendor table is confirmed correct.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date
from pathlib import Path
from typing import Any, Optional

# Databento
import databento as db  # type: ignore
import pandas as pd

# MXM
from mxm_refdata.api.ref_data_api import RefDataAPI
from mxm_secrets import get_secret
from rich.console import Console
from rich.table import Table

from mxm.v1.marketdata.vendor_mapping.databento import (
    fetch_product_instruments_table,
    list_instruments_for_parent,
)
from mxm.v1.marketdata.vendor_mapping.product_roots import get_databento_product_root
from mxm.v1.marketdata.vendor_mapping.store_sqlite import (
    VendorContractMappingStoreSqlite,
)


def _parse_date(s: Optional[str]) -> Optional[date]:
    if s is None:
        return None
    return date.fromisoformat(s)


def _default_db_path() -> Path:
    # Align with the user's convention: ~/.mxm/marketdata/databento/...
    return Path.home() / ".mxm" / "marketdata" / "databento" / "vendor_mapping.sqlite3"


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _df_to_rich_table(df: pd.DataFrame, title: str) -> Table:
    table = Table(title=title, show_lines=False)
    for col in df.columns:
        table.add_column(str(col))
    for _, row in df.iterrows():
        table.add_row(*[("" if pd.isna(v) else str(v)) for v in row.values])
    return table


def _print_df(df: pd.DataFrame, *, title: str, fmt: str) -> None:
    if fmt == "plain":
        print(f"\n{title}\n{df.to_string(index=False)}")
        return
    console = Console()
    console.print(_df_to_rich_table(df, title=title))


def _contracts_to_df(
    contracts: list[Any], *, period_by_id: dict[str, Any]
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []

    for c in contracts:
        period_id = getattr(c, "period_id", None)
        p = period_by_id.get(period_id) if isinstance(period_id, str) else None

        year = (
            getattr(getattr(p, "first_date", None), "year", None)
            if p is not None
            else None
        )
        month = (
            getattr(getattr(p, "first_date", None), "month", None)
            if p is not None
            else None
        )

        rows.append(
            {
                "mxm_contract_id": getattr(c, "contract_id", None),
                "product_id": getattr(c, "product_id", None),
                "period_id": period_id,
                "year": year,
                "month": month,
                "first_day_of_interest": getattr(c, "first_day_of_interest", None),
                "last_trading_day": getattr(c, "last_trading_day", None),
            }
        )

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["year", "month", "period_id"], kind="stable").reset_index(
            drop=True
        )
    return df


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Map MXM futures contracts to Databento instruments (metadata-only proof harness)."
    )

    p.add_argument("--product-id", required=True)
    p.add_argument(
        "--as-of", default=None, help="ISO date (YYYY-MM-DD) for active-only filtering."
    )
    p.add_argument("--active-only", action="store_true", default=False)

    p.add_argument("--format", choices=["plain", "rich"], default="rich")

    p.add_argument(
        "--db-path",
        default=None,
        help="Override sqlite path (defaults to ~/.mxm/.../vendor_mapping.sqlite3)",
    )
    p.add_argument("--vendor", default="databento")

    # Metadata guardrail
    p.add_argument(
        "--max-instruments",
        type=int,
        default=5000,
        help="Abort if the parent enumerates more instruments than this (metadata safety guard).",
    )
    p.add_argument(
        "--no-fetch",
        action="store_true",
        default=False,
        help="Dry run: enumerate instrument count only; do not fetch definitions/normalize.",
    )

    # Output trimming
    p.add_argument(
        "--vendor-preview-rows",
        type=int,
        default=50,
        help="How many vendor rows to print as a preview.",
    )

    return p


def main() -> None:
    args = build_parser().parse_args()

    fmt: str = args.format
    product_id: str = args.product_id
    as_of: Optional[date] = _parse_date(args.as_of)

    # --- SQLite store (exists even if empty; proves wiring)
    db_path = Path(args.db_path) if args.db_path else _default_db_path()
    _ensure_parent_dir(db_path)
    store = VendorContractMappingStoreSqlite(db_path)

    # --- Refdata contracts
    ref = RefDataAPI()
    if args.active_only:
        if as_of is None:
            raise SystemExit("--active-only requires --as-of YYYY-MM-DD")
        contracts = ref.get_active_contracts(as_of_date=as_of, product_id=product_id)
        title = f"MXM active contracts for product_id={product_id} as_of={as_of.isoformat()}"
    else:
        contracts = ref.get_contracts_for_product(product_id)
        title = f"MXM all contracts for product_id={product_id}"

    period_by_id = {p.period_id: p for p in ref.get_periods()}

    df_mxm = _contracts_to_df(list(contracts), period_by_id=period_by_id)
    _print_df(df_mxm, title=title, fmt=fmt)

    # --- Existing mappings (likely empty)
    existing = store.get_rows_for_product(vendor=args.vendor, product_id=product_id)
    df_existing = (
        pd.DataFrame([asdict(r) for r in existing]) if existing else pd.DataFrame()
    )
    _print_df(
        df_existing if not df_existing.empty else pd.DataFrame(columns=["(empty)"]),
        title=(
            "Existing vendor mapping rows in sqlite "
            f"(vendor={args.vendor}, product_id={product_id}) @ {db_path}"
        ),
        fmt=fmt,
    )

    # --- Databento product -> parent mapping
    root = get_databento_product_root(product_id)
    dataset = root.dataset
    parent = root.parent

    print(f"\nDatabento product root mapping:")
    print(f"  product_id = {product_id}")
    print(f"  dataset    = {dataset}")
    print(f"  parent     = {parent}")
    print(f"  stype_in   = {root.stype_in}")

    # --- Databento client (secrets via mxm-secrets)
    api_key = get_secret("mxm/dev/databento/api-key")
    client = db.Historical(api_key)

    # --- Metadata guardrail: enumerate instrument count first
    inst_rows = list_instruments_for_parent(client, parent=parent, dataset=dataset)
    n_instruments = len(inst_rows)
    print(f"\nDatabento instruments under parent={parent}:")
    print(f"  n_instruments = {n_instruments}")
    print(f"  max_instruments = {args.max_instruments}")

    if n_instruments > int(args.max_instruments):
        raise SystemExit(
            f"ABORT: parent={parent} enumerated {n_instruments} instruments which exceeds "
            f"--max-instruments={args.max_instruments}. Narrow the parent, raise the cap, or add filtering."
        )

    if args.no_fetch:
        print(
            "\n--no-fetch set; stopping after instrument enumeration (no definitions fetch)."
        )
        return

    # --- Fetch definitions + normalize (metadata-side)
    # This calls:
    #   list_instruments_for_parent(...)
    #   get_instrument_definitions(...)
    #   normalize_instruments_with_definitions(...)
    df_vendor = fetch_product_instruments_table(client, dataset=dataset, parent=parent)

    # Output preview only
    preview_n = min(int(args.vendor_preview_rows), len(df_vendor))
    df_preview = df_vendor.head(preview_n).copy()

    _print_df(
        df_preview,
        title=f"Databento vendor table preview (first {preview_n} rows) for parent={parent}",
        fmt=fmt,
    )

    # Basic sanity counts
    print("\nDatabento vendor table summary:")
    print(f"  n_rows_total        = {len(df_vendor)}")
    if "expiration_date" in df_vendor:
        print(
            f"  n_with_expiration   = {int(df_vendor['expiration_date'].notna().sum())}"
        )
    if "exp_year" in df_vendor and "exp_month" in df_vendor:
        print(f"  n_with_exp_year     = {int(df_vendor['exp_year'].notna().sum())}")
        print(f"  n_with_exp_month    = {int(df_vendor['exp_month'].notna().sum())}")

    # Optional quick check: spreads often have '-' in raw_symbol; we will filter later
    if "raw_symbol" in df_vendor:
        n_spread_like = int(
            df_vendor["raw_symbol"].fillna("").str.contains("-", regex=False).sum()
        )
        print(f"  n_spread_like_raw_symbol (contains '-') = {n_spread_like}")

    print("\nNext step: join df_mxm (year, month) to df_vendor (exp_year, exp_month),")
    print("then persist VendorContractMappingRow rows into sqlite.")


if __name__ == "__main__":
    main()
