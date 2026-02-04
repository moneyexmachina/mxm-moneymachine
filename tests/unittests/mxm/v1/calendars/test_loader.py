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
    s = pd.Series(
        np.array([np.datetime64(d, "D") for d in days], dtype="datetime64[D]")
    )
    s.to_frame("day").to_parquet(path, index=False)


def _write_registry(
    root: Path,
    *,
    calendar_id: str,
    observed_days_fn: str,
    projected_days_fn: str,
    observed_end: str,
    obs_sha: str,
    proj_sha: str,
) -> None:
    reg = f"""
calendar_id: {calendar_id}
source:
  kind: test_fixture
  spec: {{}}
observed:
  start: 2026-01-02
  end: {observed_end}
  trading_days_artifact: {observed_days_fn}
  schedule_artifact: schedule_observed.parquet
  sha256:
    trading_days: "{obs_sha}"
    schedule: "deadbeef"
projection:
  rule_id: test_projection
  start: 2026-01-06
  end: 2026-01-31
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
    (root / "holiday_rules").mkdir(parents=True, exist_ok=True)
    return root, cal_id


def test_load_calendar_happy_path(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"

    # observed ends at 2026-01-05, projected begins at 2026-01-06
    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-05"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-06", "2026-01-07"])

    obs_sha = _sha256_file(root / cal_id / obs_fn)
    proj_sha = _sha256_file(root / cal_id / proj_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-05",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
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


def test_load_calendar_checksum_mismatch_raises(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"

    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-05"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-06", "2026-01-07"])

    # Deliberately wrong checksum for observed
    obs_sha = "0" * 64
    proj_sha = _sha256_file(root / cal_id / proj_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-05",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
    )

    with pytest.raises(CalendarRegistryError):
        load_calendar(cal_id, root=root)


def test_load_calendar_projection_overlap_raises(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"

    # observed_end == 2026-01-05, but projected starts on 2026-01-05 => overlap
    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-05"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-05", "2026-01-06"])

    obs_sha = _sha256_file(root / cal_id / obs_fn)
    proj_sha = _sha256_file(root / cal_id / proj_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-05",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
    )

    with pytest.raises(CalendarRegistryError):
        load_calendar(cal_id, root=root)


def test_load_calendar_observed_not_strictly_increasing_raises(tmp_path: Path) -> None:
    root, cal_id = _setup_refdata(tmp_path)

    obs_fn = "trading_days_observed.parquet"
    proj_fn = "trading_days_projected.parquet"

    # not strictly increasing (duplicate)
    _write_days_parquet(root / cal_id / obs_fn, ["2026-01-02", "2026-01-02"])
    _write_days_parquet(root / cal_id / proj_fn, ["2026-01-06", "2026-01-07"])

    obs_sha = _sha256_file(root / cal_id / obs_fn)
    proj_sha = _sha256_file(root / cal_id / proj_fn)

    _write_registry(
        root,
        calendar_id=cal_id,
        observed_days_fn=obs_fn,
        projected_days_fn=proj_fn,
        observed_end="2026-01-02",
        obs_sha=obs_sha,
        proj_sha=proj_sha,
    )

    with pytest.raises(CalendarRegistryError):
        load_calendar(cal_id, root=root)
