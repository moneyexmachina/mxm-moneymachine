from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.testkit.statistics_1d_world import (
    Statistics1DWorld,
    make_statistics_1d_world,
)


@pytest.fixture
def statistics_1d_world(tmp_path: Path) -> Statistics1DWorld:
    """
    Hermetic test world for statistics_1d:
    - temp layout
    - SQLite backend
    - Statistics1DStore
    """
    return make_statistics_1d_world(tmp_path)
