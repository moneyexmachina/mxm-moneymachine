from __future__ import annotations

from pathlib import Path

import numpy as np

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

    assert cal.calendar_id == "cmes"
    assert cal.trading_days.dtype == np.dtype("datetime64[D]")
    assert cal.trading_days.size > 10  # should be non-trivial

    # strict increasing
    assert not (cal.trading_days[1:] <= cal.trading_days[:-1]).any()

    # projection starts strictly after observed_end
    assert cal.trading_days[-1] > cal.observed_end
