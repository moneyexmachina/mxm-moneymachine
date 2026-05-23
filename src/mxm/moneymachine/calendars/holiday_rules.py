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
    Compute Gregorian Easter Sunday using the Anonymous Gregorian algorithm.

    This implementation is:
    - deterministic,
    - dependency-free,
    - valid for Gregorian calendar years.

    References:
    - Meeus/Jones/Butcher Gregorian computus
    - "Anonymous Gregorian algorithm"

    Args:
        year:
            Gregorian calendar year.

    Returns:
        Easter Sunday as a ``datetime.date``.
    """
    golden_number = year % 19

    century = year // 100
    year_of_century = year % 100

    leap_year_correction = century // 4
    century_remainder = century % 4

    lunar_correction = (century + 8) // 25
    solar_correction = (century - lunar_correction + 1) // 3

    paschal_full_moon_offset = (
        19 * golden_number + century - leap_year_correction - solar_correction + 15
    ) % 30

    year_quarter = year_of_century // 4
    year_remainder = year_of_century % 4

    weekday_offset = (
        32
        + 2 * century_remainder
        + 2 * year_quarter
        - paschal_full_moon_offset
        - year_remainder
    ) % 7

    epact_correction = (
        golden_number + 11 * paschal_full_moon_offset + 22 * weekday_offset
    ) // 451

    easter_month = (
        paschal_full_moon_offset + weekday_offset - 7 * epact_correction + 114
    ) // 31

    easter_day = (
        (paschal_full_moon_offset + weekday_offset - 7 * epact_correction + 114) % 31
    ) + 1

    return dt.date(year, easter_month, easter_day)


def us_full_closure_holidays_minimal(year: int) -> set[dt.date]:
    """
    Minimal full-closure holiday set per MXM V1 projection rule.
    Produces *observed* dates for fixed-date holidays.

    Includes:
    - New Year's Day
    - MLK Day (3rd Mon Jan)
    - Presidents' Day (3rd Mon Feb)
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
