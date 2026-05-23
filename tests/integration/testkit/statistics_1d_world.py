from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mxm.moneymachine.marketdata.datasets.statistics_1d.store import Statistics1DStore
from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout
from mxm.moneymachine.marketdata.stores.sqlite.backend import SQLiteBackend


@dataclass(frozen=True)
class Statistics1DWorld:
    root: Path
    layout: MarketdataLayout
    backend: SQLiteBackend
    stats_store: Statistics1DStore


def make_statistics_1d_world(tmp_path: Path) -> Statistics1DWorld:
    layout = MarketdataLayout(root=tmp_path)
    backend = SQLiteBackend(layout=layout)
    stats_store = Statistics1DStore(layout=layout)
    return Statistics1DWorld(
        root=tmp_path,
        layout=layout,
        backend=backend,
        stats_store=stats_store,
    )
