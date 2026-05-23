#!/usr/bin/env python3
"""
Human smoke-check for Session 18 contract selection.

This script is NOT a unit test. It is a CLI-oriented inspection tool to:
- run point-in-time contract selection (with explain surfaces)
- build a daily FuturesContractSeries-like step function:
      date -> selected relative contract_id (e.g. front month "M1")

It uses:
- RefDataAPI (mxm-refdata)
- TradingCalendarService (mxm-moneymachine)
- ContractSelectorEngine (mxm-moneymachine Session 18)

Usage examples
--------------
  poetry run python scripts/contracts/smoke_contract_selection.py \
    --product ES \
    --start 2026-01-01 --end 2026-06-30 \
    --rule M1

  poetry run python scripts/contracts/smoke_contract_selection.py \
    --product ES \
    --as-of 2026-02-11T12:00:00Z \
    --rule DEC1

Rules supported (in this script)
--------------------------------
- M1  : period_type=MONTH, no cycle filter, n=1
- M2  : period_type=MONTH, no cycle filter, n=2
- DEC1: period_type=MONTH, cycle=CALENDAR_MONTHS, elements={12}, n=1

You can extend this map as needed.

Exit code:
  0 = success
  1 = failure
"""

from __future__ import annotations

import argparse
from collections.abc import Iterable
from datetime import UTC, date, datetime

import pandas as pd

from mxm.moneymachine.calendars.service import TradingCalendarService
from mxm.moneymachine.contracts.engine import ContractSelectorEngine
from mxm.moneymachine.contracts.selectors import PeriodFilter, SelectorRule
from mxm.refdata.api.ref_data_api import RefDataAPI
from mxm.refdata.models.periods import PeriodType

# -----------------------------
# CLI parsing helpers
# -----------------------------


def _parse_day(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _parse_utc_ts(s: str) -> datetime:
    """
    Parse ISO-ish timestamps.

    Accepts:
      - "YYYY-MM-DD"             -> interpreted as 12:00Z
      - "YYYY-MM-DDTHH:MM:SSZ"   -> strict Z
      - "YYYY-MM-DDTHH:MM:SS+00:00" etc
    """
    if "T" not in s:
        d = _parse_day(s)
        return datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=UTC)
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _date_range_days(start: date, end: date) -> Iterable[date]:
    # inclusive end
    for d in pd.date_range(start, end, freq="D"):
        yield d.date()


# -----------------------------
# Rule presets (human-friendly)
# -----------------------------


def _rule_from_name(name: str) -> SelectorRule:
    name = name.strip().upper()

    if name == "M1":
        pf = PeriodFilter(
            period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None
        )
        return SelectorRule(period_filter=pf, n=1)

    if name == "M2":
        pf = PeriodFilter(
            period_type=PeriodType.MONTH, cycle_id=None, cycle_elements=None
        )
        return SelectorRule(period_filter=pf, n=2)

    if name == "DEC1":
        pf = PeriodFilter(
            period_type=PeriodType.MONTH,
            cycle_id="CALENDAR_MONTHS",
            cycle_elements=frozenset({12}),
        )
        return SelectorRule(period_filter=pf, n=1)

    raise ValueError(f"Unknown --rule {name!r}. Supported: M1, M2, DEC1")


# -----------------------------
# Timeseries builder
# -----------------------------


def build_contract_series(
    *,
    engine: ContractSelectorEngine,
    product_id: str,
    rule: SelectorRule,
    start: date,
    end: date,
) -> pd.Series:
    """
    Build a daily series: index=date, value=contract_id for the selected rule.

    This is a simple "FuturesContractSeries" step function.
    The value changes when the engine selection changes.
    """
    idx = []
    vals = []

    for d in _date_range_days(start, end):
        # Use a consistent midday timestamp to avoid timezone boundary weirdness.
        ts = datetime(d.year, d.month, d.day, 12, 0, 0, tzinfo=UTC)
        cid = engine.select(product_id, ts, rule)
        idx.append(pd.Timestamp(d))
        vals.append(cid)

    s = pd.Series(
        vals,
        index=pd.DatetimeIndex(idx, name="date"),
        name=f"{product_id}:{_rule_label(rule)}",
    )
    return s


