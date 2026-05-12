"""
MXM V1 — Trading Calendar Inspection & Rendering.

This module provides **human-facing inspection utilities** for trading
calendar artifacts that have already been built and registered.

Its responsibilities are intentionally limited to:
- discovering available calendars via the registry,
- describing calendar provenance and coverage,
- rendering trading calendars in readable textual form
  (e.g. month or range views, similar to `cal(1)`).

This module does **not**:
- build or modify calendar data,
- reconcile calendars against market data,
- depend on downstream marketdata APIs.

Design intent:
- Inspection is read-only and side-effect free.
- Output is deterministic and suitable for CLI / ops use.
- Rendering logic is explicit and simple, prioritising clarity
  over visual richness.

Future work (explicitly out of scope here):
- reconciliation against OHLCV or execution data,
- graphical or web-based calendar views,
- product- or contract-specific overlays.
"""

from __future__ import annotations

import calendar as _cal
import datetime as dt
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from mxm.v1.calendars.loader import calendars_root, load_calendar, registry_path
from mxm.v1.calendars.models import TradingCalendar
from mxm.v1.calendars.registry import (
    CalendarRegistryEntry,
    load_calendar_registry,
    validate_registry_entry,
)
from mxm.v1.utils.date_utils import coerce_np_day, day_in_set, fmt_iso_day

# ----------------------------
# Models
# ----------------------------


@dataclass(frozen=True, slots=True)
class CalendarSummary:
    calendar_id: str
    observed_start: np.datetime64
    observed_end: np.datetime64
    projection_start: np.datetime64
    projection_end: np.datetime64
    observed_source_kind: str
    projection_rule_id: str


# ----------------------------
# Registry discovery / description
# ----------------------------


def list_calendars(*, root: Path | None = None) -> list[str]:
    """
    List calendar_ids available in the calendar registry.

    Returns an empty list if the registry file does not exist.
    """
    cal_root = calendars_root() if root is None else root
    reg_path = registry_path(cal_root)
    if not reg_path.exists():
        return []
    reg = load_calendar_registry(reg_path)
    return sorted(reg.keys())


def load_calendar_entry(
    calendar_id: str, *, root: Path | None = None
) -> CalendarRegistryEntry:
    """
    Load and validate a single registry entry.
    """
    cal_root = calendars_root() if root is None else root
    reg_path = registry_path(cal_root)
    reg = load_calendar_registry(reg_path)
    if calendar_id not in reg:
        raise KeyError(f"calendar_id not found in registry: {calendar_id}")
    entry = reg[calendar_id]
    validate_registry_entry(entry)
    return entry


def summarize_calendar(
    calendar_id: str, *, root: Path | None = None
) -> CalendarSummary:
    """
    Return a compact summary of provenance and coverage for one calendar.
    """
    entry = load_calendar_entry(calendar_id, root=root)

    return CalendarSummary(
        calendar_id=entry.calendar_id,
        observed_start=entry.observed.start,
        observed_end=entry.observed.end,
        projection_start=entry.projection.start,
        projection_end=entry.projection.end,
        observed_source_kind=entry.source.kind,
        projection_rule_id=entry.projection.rule_id,
    )


def describe_calendar(calendar_id: str, *, root: Path | None = None) -> str:
    """
    Produce a human-readable description of a calendar entry and its artifacts.
    """
    entry = load_calendar_entry(calendar_id, root=root)

    lines: list[str] = []
    lines.append(f"calendar_id:      {entry.calendar_id}")
    lines.append(f"source.kind:      {entry.source.kind}")

    if entry.source.spec:
        lines.append("source.spec:")
        for k in sorted(entry.source.spec.keys()):
            v = entry.source.spec[k]
            lines.append(f"  {k}: {v!r}")

    lines.append("")
    lines.append("observed:")
    lines.append(f"  start:          {entry.observed.start}")
    lines.append(f"  end:            {entry.observed.end}")
    lines.append(f"  trading_days:   {entry.observed.trading_days_artifact}")
    lines.append(f"  schedule:       {entry.observed.schedule_artifact}")
    lines.append(f"  sha256.days:    {entry.observed.sha256_trading_days}")
    lines.append(f"  sha256.schedule:{entry.observed.sha256_schedule}")

    lines.append("")
    lines.append("projection:")
    lines.append(f"  rule_id:        {entry.projection.rule_id}")
    lines.append(f"  start:          {entry.projection.start}")
    lines.append(f"  end:            {entry.projection.end}")
    lines.append(f"  trading_days:   {entry.projection.trading_days_artifact}")
    lines.append(f"  sha256.days:    {entry.projection.sha256_trading_days}")

    lines.append("")
    lines.append(f"generated_at:     {entry.generated_at}")

    if entry.builder is not None:
        lines.append("")
        lines.append("builder:")
        lines.append(f"  builder_id:     {entry.builder.builder_id}")
        lines.append(f"  mxm_version:    {entry.builder.mxm_version!r}")
        if entry.builder.params:
            lines.append("  params:")
            for k in sorted(entry.builder.params.keys()):
                lines.append(f"    {k}: {entry.builder.params[k]!r}")

    return "\n".join(lines)


