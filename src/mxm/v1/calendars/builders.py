"""
MXM V1 — Trading Calendar Builders.

This module contains **operational builders** responsible for generating
calendar refdata artifacts and updating the calendar registry.

Builders are **write-side, ops-only code**. They are permitted to:
- depend on upstream data sources (e.g. `exchange_calendars`),
- perform date generation and projection logic,
- write parquet artifacts and update registry YAML,
- compute and record provenance and checksums.

Builders are **not** used at runtime. All runtime calendar access must go
through pre-materialised artifacts loaded via `calendars.loader`.

Design principles:
- Calendars are treated as **data**, not dynamic code paths.
- Observed calendars are authoritative where available.
- Future calendars may be projected, but only via explicit, versioned rules.
- All outputs are deterministic, auditable, and diffable.

This module currently provides a V1 builder that sources observed schedules
from the `exchange_calendars` package and extends them via a minimal,
transparent projection rule.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata
from pathlib import Path

import numpy as np
import pandas as pd

from mxm.v1.calendars.holiday_rules import us_full_closure_holidays_minimal
from mxm.v1.calendars.loader import (
    calendar_dir,
    calendars_root,
    registry_path,
)
from mxm.v1.calendars.registry import (
    BuilderInfo,
    CalendarRegistryEntry,
    CalendarRegistryError,
    ObservedSection,
    ProjectionSection,
    SourceInfo,
    load_calendar_registry,
    write_calendar_registry,
)
from mxm.v1.utils.hashing import sha256_file


def _project_trading_days_minimal_us(
    *,
    start_exclusive: np.datetime64,
    projection_years: int,
) -> np.ndarray:
    """
    Project trading days beyond observed_end using weekday rule and minimal US holiday set.
    """

    start_day = pd.Timestamp(start_exclusive.astype("datetime64[D]")) + pd.Timedelta(
        days=1
    )
    end_day = start_day + pd.DateOffset(years=projection_years)

    # Weekdays only (Mon-Fri)
    bdays = pd.date_range(start=start_day, end=end_day, freq="B")

    years = range(start_day.year, end_day.year + 1)
    holidays: set[dt.date] = set()
    for y in years:
        holidays |= us_full_closure_holidays_minimal(y)

    keep = [d for d in bdays if d.date() not in holidays]
    if not keep:
        raise CalendarRegistryError(
            "Projected trading days are empty; check projection parameters"
        )

    arr = np.array([np.datetime64(d.date(), "D") for d in keep], dtype="datetime64[D]")
    if np.any(arr[1:] <= arr[:-1]):
        raise CalendarRegistryError(
            "Projected trading days are not strictly increasing (unexpected)"
        )
    return arr


# ----------------------------
# parquet writers
# ----------------------------


def _write_trading_days_parquet(path: Path, days: np.ndarray) -> None:
    df = pd.DataFrame({"day": pd.to_datetime(days.astype("datetime64[D]"))})
    # ensure stable schema: one column, no index
    df.to_parquet(path, index=False)


def _write_schedule_parquet(path: Path, schedule: pd.DataFrame) -> None:
    """
    Persist observed schedule with UTC open/close timestamps.

    Stored columns:
      - session   (datetime64[ns])  : label at UTC midnight (naive)
      - open_utc  (datetime64[ns])  : UTC instant (naive)
      - close_utc (datetime64[ns])  : UTC instant (naive)

    Notes:
      - session is a *label*, not an interval endpoint.
      - open_utc/close_utc are stored UTC-naive for stable parquet round-trip.
    """
    s = schedule.copy()

    # session labels: take schedule index, convert to Timestamp, normalize to midnight
    idx = pd.to_datetime(s.index, errors="raise")
    if getattr(idx, "tz", None) is not None:
        idx = idx.tz_convert("UTC").tz_localize(None)
    session = idx.normalize()

    def _to_utc_naive(x: pd.Series) -> pd.Series:
        xx = pd.to_datetime(x, errors="raise")
        if getattr(xx.dt, "tz", None) is not None:
            return xx.dt.tz_convert("UTC").dt.tz_localize(None)
        # if tz-naive, treat as already UTC-naive (builder invariant for exchange_calendars schedules)
        return xx

    open_utc = _to_utc_naive(s["open"])
    close_utc = _to_utc_naive(s["close"])

    out = pd.DataFrame(
        {
            "session": session.astype("datetime64[ns]"),
            "open_utc": open_utc.astype("datetime64[ns]"),
            "close_utc": close_utc.astype("datetime64[ns]"),
        }
    )
    out.to_parquet(path, index=False)


# ----------------------------
# public builder
# ----------------------------


def build_exchange_calendars_v1(
    *,
    calendar_id: str,
    exchange_calendar_name: str,
    projection_years: int = 2,
    root: Path | None = None,
) -> None:
    """
    Build MXM V1 calendar artifacts using exchange_calendars for observed schedule.

    Writes (under <root>/<calendar_id>/):
      - schedule_observed.parquet
      - trading_days_observed.parquet
      - trading_days_projected.parquet

    Updates <root>/calendar_registry.yaml with checksums and provenance.

    Notes:
      - Observed end is taken from exchange_calendars coverage end.
      - Projected region begins strictly after observed_end.
      - Projection rule: weekday-only minus minimal US closure holidays (incl Good Friday).
    """
    # Local import: builders are ops-only; runtime does not depend on exchange_calendars.
    import exchange_calendars as xcals  # type: ignore[reportMissingTypeStubs]

    cal_root = calendars_root() if root is None else root
    cal_path = calendar_dir(calendar_id, cal_root)
    cal_path.mkdir(parents=True, exist_ok=True)

    cal = xcals.get_calendar(exchange_calendar_name)

    # Observed schedule (DataFrame indexed by sessions)
    schedule = cal.schedule
    if schedule.empty:
        raise CalendarRegistryError(
            f"{calendar_id}: exchange_calendars returned empty schedule for {exchange_calendar_name}"
        )

    # Observed trading days from schedule index
    sessions = pd.to_datetime(schedule.index).date
    obs_days = np.array(
        [np.datetime64(d, "D") for d in sessions], dtype="datetime64[D]"
    )

    if np.any(obs_days[1:] <= obs_days[:-1]):
        raise CalendarRegistryError(
            f"{calendar_id}: observed trading days are not strictly increasing"
        )

    observed_start = obs_days[0]
    observed_end = obs_days[-1]

    # Projected trading days
    if projection_years < 1:
        raise CalendarRegistryError(
            f"{calendar_id}: projection_years must be >= 1, got {projection_years!r}"
        )
    proj_days = _project_trading_days_minimal_us(
        start_exclusive=observed_end,
        projection_years=projection_years,
    )
    projection_start = proj_days[0]
    projection_end = proj_days[-1]

    # Write artifacts
    schedule_path = cal_path / "schedule_observed.parquet"
    obs_days_path = cal_path / "trading_days_observed.parquet"
    proj_days_path = cal_path / "trading_days_projected.parquet"

    _write_schedule_parquet(schedule_path, schedule)
    _write_trading_days_parquet(obs_days_path, obs_days)
    _write_trading_days_parquet(proj_days_path, proj_days)

    # Checksums
    sha_schedule = sha256_file(schedule_path)
    sha_obs = sha256_file(obs_days_path)
    sha_proj = sha256_file(proj_days_path)

    # Registry update
    reg_path = registry_path(cal_root)
    reg = load_calendar_registry(reg_path) if reg_path.exists() else {}
    now = (
        dt.datetime.now(dt.UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )

    # Provenance
    pkg_version = importlib.metadata.version("exchange_calendars")

    entry = CalendarRegistryEntry(
        calendar_id=calendar_id,
        source=SourceInfo(
            kind="exchange_calendars",
            spec={
                "package": "exchange_calendars",
                "version": pkg_version,
                "calendar_name": exchange_calendar_name,
            },
        ),
        observed=ObservedSection(
            start=observed_start,
            end=observed_end,
            trading_days_artifact=obs_days_path.name,
            schedule_artifact=schedule_path.name,
            sha256_trading_days=sha_obs,
            sha256_schedule=sha_schedule,
        ),
        projection=ProjectionSection(
            rule_id="us_federal_minimal_v1",
            start=projection_start,
            end=projection_end,
            trading_days_artifact=proj_days_path.name,
            sha256_trading_days=sha_proj,
        ),
        generated_at=now,
        builder=BuilderInfo(
            builder_id="mxm.v1.calendars.builders.build_exchange_calendars_v1",
            mxm_version=None,
            params={
                "exchange_calendar_name": exchange_calendar_name,
                "projection_years": projection_years,
            },
        ),
    )
    reg[calendar_id] = entry
    write_calendar_registry(reg_path, reg)
