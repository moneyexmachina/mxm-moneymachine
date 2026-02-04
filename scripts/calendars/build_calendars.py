from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

from mxm.v1.calendars.builders import build_exchange_calendars_v1


@dataclass(frozen=True, slots=True)
class CalendarBuildSpec:
    calendar_id: str
    exchange_calendar_name: str
    projection_years: int = 2


# V1 build set (explicit, diffable)
V1_CALENDARS: dict[str, CalendarBuildSpec] = {
    "cmes": CalendarBuildSpec(
        calendar_id="cmes", exchange_calendar_name="CMES", projection_years=2
    ),
    # Add more here as you expand:
    # "xnys": CalendarBuildSpec(calendar_id="xnys", exchange_calendar_name="XNYS", projection_years=2),
}


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="build_calendars", description="Build MXM V1 calendar refdata artifacts"
    )

    p.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Calendars refdata root (defaults to ~/.mxm/refdata/calendars)",
    )
    p.add_argument(
        "--only",
        action="append",
        default=[],
        help="Build only the specified calendar_id(s). Can be repeated.",
    )
    p.add_argument(
        "--projection-years",
        type=int,
        default=None,
        help="Override projection horizon for all calendars (default: per-calendar spec).",
    )

    return p.parse_args()


def main() -> int:
    ns = _parse_args()

    only: set[str] = set(ns.only) if ns.only else set(V1_CALENDARS.keys())
    unknown = sorted([x for x in only if x not in V1_CALENDARS])
    if unknown:
        raise SystemExit(f"Unknown calendar_id(s): {', '.join(unknown)}")

    root: Path | None = ns.root
    override_py: int | None = ns.projection_years

    built: list[str] = []

    for cid in sorted(only):
        spec = V1_CALENDARS[cid]
        py = override_py if override_py is not None else spec.projection_years

        print(
            f"[build] {cid}  source=exchange_calendars:{spec.exchange_calendar_name}  projection_years={py}"
        )
        build_exchange_calendars_v1(
            calendar_id=spec.calendar_id,
            exchange_calendar_name=spec.exchange_calendar_name,
            projection_years=py,
            root=root,
        )
        built.append(cid)

    print("")
    print(f"Built {len(built)} calendar(s): {', '.join(built)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
