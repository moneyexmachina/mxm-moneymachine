from __future__ import annotations

import argparse
from pathlib import Path

from mxm.moneymachine.calendars.inspect import (
    describe_calendar,
    list_calendars,
    render_month_by_id,
    render_range_by_id,
)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="mxm-v1-calendars", description="MXM V1 calendar inspection tools"
    )

    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Calendars refdata root (defaults to ~/.mxm/refdata/calendars)",
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("ls", help="List calendars in registry")

    p_show = sub.add_parser("show", help="Describe a calendar registry entry")
    p_show.add_argument("calendar_id", type=str)

    p_cal = sub.add_parser("cal", help="Render a month view")
    p_cal.add_argument("calendar_id", type=str)
    p_cal.add_argument("year", type=int)
    p_cal.add_argument("month", type=int)

    p_range = sub.add_parser(
        "range", help="Render a trading-day range view (trading days only)"
    )
    p_range.add_argument("calendar_id", type=str)
    p_range.add_argument("start", type=str, help="Start date (YYYY-MM-DD)")
    p_range.add_argument("end", type=str, help="End date (YYYY-MM-DD)")
    p_range.add_argument("--columns", type=int, default=7)

    return p.parse_args()


def main() -> int:
    ns = _parse_args()

    root: Path | None = ns.root

    if ns.cmd == "ls":
        ids = list_calendars(root=root)
        if not ids:
            print("(no calendars found)")
            return 0
        for cid in ids:
            print(cid)
        return 0

    if ns.cmd == "show":
        print(describe_calendar(ns.calendar_id, root=root))
        return 0

    if ns.cmd == "cal":
        print(
            render_month_by_id(ns.calendar_id, year=ns.year, month=ns.month, root=root)
        )
        return 0

    if ns.cmd == "range":
        print(
            render_range_by_id(
                ns.calendar_id,
                start=ns.start,
                end=ns.end,
                columns=ns.columns,
                root=root,
            )
        )
        return 0

    raise RuntimeError(f"Unhandled command: {ns.cmd}")


if __name__ == "__main__":
    raise SystemExit(main())
