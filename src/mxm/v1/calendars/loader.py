"""
MXM V1 — Calendar artifact loaders.

This module loads calendar artifacts from user refdata and constructs the
runtime TradingCalendar model.

Key invariants:
- runtime depends only on persisted artifacts + registry
- artifacts are checksum-validated (sha256)
- trading-day arrays are strict: dtype datetime64[D], strictly increasing, unique
- observed vs projected boundary is enforced and auditable
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from mxm.v1.utils.hashing import sha256_file

from .models import TradingCalendar
from .registry import (
    CalendarRegistryError,
    get_registry_entry,
    load_calendar_registry,
    validate_registry_entry,
)

# ----------------------------
# Refdata path policy (V1)
# ----------------------------


def calendars_root() -> Path:
    """
    Return the user refdata calendars root.

    V1 policy:
      ~/.mxm/refdata/calendars

    This is intentionally simple. If you later adopt XDG locations, this
    function is the single point of change.
    """
    return Path.home() / ".mxm" / "refdata" / "calendars"


def registry_path(root: Path | None = None) -> Path:
    r = calendars_root() if root is None else root
    return r / "calendar_registry.yaml"


def calendar_dir(calendar_id: str, root: Path | None = None) -> Path:
    r = calendars_root() if root is None else root
    return r / calendar_id


# ----------------------------
# Artifact loading helpers
# ----------------------------


def _load_trading_days_parquet(path: Path) -> np.ndarray:
    """
    Load a trading-day artifact from parquet and return datetime64[D] ndarray.

    Accepted parquet shapes:
    - single column (Series-like)
    - index-only (rare; if written that way)

    We coerce to numpy datetime64[D] and validate strict monotonicity.
    """
    if not path.exists():
        raise CalendarRegistryError(f"Calendar artifact not found: {path}")

    df = pd.read_parquet(path)

    if df.shape[1] == 0:
        s = pd.Series(df.index)
    elif df.shape[1] == 1:
        s = df.iloc[:, 0]
    else:
        raise CalendarRegistryError(
            f"Trading-days parquet must have 0 or 1 columns, got {df.shape[1]}: {path}"
        )

    # Convert to numpy datetime64[D]
    arr = s.to_numpy()

    if arr.dtype.kind != "M":
        raise CalendarRegistryError(
            f"Trading-days dtype must be datetime64, got {arr.dtype!r}: {path}"
        )

    days = arr.astype("datetime64[D]")

    if days.ndim != 1:
        days = days.reshape(-1)

    if days.size == 0:
        raise CalendarRegistryError(f"Trading-days array is empty: {path}")

    # Strictly increasing
    if np.any(days[1:] <= days[:-1]):
        raise CalendarRegistryError(
            f"Trading-days array must be strictly increasing (sorted, unique): {path}"
        )

    return days


def _validate_checksum(path: Path, expected_hex: str, *, where: str) -> None:
    if not expected_hex:
        raise CalendarRegistryError(
            f"{where}: expected sha256 hex string missing/invalid"
        )
    got = sha256_file(path)
    if got != expected_hex:
        raise CalendarRegistryError(
            f"{where}: sha256 mismatch for {path.name}: expected {expected_hex}, got {got}"
        )


# ----------------------------
# Public loader
# ----------------------------


def load_calendar(calendar_id: str, *, root: Path | None = None) -> TradingCalendar:
    """
    Load calendar artifacts for `calendar_id` and construct a TradingCalendar.

    This is the runtime entrypoint. It performs:
    - registry load + entry validation
    - artifact existence checks
    - sha256 verification against registry
    - observed/projected boundary enforcement
    - effective trading-days assembly
    """
    cal_root = calendars_root() if root is None else root
    reg_path = registry_path(cal_root)

    registry = load_calendar_registry(reg_path)
    entry = get_registry_entry(registry, calendar_id)
    validate_registry_entry(entry)

    cal_path = calendar_dir(entry.calendar_id, cal_root)

    obs_days_path = cal_path / entry.observed.trading_days_artifact
    proj_days_path = cal_path / entry.projection.trading_days_artifact

    # checksum validation
    _validate_checksum(
        obs_days_path,
        entry.observed.sha256_trading_days,
        where=f"{calendar_id}.observed.trading_days",
    )
    _validate_checksum(
        proj_days_path,
        entry.projection.sha256_trading_days,
        where=f"{calendar_id}.projection.trading_days",
    )

    # load arrays
    obs_days = _load_trading_days_parquet(obs_days_path)
    proj_days = _load_trading_days_parquet(proj_days_path)

    observed_end = entry.observed.end.astype("datetime64[D]")

    # sanity: observed_end must be in observed days
    if observed_end < obs_days[0] or observed_end > obs_days[-1]:
        raise CalendarRegistryError(
            f"{calendar_id}: registry observed_end {observed_end} not within observed days "
            f"[{obs_days[0]}, {obs_days[-1]}]"
        )

    # Observed days must not extend beyond registry observed_end (allow equality).
    # (If you ever store a longer observed artifact, the registry is stale.)
    if obs_days[-1] != observed_end:
        raise CalendarRegistryError(
            f"{calendar_id}: observed days artifact ends at {obs_days[-1]}, but registry observed.end is {observed_end}"
        )

    # projected region must be strictly after observed_end
    if proj_days[0] <= observed_end:
        raise CalendarRegistryError(
            f"{calendar_id}: projected days start {proj_days[0]} must be strictly after observed_end {observed_end}"
        )

    # assemble effective days: all observed + all projected (already > observed_end)
    effective = np.concatenate([obs_days, proj_days])

    # validate effective strictness
    if np.any(effective[1:] <= effective[:-1]):
        raise CalendarRegistryError(
            f"{calendar_id}: effective trading-days array is not strictly increasing"
        )

    # --- load observed schedule (optional runtime surface; authoritative region only)
    schedule_df = None
    if entry.observed.schedule_artifact:
        schedule_path = cal_path / entry.observed.schedule_artifact

        _validate_checksum(
            schedule_path,
            entry.observed.sha256_schedule,
            where=f"{calendar_id}.observed.schedule",
        )

        schedule_df = _load_schedule_observed_parquet(schedule_path)

        # schedule coverage must match observed trading days exactly
        sched_days = schedule_df.index.to_numpy(dtype="datetime64[D]")

        if sched_days.size != obs_days.size or np.any(sched_days != obs_days):
            raise CalendarRegistryError(
                f"{calendar_id}: schedule session labels do not match observed trading days exactly"
            )
    return TradingCalendar(
        calendar_id=entry.calendar_id,
        trading_days=effective,
        observed_end=observed_end,
        schedule=schedule_df,
    )


def _load_schedule_observed_parquet(path: Path) -> pd.DataFrame:
    """
    Load an observed schedule artifact from parquet.

    Expected columns:
      - session
      - open_utc
      - close_utc
      - optional: break_start_utc, break_end_utc
    """
    df = _read_schedule_parquet(path)
    _validate_schedule_required_columns(df, path=path)

    sess_days = _coerce_schedule_session_days(df, path=path)

    out = _build_schedule_frame_without_session(df, sess_days=sess_days)
    _coerce_schedule_boundary_columns(out)
    _validate_schedule_intervals(out, path=path)

    return out


def _read_schedule_parquet(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise CalendarRegistryError(f"Calendar schedule artifact not found: {path}")

    return pd.read_parquet(path)


def _validate_schedule_required_columns(df: pd.DataFrame, *, path: Path) -> None:
    for column_name in ("session", "open_utc", "close_utc"):
        if column_name not in df.columns:
            raise CalendarRegistryError(
                f"Schedule parquet missing required column {column_name!r}: {path}"
            )


def _coerce_schedule_session_days(
    df: pd.DataFrame,
    *,
    path: Path,
) -> np.ndarray:
    session = pd.to_datetime(df["session"], errors="raise")

    if getattr(session.dt, "tz", None) is not None:
        session = session.dt.tz_convert("UTC").dt.tz_localize(None)

    session_days = session.dt.normalize().to_numpy(dtype="datetime64[D]")
    _validate_schedule_session_days(session_days, path=path)

    return session_days


def _validate_schedule_session_days(
    session_days: np.ndarray,
    *,
    path: Path,
) -> None:
    if session_days.size == 0:
        raise CalendarRegistryError(f"Schedule parquet has zero rows: {path}")

    if np.any(session_days[1:] <= session_days[:-1]):
        raise CalendarRegistryError(
            f"Schedule sessions must be strictly increasing (sorted, unique): {path}"
        )


def _build_schedule_frame_without_session(
    df: pd.DataFrame,
    *,
    sess_days: np.ndarray,
) -> pd.DataFrame:
    out = df.copy()
    out.index = sess_days
    return out.drop(columns=["session"])


def _coerce_schedule_boundary_columns(out: pd.DataFrame) -> None:
    out["open_utc"] = _coerce_utc_timestamp_column(out, "open_utc")
    out["close_utc"] = _coerce_utc_timestamp_column(out, "close_utc")

    for column_name in ("break_start_utc", "break_end_utc"):
        if column_name in out.columns:
            out[column_name] = _coerce_utc_timestamp_column(out, column_name)


def _coerce_utc_timestamp_column(
    df: pd.DataFrame,
    column_name: str,
) -> pd.Series:
    return pd.to_datetime(df[column_name], utc=True, errors="raise")


def _validate_schedule_intervals(
    out: pd.DataFrame,
    *,
    path: Path,
) -> None:
    if (out["open_utc"] >= out["close_utc"]).any():
        raise CalendarRegistryError(f"Schedule has open_utc >= close_utc rows: {path}")