# ----------------------------
# Rendering primitives
# ----------------------------


def render_month(
    calendar: TradingCalendar,
    *,
    year: int,
    month: int,
    mark_projected: bool = True,
) -> str:
    """
    Render a month view similar to `cal(1)`.

    Marking:
      - trading day: show day number (2 digits)
      - non-trading day: '..'
      - projected trading day (optional): append '*' (e.g. '05*')

    Output uses a Monday-first week header: Mo Tu We Th Fr Sa Su
    """
    # Build a set for membership tests (fast enough for monthly views)

    tdays_set: set[np.datetime64] = {
        d.astype("datetime64[D]") for d in calendar.trading_days
    }
    obs_end = calendar.observed_end.astype("datetime64[D]")

    first_weekday, n_days = _cal.monthrange(year, month)  # Monday=0..Sunday=6
    # calendar.monthrange uses Monday=0; we want Monday-first, so this aligns.

    # Header
    title = f"{_cal.month_name[month]} {year}"
    lines: list[str] = []
    lines.append(title)
    lines.append("Mo Tu We Th Fr Sa Su")

    # Build grid
    # first_weekday is the weekday of day=1 (Mon=0..Sun=6)
    week: list[str] = ["  "] * 7
    day = 1

    # Fill leading blanks
    for wd in range(first_weekday):
        week[wd] = "  "

    while day <= n_days:
        wd = dt.date(year, month, day).weekday()  # Mon=0..Sun=6
        d64 = np.datetime64(dt.date(year, month, day), "D")

        if day_in_set(d64, tdays_set):
            # Trading day
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

    # Flush last week if not already flushed
    if any(cell.strip() for cell in week):
        # replace blanks with spaces for consistent layout
        week = [cell if cell.strip() else "  " for cell in week]
        lines.append(" ".join(week))

    return "\n".join(lines)


def render_range(
    calendar: TradingCalendar,
    *,
    start: object,
    end: object,
    columns: int = 7,
    mark_projected: bool = True,
) -> str:
    """
    Render a compact range view.

    Each day is rendered as:
      - 'YYYY-MM-DD' for trading days
      - 'YYYY-MM-DD*' for projected trading days (optional)

    Non-trading days are omitted (this is a trading-day view).
    """
    s = coerce_np_day(start)
    e = coerce_np_day(end)
    s2 = calendar.normalize(s, how="next")
    e2 = calendar.normalize(e, how="prev")
    if e2 < s2:
        raise ValueError(f"end < start: start={fmt_iso_day(s)} end={fmt_iso_day(e)}")

    tdays = calendar.trading_days_between(s2, e2, strict=True)
    obs_end = calendar.observed_end.astype("datetime64[D]")

    tokens: list[str] = []
    for d in tdays.tolist():
        dd = np.datetime64(d, "D")
        tok = fmt_iso_day(dd)
        if mark_projected and dd > obs_end:
            tok += "*"
        tokens.append(tok)

    # columnize
    if columns <= 0:
        columns = 7

    lines: list[str] = []
    for i in range(0, len(tokens), columns):
        lines.append("  ".join(tokens[i : i + columns]))
    return "\n".join(lines)


# ----------------------------
# Convenience: render by calendar_id
# ----------------------------


def render_month_by_id(
    calendar_id: str,
    *,
    year: int,
    month: int,
    root: Path | None = None,
    mark_projected: bool = True,
) -> str:
    cal = load_calendar(calendar_id, root=root)
    return render_month(cal, year=year, month=month, mark_projected=mark_projected)


def render_range_by_id(
    calendar_id: str,
    *,
    start: object,
    end: object,
    root: Path | None = None,
    columns: int = 7,
    mark_projected: bool = True,
) -> str:
    cal = load_calendar(calendar_id, root=root)
    return render_range(
        cal, start=start, end=end, columns=columns, mark_projected=mark_projected
    )


"""
MXM V1 — Trading Calendar Inspection & Rendering.

This module provides **human-facing inspection utilities** for trading
calendar artifacts that have already been built and registered.

Its responsibilities are intentionally limited to:
- discovering available calendars via the registry,
- describing calendar provenance and coverage,
- rendering trading calendars in readable textual form
  (e.g. month or range views, similar to `cal(1)`).

This module does **not**:
- build or modify calendar data,
- reconcile calendars against market data,
- depend on downstream marketdata APIs.

Design intent:
- Inspection is read-only and side-effect free.
- Output is deterministic and suitable for CLI / ops use.
- Rendering logic is explicit and simple, prioritising clarity
  over visual richness.

Future work (explicitly out of scope here):
- reconciliation against OHLCV or execution data,
- graphical or web-based calendar views,
- product- or contract-specific overlays.

This separation ensures that calendar inspection can be used safely
and early in the MXM V1 lifecycle, independent of downstream data layers.
"""
