from __future__ import annotations

import hashlib
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from mxm.v1.calendars.loader import load_calendar
from mxm.v1.calendars.registry import CalendarRegistryError


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_days_parquet(path: Path, days: list[str]) -> None:
    """
    Write a trading-days parquet with one column 'day' storing datetime64[D].
    """
    s = pd.Series(
        np.array([np.datetime64(d, "D") for d in days], dtype="datetime64[D]")
    )
    s.to_frame("day").to_parquet(path, index=False)


def _write_schedule_parquet(path: Path, rows: list[tuple[str, str, str]]) -> None:
    """
    Write schedule_observed.parquet with required columns:
      - session (datetime64[ns]) at UTC midnight label
      - open_utc (tz-aware UTC Timestamp)
      - close_utc (tz-aware UTC Timestamp)

    rows: [(session_day, open_ts, close_ts), ...]
      session_day: 'YYYY-MM-DD'
      open_ts/close_ts: ISO8601Z strings
    """
    session = pd.to_datetime([r[0] for r in rows]).normalize()  # DatetimeIndex -> ok
    open_utc = pd.to_datetime([r[1] for r in rows], utc=True, errors="raise")
    close_utc = pd.to_datetime([r[2] for r in rows], utc=True, errors="raise")

    df = pd.DataFrame(
        {
            "session": session.astype("datetime64[ns]"),
            "open_utc": open_utc,
            "close_utc": close_utc,
        }
    )
    df.to_parquet(path, index=False)


def _write_registry(
    root: Path,
    *,
    calendar_id: str,
    observed_days_fn: str,
    projected_days_fn: str,
    observed_end: str,
    obs_sha: str,
    proj_sha: str,
    schedule_fn: str,
    schedule_sha: str,
) -> None:
    """
    Write a minimal registry YAML matching the nested sha256 mapping schema:

      observed:
        sha256:
          trading_days: ...
          schedule: ...
      projection:
        sha256:
          trading_days: ...

    This matches validate_registry_entry() expectations in mxm.v1.calendars.registry.
    """
    reg = f"""
{calendar_id}:
  calendar_id: {calendar_id}
  source:
    kind: test_fixture
    spec: {{}}
  observed:
    start: "2026-01-02"
    end: "{observed_end}"
    trading_days_artifact: {observed_days_fn}
    schedule_artifact: {schedule_fn}
    sha256:
      trading_days: "{obs_sha}"
      schedule: "{schedule_sha}"
  projection:
    rule_id: test_projection
    start: "2026-01-06"
    end: "2026-01-31"
    trading_days_artifact: {projected_days_fn}
    sha256:
      trading_days: "{proj_sha}"
  generated_at: "2026-02-04T00:00:00Z"
"""
    (root / "calendar_registry.yaml").write_text(reg.strip() + "\n", encoding="utf-8")


def _setup_refdata(tmp_path: Path) -> tuple[Path, str]:
    root = tmp_path / "calendars"
    cal_id = "cmes"
    cal_dir = root / cal_id
    cal_dir.mkdir(parents=True, exist_ok=True)
    return root, cal_id


