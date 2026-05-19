from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from mxm.v1.calendars.builders import build_exchange_calendars_v1
from mxm.v1.calendars.loader import load_calendar
from mxm.v1.calendars.registry import load_calendar_registry, validate_registry_entry
from mxm.v1.utils.hashing import sha256_file


def test_build_exchange_calendars_v1_builds_and_loads(tmp_path: Path) -> None:
    root = tmp_path / "calendars"

    build_exchange_calendars_v1(
        calendar_id="cmes",
        exchange_calendar_name="CMES",
        projection_years=1,
        root=root,
    )

    # artifacts exist
    reg_path = root / "calendar_registry.yaml"
    assert reg_path.exists()

    cal_dir = root / "cmes"
    assert (cal_dir / "schedule_observed.parquet").exists()
    assert (cal_dir / "trading_days_observed.parquet").exists()
    assert (cal_dir / "trading_days_projected.parquet").exists()

    # registry parses + validates
    reg = load_calendar_registry(reg_path)
    entry = reg["cmes"]
    validate_registry_entry(entry)

    # checksums match files (strong smoke test)
    assert (
        sha256_file(cal_dir / entry.observed.trading_days_artifact)
        == entry.observed.sha256_trading_days
    )
    assert (
        sha256_file(cal_dir / entry.observed.schedule_artifact)
        == entry.observed.sha256_schedule
    )
    assert (
        sha256_file(cal_dir / entry.projection.trading_days_artifact)
        == entry.projection.sha256_trading_days
    )
    # loader can load effective calendar
    cal = load_calendar("cmes", root=root)

    # schedule loaded and usable (observed region)
    assert cal.schedule is not None
    assert cal.has_schedule is True

    schedule = cal.schedule

    # timestamp mapping smoke test: during first session -> current_session returns first label
    first_label = schedule.index[0]
    open_col = pd.DatetimeIndex(schedule["open_utc"])
    close_col = pd.DatetimeIndex(schedule["close_utc"])

    open_ts = open_col[0]
    close_ts = close_col[0]
    mid_ts = open_ts + (close_ts - open_ts) / 2

    assert cal.current_session(mid_ts) == np.datetime64(str(first_label), "D")
    # schedule coverage matches observed region endpoints
    sched_labels = cal.schedule.index.to_numpy(dtype="datetime64[D]")
    assert sched_labels[0] == cal.trading_days[0]
    assert sched_labels[-1] == cal.observed_end
    assert cal.calendar_id == "cmes"
    assert cal.trading_days.dtype == np.dtype("datetime64[D]")
    assert cal.trading_days.size > 10  # should be non-trivial

    # strict increasing
    assert not (cal.trading_days[1:] <= cal.trading_days[:-1]).any()

    # projection starts strictly after observed_end
    assert cal.trading_days[-1] > cal.observed_end
