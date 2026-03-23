from __future__ import annotations

"""
Smoke script: build and inspect the runtime MXM business calendar.

Usage examples:

    poetry run python scripts/calendars/smoke_mxm_business_calendar.py \
        --base-calendar-id cmes

    poetry run python scripts/calendars/smoke_mxm_business_calendar.py \
        --base-calendar-id cmes \
        --show-month 2010-07 \
        --show-month 2010-11 \
        --show-range 2010-07-01:2010-07-15

This is a human inspection tool, not a regression test.
"""

import argparse
import calendar as _cal
import datetime as dt
import sys
from pathlib import Path
from typing import Sequence

import numpy as np

from mxm.v1.calendars.mxm_business_calendar import MxMBusinessCalendar
from mxm.v1.calendars.mxm_business_calendar_service import MxMBusinessCalendarService
from mxm.v1.utils.date_utils import coerce_np_day, fmt_iso_day


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Smoke MXM business calendar")

    p.add_argument(
        "--base-calendar-id",
        required=True,
        help="TradingCalendar id used as the base input to MXM business calendar construction",
    )
    p.add_argument(
        "--business-calendar-id",
        default="mxm_v1_business",
        help="Runtime id to assign to the MXM business calendar (default: mxm_v1_business)",
    )
    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Calendars refdata root (defaults to ~/.mxm/refdata/calendars)",
    )
    p.add_argument(
        "--show-month",
        action="append",
        default=[],
        help="Render month view for YYYY-MM. Can be repeated.",
    )
    p.add_argument(
        "--show-range",
        action="append",
        default=[],
        help="Render business-day range for START:END (YYYY-MM-DD:YYYY-MM-DD). Can be repeated.",
    )
    p.add_argument(
        "--columns",
        type=int,
        default=7,
        help="Columns for range rendering (default: 7)",
    )

    return p.parse_args(argv)


def _month_view(
    calendar: MxMBusinessCalendar,
    *,
    year: int,
    month: int,
    mark_projected: bool = True,
) -> str:
    bdays_set: set[np.datetime64] = {
        d.astype("datetime64[D]") for d in calendar.business_days
    }
    obs_end = calendar.observed_end.astype("datetime64[D]")

    first_weekday, n_days = _cal.monthrange(year, month)

    title = f"{_cal.month_name[month]} {year}"
    lines: list[str] = [title, "Mo Tu We Th Fr Sa Su"]

    week: list[str] = ["  "] * 7
    day = 1

    for wd in range(first_weekday):
        week[wd] = "  "

    while day <= n_days:
        wd = dt.date(year, month, day).weekday()
        d64 = np.datetime64(dt.date(year, month, day), "D")

        if d64 in bdays_set:
            s = f"{day:02d}"
            if mark_projected and d64 > obs_end:
                s = s + "*"
            week[wd] = s
        else:
            week[wd] = ".."

        if wd == 6:
            lines.append(" ".join(week))
            week = ["  "] * 7
        day += 1

    if any(cell.strip() for cell in week):
        week = [cell if cell.strip() else "  " for cell in week]
        lines.append(" ".join(week))

    return "\n".join(lines)


def _range_view(
    calendar: MxMBusinessCalendar,
    *,
    start: str,
    end: str,
    columns: int = 7,
    mark_projected: bool = True,
) -> str:
    s = coerce_np_day(start)
    e = coerce_np_day(end)

    s2 = calendar.normalize(s, how="next")
    e2 = calendar.normalize(e, how="prev")
    if e2 < s2:
        raise ValueError(f"end < start after normalization: start={s2} end={e2}")

    days = calendar.business_days_between(
        s2,
        e2,
        strict=True,
        inclusive="both",
    )

    obs_end = calendar.observed_end.astype("datetime64[D]")

    tokens: list[str] = []
    for d in days.tolist():
        dd = np.datetime64(d, "D")
        tok = fmt_iso_day(dd)
        if mark_projected and dd > obs_end:
            tok += "*"
        tokens.append(tok)

    if columns <= 0:
        columns = 7

    lines: list[str] = []
    for i in range(0, len(tokens), columns):
        lines.append("  ".join(tokens[i : i + columns]))
    return "\n".join(lines)


def _print_summary(
    calendar: MxMBusinessCalendar,
    *,
    base_calendar_id: str,
) -> None:
    print("=" * 72)
    print("MXM Business Calendar")
    print(f"base_calendar_id:     {base_calendar_id}")
    print(f"business_calendar_id: {calendar.calendar_id}")
    print(f"first_business_day:   {calendar.business_days[0]}")
    print(f"observed_end:         {calendar.observed_end}")
    print(f"last_business_day:    {calendar.business_days[-1]}")
    print(f"n_business_days:      {len(calendar.business_days)}")
    print("=" * 72)
    print()


def _parse_year_month(value: str) -> tuple[int, int]:
    try:
        y_str, m_str = value.split("-")
        year = int(y_str)
        month = int(m_str)
    except Exception as e:
        raise ValueError(
            f"Invalid --show-month value {value!r}; expected YYYY-MM"
        ) from e

    if not (1 <= month <= 12):
        raise ValueError(f"Invalid month in --show-month: {value!r}")

    return year, month


def _parse_range(value: str) -> tuple[str, str]:
    try:
        start, end = value.split(":")
    except Exception as e:
        raise ValueError(
            f"Invalid --show-range value {value!r}; expected YYYY-MM-DD:YYYY-MM-DD"
        ) from e
    return start, end


def main(argv: Sequence[str]) -> int:
    args = parse_args(argv)

    svc = MxMBusinessCalendarService(
        base_trading_calendar_id=args.base_calendar_id,
        calendars_root=args.root,
        business_calendar_id=args.business_calendar_id,
    )
    calendar = svc.get_calendar()

    _print_summary(
        calendar,
        base_calendar_id=args.base_calendar_id,
    )

    for ym in args.show_month:
        year, month = _parse_year_month(ym)
        print(_month_view(calendar, year=year, month=month))
        print()

    for raw_range in args.show_range:
        start, end = _parse_range(raw_range)
        print(f"Range {start} -> {end}")
        print(
            _range_view(
                calendar,
                start=start,
                end=end,
                columns=args.columns,
            )
        )
        print()

    print("=" * 72)
    print("Done.")
    print("=" * 72)

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
