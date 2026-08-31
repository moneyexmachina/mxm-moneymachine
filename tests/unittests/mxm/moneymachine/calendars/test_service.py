from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import numpy as np
import pandas as pd

from mxm.moneymachine.calendars.service import (
    TradingCalendarService,
    canonical_calendar_id,
)
from mxm.refdata import RefDataReader


@dataclass(frozen=True)
class _FakeProduct:
    trading_calendar: str


class _FakeRefDataReader:
    def get_product_by_id(
        self,
        product_id: str,
    ) -> _FakeProduct:
        assert product_id == "p1"
        return _FakeProduct(
            trading_calendar="CMES",
        )


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def test_canonical_calendar_id() -> None:
    assert canonical_calendar_id(" CMES ") == "cmes"


def test_calendar_for_product_smoke(
    tmp_path: Path,
) -> None:
    root = tmp_path / "calendars"
    cal_dir = root / "cmes"
    cal_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    obs = pd.DataFrame(
        {
            "day": pd.to_datetime(
                [
                    "2026-01-02",
                    "2026-01-05",
                ]
            )
        }
    )
    obs.to_parquet(
        cal_dir / "trading_days_observed.parquet",
        index=False,
    )

    proj = pd.DataFrame(
        {
            "day": pd.to_datetime(
                [
                    "2026-01-06",
                    "2026-01-07",
                ]
            )
        }
    )
    proj.to_parquet(
        cal_dir / "trading_days_projected.parquet",
        index=False,
    )

    sched = pd.DataFrame(
        {
            "session": pd.to_datetime(
                [
                    "2026-01-02",
                    "2026-01-05",
                ]
            ).normalize(),
            "open_utc": pd.to_datetime(
                [
                    "2026-01-02T00:00:00Z",
                    "2026-01-05T00:00:00Z",
                ],
                utc=True,
            ),
            "close_utc": pd.to_datetime(
                [
                    "2026-01-03T00:00:00Z",
                    "2026-01-06T00:00:00Z",
                ],
                utc=True,
            ),
        }
    )
    sched.to_parquet(
        cal_dir / "schedule_observed.parquet",
        index=False,
    )

    reg_txt = f"""
cmes:
  calendar_id: cmes
  source:
    kind: test_fixture
    spec: {{}}
  observed:
    start: "2026-01-02"
    end: "2026-01-05"
    trading_days_artifact: trading_days_observed.parquet
    schedule_artifact: schedule_observed.parquet
    sha256:
      trading_days: "{_sha(cal_dir / "trading_days_observed.parquet")}"
      schedule: "{_sha(cal_dir / "schedule_observed.parquet")}"
  projection:
    rule_id: test_projection
    start: "2026-01-06"
    end: "2026-01-31"
    trading_days_artifact: trading_days_projected.parquet
    sha256:
      trading_days: "{_sha(cal_dir / "trading_days_projected.parquet")}"
  generated_at: "2026-02-04T00:00:00Z"
"""

    (root / "calendar_registry.yaml").write_text(
        reg_txt.strip() + "\n",
        encoding="utf-8",
    )

    svc = TradingCalendarService(
        refdata_reader=cast(
            RefDataReader,
            _FakeRefDataReader(),
        ),
        calendars_root=root,
    )

    cal = svc.calendar_for_product("p1")

    assert cal.calendar_id == "cmes"
    assert cal.trading_days.dtype == np.dtype("datetime64[D]")