def test_load_calendar_happy_path(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"
    sched_fn = "schedule_observed.parquet"

    # observed ends at 2026-01-05, projected begins at 2026-01-06
    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-05"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-06", "2026-01-07"])

    # schedule must match observed days exactly
    _write_schedule_parquet(
        root / cal_id / sched_fn,
        [
            ("2026-01-02", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
            ("2026-01-05", "2026-01-05T00:00:00Z", "2026-01-06T00:00:00Z"),
        ],
    )

    obs_sha = _sha256_file(root / cal_id / obs_fn)
    proj_sha = _sha256_file(root / cal_id / proj_fn)
    schedule_sha = _sha256_file(root / cal_id / sched_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-05",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
        schedule_fn=sched_fn,
        schedule_sha=schedule_sha,
    )

    cal = load_calendar(cal_id, root=root)

    assert cal.calendar_id == cal_id
    assert cal.observed_end == np.datetime64("2026-01-05", "D")

    # effective = observed + projected
    assert cal.trading_days.tolist() == [
        np.datetime64("2026-01-02", "D"),
        np.datetime64("2026-01-05", "D"),
        np.datetime64("2026-01-06", "D"),
        np.datetime64("2026-01-07", "D"),
    ]

    # schedule is loaded and available
    assert cal.schedule is not None


def test_load_calendar_checksum_mismatch_raises(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"
    sched_fn = "schedule_observed.parquet"

    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-05"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-06", "2026-01-07"])
    _write_schedule_parquet(
        root / cal_id / sched_fn,
        [
            ("2026-01-02", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
            ("2026-01-05", "2026-01-05T00:00:00Z", "2026-01-06T00:00:00Z"),
        ],
    )

    # Deliberately wrong checksum for observed trading days
    obs_sha = "0" * 64
    proj_sha = _sha256_file(root / cal_id / proj_fn)
    schedule_sha = _sha256_file(root / cal_id / sched_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-05",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
        schedule_fn=sched_fn,
        schedule_sha=schedule_sha,
    )

    with pytest.raises(CalendarRegistryError):
        load_calendar(cal_id, root=root)


def test_load_calendar_projection_overlap_raises(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"
    sched_fn = "schedule_observed.parquet"

    # observed_end == 2026-01-05, but projected starts on 2026-01-05 => overlap
    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-05"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-05", "2026-01-06"])
    _write_schedule_parquet(
        root / cal_id / sched_fn,
        [
            ("2026-01-02", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
            ("2026-01-05", "2026-01-05T00:00:00Z", "2026-01-06T00:00:00Z"),
        ],
    )

    obs_sha = _sha256_file(root / cal_id / obs_fn)
    proj_sha = _sha256_file(root / cal_id / proj_fn)
    schedule_sha = _sha256_file(root / cal_id / sched_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-05",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
        schedule_fn=sched_fn,
        schedule_sha=schedule_sha,
    )

    with pytest.raises(CalendarRegistryError):
        load_calendar(cal_id, root=root)


def test_load_calendar_observed_not_strictly_increasing_raises(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"
    sched_fn = "schedule_observed.parquet"

    # not strictly increasing (duplicate)
    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-02"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-06", "2026-01-07"])

    # schedule must match observed days "exactly" — but observed is invalid and will fail earlier,
    # so we can still write a minimal file to satisfy existence/checksum paths.
    _write_schedule_parquet(
        root / cal_id / sched_fn,
        [
            ("2026-01-02", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
            ("2026-01-02", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
        ],
    )

    obs_sha = _sha256_file(root / cal_id / obs_fn)
    proj_sha = _sha256_file(root / cal_id / proj_fn)
    schedule_sha = _sha256_file(root / cal_id / sched_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-02",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
        schedule_fn=sched_fn,
        schedule_sha=schedule_sha,
    )

    with pytest.raises(CalendarRegistryError):
        load_calendar(cal_id, root=root)


def test_load_calendar_schedule_checksum_mismatch_raises(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"
    sched_fn = "schedule_observed.parquet"

    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-05"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-06", "2026-01-07"])
    _write_schedule_parquet(
        root / cal_id / sched_fn,
        [
            ("2026-01-02", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
            ("2026-01-05", "2026-01-05T00:00:00Z", "2026-01-06T00:00:00Z"),
        ],
    )

    obs_sha = _sha256_file(root / cal_id / obs_fn)
    proj_sha = _sha256_file(root / cal_id / proj_fn)

    # wrong schedule checksum
    schedule_sha = "0" * 64

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-05",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
        schedule_fn=sched_fn,
        schedule_sha=schedule_sha,
    )

    with pytest.raises(CalendarRegistryError):
        load_calendar(cal_id, root=root)


def test_load_calendar_schedule_coverage_mismatch_raises(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"
    sched_fn = "schedule_observed.parquet"

    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-05"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-06", "2026-01-07"])

    # schedule ends on 2026-01-02 only -> mismatch with observed_end 2026-01-05
    _write_schedule_parquet(
        root / cal_id / sched_fn,
        [
            ("2026-01-02", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
        ],
    )

    obs_sha = _sha256_file(root / cal_id / obs_fn)
    proj_sha = _sha256_file(root / cal_id / proj_fn)
    schedule_sha = _sha256_file(root / cal_id / sched_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-05",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
        schedule_fn=sched_fn,
        schedule_sha=schedule_sha,
    )

    with pytest.raises((CalendarRegistryError, ValueError)):
        load_calendar(cal_id, root=root)


def test_load_calendar_schedule_label_not_in_trading_days_raises(
    tmp_path: Path,
) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"
    sched_fn = "schedule_observed.parquet"

    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-05"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-06", "2026-01-07"])

    # schedule contains 2026-01-03 which is not a trading day in obs_fn
    _write_schedule_parquet(
        root / cal_id / sched_fn,
        [
            ("2026-01-02", "2026-01-02T00:00:00Z", "2026-01-03T00:00:00Z"),
            ("2026-01-03", "2026-01-03T00:00:00Z", "2026-01-04T00:00:00Z"),
        ],
    )

    obs_sha = _sha256_file(root / cal_id / obs_fn)
    proj_sha = _sha256_file(root / cal_id / proj_fn)
    schedule_sha = _sha256_file(root / cal_id / sched_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-05",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
        schedule_fn=sched_fn,
        schedule_sha=schedule_sha,
    )

    with pytest.raises((CalendarRegistryError, ValueError)):
        load_calendar(cal_id, root=root)
