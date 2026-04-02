"""
MXM V1 — Calendar Holiday Rules.

This module defines **deterministic holiday rule functions** used across the
MXM calendar system.

Scope:
- Provides a minimal, dependency-free implementation of US federal-style
  market closure holidays.
- Supports:
    - TradingCalendar projection (builder layer)

Design principles:
- Pure functions: no IO, no external dependencies, no hidden state.
- Deterministic and reproducible across environments.
- Explicit rule definitions (no reliance on third-party holiday packages).
- Suitable for both historical reconstruction and forward projection.

Current rule set:
- "us_full_closure_holidays_minimal"
  A deliberately minimal set of full-day market closures aligned with
  major US exchange holidays (e.g. CME equities futures).

Notes:
- This is not intended to be a complete exchange holiday specification.
  It omits:
    - early closes
    - ad hoc closures
    - product-specific exceptions
- It is sufficient for:
    - calendar projection beyond observed data
    - first-pass MXM business calendar construction

Future extensions may include:
- richer holiday sets (per venue or asset class)
- partial-day / early-close modelling
- explicit "settlement calendars"
- versioned rule identifiers for reproducibility
"""

import datetime as dt

# ----------------------------
# holiday rules (minimal US set)
# ----------------------------


def observed_fixed_date_holiday(d: dt.date) -> dt.date:
    """
    Apply simple US-style observance for fixed-date holidays:
    - If holiday falls on Saturday -> observed Friday
    - If holiday falls on Sunday   -> observed Monday
    - Otherwise observed on the day
    """
    wd = d.weekday()  # Mon=0 ... Sun=6
    if wd == 5:  # Saturday
        return d - dt.timedelta(days=1)
    if wd == 6:  # Sunday
        return d + dt.timedelta(days=1)
    return d


def nth_weekday_of_month(year: int, month: int, weekday: int, n: int) -> dt.date:
    """
    Return the n-th weekday in a month. weekday: Mon=0..Sun=6.
    Example: third Monday in Jan => weekday=0, n=3
    """
    first = dt.date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    day = 1 + offset + (n - 1) * 7
    return dt.date(year, month, day)


def last_weekday_of_month(year: int, month: int, weekday: int) -> dt.date:
    """
    Return the last weekday in a month. weekday: Mon=0..Sun=6.
    Example: last Monday in May => weekday=0
    """
    # go to first day of next month, step back
    if month == 12:
        next_month = dt.date(year + 1, 1, 1)
    else:
        next_month = dt.date(year, month + 1, 1)
    d = next_month - dt.timedelta(days=1)
    while d.weekday() != weekday:
        d -= dt.timedelta(days=1)
    return d


def easter_sunday_gregorian(year: int) -> dt.date:
    """
    Compute Easter Sunday (Gregorian calendar) using Anonymous Gregorian algorithm.
    Deterministic and dependency-free.
    """
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def us_full_closure_holidays_minimal(year: int) -> set[dt.date]:
    """
    Minimal full-closure holiday set per MXM V1 projection rule.
    Produces *observed* dates for fixed-date holidays.

    Includes:
    - New Year's Day
    - MLK Day (3rd Mon Jan)
    - Presidents’ Day (3rd Mon Feb)
    - Good Friday
    - Memorial Day (last Mon May)
    - Juneteenth (from 2021 onward)
    - Independence Day
    - Labor Day (1st Mon Sep)
    - Thanksgiving (4th Thu Nov)
    - Christmas Day
    """
    out: set[dt.date] = set()

    # Fixed-date (observed)
    out.add(observed_fixed_date_holiday(dt.date(year, 1, 1)))  # New Year's
    if year >= 2021:
        out.add(observed_fixed_date_holiday(dt.date(year, 6, 19)))  # Juneteenth
    out.add(observed_fixed_date_holiday(dt.date(year, 7, 4)))  # Independence Day
    out.add(observed_fixed_date_holiday(dt.date(year, 12, 25)))  # Christmas

    # Nth/last weekday holidays
    out.add(nth_weekday_of_month(year, 1, weekday=0, n=3))  # MLK: 3rd Monday Jan
    out.add(nth_weekday_of_month(year, 2, weekday=0, n=3))  # Presidents: 3rd Monday Feb
    out.add(last_weekday_of_month(year, 5, weekday=0))  # Memorial: last Monday May
    out.add(nth_weekday_of_month(year, 9, weekday=0, n=1))  # Labor: 1st Monday Sep
    out.add(
        nth_weekday_of_month(year, 11, weekday=3, n=4)
    )  # Thanksgiving: 4th Thursday Nov

    # Good Friday
    easter = easter_sunday_gregorian(year)
    out.add(easter - dt.timedelta(days=2))

    return out