def _rule_label(rule: SelectorRule) -> str:
    pf = rule.period_filter
    if pf.cycle_id is None:
        return f"{pf.period_type.name}:n={rule.n}"
    elems = ",".join(str(x) for x in sorted(pf.cycle_elements or ()))
    return f"{pf.period_type.name}:{pf.cycle_id}[{elems}]:n={rule.n}"


# -----------------------------
# Printing / inspection
# -----------------------------


def print_point_in_time(
    *,
    engine: ContractSelectorEngine,
    product_id: str,
    as_of_ts: datetime,
    rule: SelectorRule,
) -> None:
    exp = engine.explain(product_id, as_of_ts, rule)

    print("== selection ==")
    print(f"product_id     : {exp.product_id}")
    print(f"as_of_utc      : {exp.as_of_utc}")
    print(f"as_of_session  : {exp.as_of_session}")
    print(f"rule           : {_rule_label(rule)}")
    print(f"outcome        : {exp.outcome}")

    if exp.outcome == "selected":
        print(f"selected       : {exp.selected_contract_id}")
    else:
        print(f"failure_type   : {exp.failure_type}")
        print(f"message        : {exp.message}")

    # details are your “audit crumbs”
    print("details:")
    for k, v in exp.details.items():
        print(f"  - {k}: {v}")


def print_series_summary(s: pd.Series, *, max_changes: int = 25) -> None:
    print("== series ==")
    print(f"name   : {s.name}")
    print(f"range  : {s.index.min().date()} .. {s.index.max().date()}  ({len(s)} days)")
    print(f"unique : {s.nunique()} contracts")

    # show change points
    changes = s[s != s.shift(1)]
    print(f"changes: {len(changes)}")
    print("first change points:")
    for i, (dt, cid) in enumerate(changes.iloc[:max_changes].items(), start=1):
        print(f"  {i:>2}. {dt.date()} -> {cid}")


# -----------------------------
# Main
# -----------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Human smoke-check for MXM moneymachine contract selection (Session 18)."
    )

    parser.add_argument("--product", required=True, help="MXM product_id, e.g. ES")
    parser.add_argument("--rule", default="M1", help="Rule preset: M1, M2, DEC1")

    parser.add_argument(
        "--as-of",
        default=None,
        help="Point-in-time selection timestamp (ISO). If set, prints explain() output.",
    )

    parser.add_argument(
        "--start", default=None, help="Start day YYYY-MM-DD for series build"
    )
    parser.add_argument(
        "--end", default=None, help="End day YYYY-MM-DD for series build"
    )

    parser.add_argument(
        "--csv",
        default=None,
        help="Optional path to write the series as CSV (date, contract_id).",
    )

    args = parser.parse_args()

    product_id = args.product
    rule = _rule_from_name(args.rule)

    refdata = RefDataAPI()
    calendars = TradingCalendarService(
        refdata_api=refdata
    )  # adjust if your ctor differs
    engine = ContractSelectorEngine.build(refdata=refdata, calendars=calendars)

    did_something = False

    if args.as_of is not None:
        as_of_ts = _parse_utc_ts(args.as_of)
        print_point_in_time(
            engine=engine, product_id=product_id, as_of_ts=as_of_ts, rule=rule
        )
        did_something = True

    if args.start is not None and args.end is not None:
        start = _parse_day(args.start)
        end = _parse_day(args.end)
        if start > end:
            raise ValueError("start must be <= end")

        s = build_contract_series(
            engine=engine, product_id=product_id, rule=rule, start=start, end=end
        )
        print_series_summary(s)

        if args.csv:
            df = s.rename("contract_id").to_frame()
            df.to_csv(args.csv, index=True)
            print(f"Wrote CSV: {args.csv}")

        did_something = True

    if not did_something:
        print("Nothing to do. Provide --as-of and/or --start/--end.")
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
