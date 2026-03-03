from __future__ import annotations

"""
Smoke script: build and inspect a ContractSeries.

Usage:

    poetry run python scripts/contracts/smoke_contract_series.py \
        --product-id cme_emini_snp500_futures \
        --start 2025-01-02 \
        --end 2025-02-28

Defaults:
    - period_type = MONTH
    - unfiltered cycle (all listed)
    - n = 1
"""

import argparse
import sys
from typing import Sequence

import numpy as np
from mxm_refdata.api.ref_data_api import RefDataAPI
from mxm_refdata.models.periods import PeriodType

from mxm.v1.calendars.service import TradingCalendarService
from mxm.v1.contracts.contract_series import (
    ContractSeriesSpec,
    build_contract_series,
)
from mxm.v1.contracts.engine import ContractSelectorEngine
from mxm.v1.contracts.selectors import PeriodFilter, SelectorRule

# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke ContractSeries build")

    p.add_argument("--product-id", required=True)
    p.add_argument("--start", required=True, help="YYYY-MM-DD")
    p.add_argument("--end", required=True, help="YYYY-MM-DD")

    p.add_argument(
        "--n",
        type=int,
        default=1,
        help="Selector depth (default: 1)",
    )

    return p.parse_args(argv)


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    product_id = args.product_id
    start = np.datetime64(args.start)
    end = np.datetime64(args.end)
    n = args.n

    # --- Build real services ---
    refdata = RefDataAPI()
    calendars = TradingCalendarService(refdata_api=refdata)
    engine = ContractSelectorEngine.build(refdata=refdata, calendars=calendars)

    # --- Rule: unfiltered monthly, depth n ---
    pf = PeriodFilter(period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None)
    rule = SelectorRule(period_filter=pf, n=n)

    spec = ContractSeriesSpec(
        product_id=product_id,
        rule=rule,
        start_session=start,
        end_session=end,
    )

    print("=" * 72)
    print("Building ContractSeries")
    print(f"product_id: {product_id}")
    print(f"start:      {start}")
    print(f"end:        {end}")
    print(f"rule short: {rule}")
    print("=" * 72)

    series = build_contract_series(
        engine=engine,
        calendar_service=calendars,
        spec=spec,
    )

    print()
    print("Rule labels")
    print(f"  canonical: {series.canonical_relative_id}")
    print(f"  short:     {series.short_rel_id}")
    print()

    print("Range")
    print(f"  sessions: {len(series.sessions)}")
    print(f"  first:    {series.sessions[0]}")
    print(f"  last:     {series.sessions[-1]}")
    print()

    print("Head (first 10 rows)")
    for s, cid in list(zip(series.sessions, series.contract_ids))[:10]:
        print(f"  {s}  ->  {cid}")

    switches = series.switch_view(max_rows=50)
    print()
    print(f"Switch count: {len(switches)}")
    for s, c0, c1 in switches:
        print(f"  {s} : {c0}  ->  {c1}")

    print("=" * 72)
    print("Done.")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
