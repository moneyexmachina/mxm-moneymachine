"""Offline patching helpers for statistics_1d integration tests."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd
from pytest import MonkeyPatch

import mxm.v1.marketdata.orchestrators.statistics_1d as orch_mod
from mxm.v1.marketdata.schema.statistics_1d import STATISTICS_1D, coerce_statistics_1d
from tests.integration.testkit.fixtures_statistics import make_statistics_1d_rawish_df


@dataclass(frozen=True)
class OfflineStats1DConfig:
    """Configuration for hermetic/offline patching of the statistics_1d orchestrator."""

    product_id: str
    instrument_id: int
    dataset: str = "TEST.DATASET"
    feed: str = "databento"
    publisher_id: int = 1
    estimated_cost_usd: float = 0.0
    avail_start: str = "2020-01-01T00:00:00Z"
    avail_end: str = "2020-02-01T00:00:00Z"
    patch_normalize_to_identity: bool = True


@dataclass(frozen=True)
class OfflineIdent:
    """Minimal stand-in for DatabentoInstrumentIdentity."""

    feed: str
    dataset: str
    publisher_id: int
    instrument_id: int
    raw_symbol: str


type StatsDataFrameFactory = Callable[[int], pd.DataFrame]


def _canonicalize_for_store(
    df_raw: pd.DataFrame,
    *,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    raw_symbol: str,
) -> pd.DataFrame:
    df = df_raw.copy()

    if "trading_date" not in df.columns:
        df["trading_date"] = pd.NaT
    if "rtype" not in df.columns:
        df["rtype"] = 24
    if "quantity" not in df.columns:
        df["quantity"] = 0.0
    if "ts_in_delta" not in df.columns:
        df["ts_in_delta"] = 0
    if "update_action" not in df.columns:
        df["update_action"] = 0
    if "is_trading_tick" not in df.columns:
        df["is_trading_tick"] = False
    if "is_intraday" not in df.columns:
        df["is_intraday"] = False
    if "is_null_set" not in df.columns:
        df["is_null_set"] = False
    if "schema" not in df.columns:
        df["schema"] = "statistics"
    if "publisher_id" not in df.columns:
        df["publisher_id"] = publisher_id
    if "channel_id" not in df.columns:
        df["channel_id"] = 0
    if "dataset" not in df.columns:
        df["dataset"] = dataset
    if "instrument_id" not in df.columns:
        df["instrument_id"] = instrument_id
    if "raw_symbol" not in df.columns:
        df["raw_symbol"] = raw_symbol

    for column_name in ("ts_recv", "ts_event", "ts_ref"):
        if column_name not in df.columns:
            raise ValueError(
                f"test fixture missing required timestamp column: {column_name}"
            )

    if "trading_date" not in df.columns or df["trading_date"].isna().all():
        df["trading_date"] = pd.to_datetime(df["ts_ref"], utc=True).dt.floor("D")

    if "is_final" not in df.columns:
        df["is_final"] = False
    if "is_actual" not in df.columns:
        df["is_actual"] = True
    if "stat_flags" not in df.columns:
        df["stat_flags"] = 0
    if "price" not in df.columns:
        df["price"] = 0.0
    if "sequence" not in df.columns:
        df["sequence"] = 0

    out = coerce_statistics_1d(
        df,
        dataset=dataset,
        schema="statistics",
        ensure_column_order=True,
    )

    missing = [
        column_name
        for column_name in STATISTICS_1D.required
        if column_name not in out.columns
    ]
    if missing:
        raise ValueError(f"canonicalize failed: missing columns {missing}")

    return out


def patch_statistics_1d_orchestrator_offline(
    monkeypatch: MonkeyPatch,
    *,
    cfg: OfflineStats1DConfig,
    stats_df_factory: StatsDataFrameFactory | None = None,
) -> None:
    if stats_df_factory is None:

        def default_stats_df_factory(instrument_id: int) -> pd.DataFrame:
            return make_statistics_1d_rawish_df(
                instrument_id=instrument_id,
                raw_symbol="TEST.2020-01",
            )

        stats_df_factory = default_stats_df_factory

    def fake_gate_definitions_available(
        *,
        backend: object,
        product_id: str,
    ) -> orch_mod.GateResult:
        _ = (backend, product_id)
        return orch_mod.GateResult(
            name="instrument_definitions_watermark_exists",
            ok=True,
            detail="watermark=test",
        )

    def fake_contract_year_month(contract: object) -> tuple[int, int]:
        _ = contract
        return (2020, 1)

    def fake_get_dataset_range(
        client: object,
        dataset: str,
        schema: str,
    ) -> SimpleNamespace:
        _ = (client, dataset, schema)
        return SimpleNamespace(
            start=cfg.avail_start,
            end=cfg.avail_end,
        )

    def fake_resolve_databento_instrument(
        backend: object,
        contract: object,
    ) -> OfflineIdent:
        _ = backend
        return OfflineIdent(
            feed=cfg.feed,
            dataset=cfg.dataset,
            publisher_id=cfg.publisher_id,
            instrument_id=cfg.instrument_id,
            raw_symbol=str(getattr(contract, "contract_id", "UNKNOWN")),
        )

    def fake_read_lifecycle_for_product_instrument(
        *,
        store: object,
        product_id: str,
        publisher_id: int,
        instrument_id: int,
    ) -> None:
        _ = (store, product_id, publisher_id, instrument_id)

    def fake_estimate_cost_statistics_1d(
        *,
        client: object,
        dataset: str,
        schema: str,
        start: object,
        end: object,
        symbols: object,
    ) -> SimpleNamespace:
        _ = (client, dataset, schema, start, end, symbols)
        return SimpleNamespace(estimated_cost_usd=cfg.estimated_cost_usd)

    def fake_pull_statistics_1d_by_instrument_id(
        *,
        client: object,
        dataset: str,
        publisher_id: int,
        instrument_id: int,
        start: object,
        end: object,
    ) -> pd.DataFrame:
        _ = (client, dataset, publisher_id, start, end)
        return stats_df_factory(instrument_id)

    def fake_normalize_statistics_1d(
        df_raw: pd.DataFrame,
        dataset: str,
        raw_symbol: str,
    ) -> pd.DataFrame:
        return _canonicalize_for_store(
            df_raw,
            dataset=dataset,
            publisher_id=cfg.publisher_id,
            instrument_id=cfg.instrument_id,
            raw_symbol=raw_symbol,
        )

    monkeypatch.setattr(
        orch_mod,
        "_gate_definitions_available",
        fake_gate_definitions_available,
    )
    monkeypatch.setattr(orch_mod, "contract_year_month", fake_contract_year_month)
    monkeypatch.setattr(orch_mod, "get_dataset_range", fake_get_dataset_range)
    monkeypatch.setattr(
        orch_mod,
        "resolve_databento_instrument",
        fake_resolve_databento_instrument,
    )
    monkeypatch.setattr(
        orch_mod,
        "read_lifecycle_for_product_instrument",
        fake_read_lifecycle_for_product_instrument,
    )
    monkeypatch.setattr(
        orch_mod,
        "estimate_cost_statistics_1d",
        fake_estimate_cost_statistics_1d,
    )
    monkeypatch.setattr(
        orch_mod,
        "pull_statistics_1d_by_instrument_id",
        fake_pull_statistics_1d_by_instrument_id,
    )
    monkeypatch.setattr(
        orch_mod,
        "normalize_statistics_1d",
        fake_normalize_statistics_1d,
    )
