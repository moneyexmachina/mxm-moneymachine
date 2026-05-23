"""Offline patching helpers for statistics_1d integration tests."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any

import pandas as pd
from pytest import MonkeyPatch

import mxm.moneymachine.marketdata.orchestrators.statistics_1d as orch_mod
from mxm.moneymachine.marketdata.schema.statistics_1d import (
    STATISTICS_1D,
    coerce_statistics_1d,
)
from tests.integration.testkit.fixtures_statistics import make_statistics_1d_rawish_df

type ColumnDefault = str | int | float | bool | pd.Timestamp | None


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

    _populate_base_statistics_columns(
        df,
        dataset=dataset,
        publisher_id=publisher_id,
        instrument_id=instrument_id,
        raw_symbol=raw_symbol,
    )
    _validate_required_timestamp_columns(df)
    _derive_trading_date(df)
    _populate_observation_statistics_columns(df)

    out = _coerce_statistics_store_surface(df, dataset=dataset)
    _validate_statistics_store_surface(out)

    return out


def _set_default_column(
    df: pd.DataFrame,
    *,
    column_name: str,
    value: ColumnDefault,
) -> None:
    if column_name not in df.columns:
        df[column_name] = value


def _populate_base_statistics_columns(
    df: pd.DataFrame,
    *,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    raw_symbol: str,
) -> None:
    _set_default_column(df, column_name="trading_date", value=None)
    _set_default_column(df, column_name="rtype", value=24)
    _set_default_column(df, column_name="quantity", value=0.0)
    _set_default_column(df, column_name="ts_in_delta", value=0)
    _set_default_column(df, column_name="update_action", value=0)
    _set_default_column(df, column_name="is_trading_tick", value=False)
    _set_default_column(df, column_name="is_intraday", value=False)
    _set_default_column(df, column_name="is_null_set", value=False)
    _set_default_column(df, column_name="schema", value="statistics")
    _set_default_column(df, column_name="publisher_id", value=publisher_id)
    _set_default_column(df, column_name="channel_id", value=0)
    _set_default_column(df, column_name="dataset", value=dataset)
    _set_default_column(df, column_name="instrument_id", value=instrument_id)
    _set_default_column(df, column_name="raw_symbol", value=raw_symbol)


def _validate_required_timestamp_columns(df: pd.DataFrame) -> None:
    for column_name in ("ts_recv", "ts_event", "ts_ref"):
        if column_name not in df.columns:
            raise ValueError(
                f"test fixture missing required timestamp column: {column_name}"
            )


def _derive_trading_date(df: pd.DataFrame) -> None:
    if "trading_date" not in df.columns or df["trading_date"].isna().all():
        df["trading_date"] = pd.to_datetime(
            df["ts_ref"],
            utc=True,
        ).dt.floor("D")


def _populate_observation_statistics_columns(df: pd.DataFrame) -> None:
    _set_default_column(df, column_name="is_final", value=False)
    _set_default_column(df, column_name="is_actual", value=True)
    _set_default_column(df, column_name="stat_flags", value=0)
    _set_default_column(df, column_name="price", value=0.0)
    _set_default_column(df, column_name="sequence", value=0)


def _coerce_statistics_store_surface(
    df: pd.DataFrame,
    *,
    dataset: str,
) -> pd.DataFrame:
    return coerce_statistics_1d(
        df,
        dataset=dataset,
        schema="statistics",
        ensure_column_order=True,
    )


def _validate_statistics_store_surface(df: pd.DataFrame) -> None:
    missing = [
        column_name
        for column_name in STATISTICS_1D.required
        if column_name not in df.columns
    ]

    if missing:
        raise ValueError(f"canonicalize failed: missing columns {missing}")


def patch_statistics_1d_orchestrator_offline(
    monkeypatch: MonkeyPatch,
    *,
    cfg: OfflineStats1DConfig,
    stats_df_factory: StatsDataFrameFactory | None = None,
) -> None:
    resolved_stats_df_factory = _resolve_stats_df_factory(stats_df_factory)

    monkeypatch.setattr(
        orch_mod,
        "_gate_definitions_available",
        _fake_gate_definitions_available,
    )
    monkeypatch.setattr(orch_mod, "contract_year_month", _fake_contract_year_month)
    monkeypatch.setattr(
        orch_mod,
        "get_dataset_range",
        _fake_get_dataset_range(cfg),
    )
    monkeypatch.setattr(
        orch_mod,
        "resolve_databento_instrument",
        _fake_resolve_databento_instrument(cfg),
    )
    monkeypatch.setattr(
        orch_mod,
        "read_lifecycle_for_product_instrument",
        _fake_read_lifecycle_for_product_instrument,
    )
    monkeypatch.setattr(
        orch_mod,
        "estimate_cost_statistics_1d",
        _fake_estimate_cost_statistics_1d(cfg),
    )
    monkeypatch.setattr(
        orch_mod,
        "pull_statistics_1d_by_instrument_id",
        _fake_pull_statistics_1d_by_instrument_id(resolved_stats_df_factory),
    )
    monkeypatch.setattr(
        orch_mod,
        "normalize_statistics_1d",
        _fake_normalize_statistics_1d(cfg),
    )


def _resolve_stats_df_factory(
    stats_df_factory: StatsDataFrameFactory | None,
) -> StatsDataFrameFactory:
    if stats_df_factory is not None:
        return stats_df_factory

    def default_stats_df_factory(instrument_id: int) -> pd.DataFrame:
        return make_statistics_1d_rawish_df(
            instrument_id=instrument_id,
            raw_symbol="TEST.2020-01",
        )

    return default_stats_df_factory


def _fake_gate_definitions_available(
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


def _fake_contract_year_month(contract: object) -> tuple[int, int]:
    _ = contract
    return (2020, 1)


def _fake_get_dataset_range(cfg: OfflineStats1DConfig):
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

    return fake_get_dataset_range


def _fake_resolve_databento_instrument(cfg: OfflineStats1DConfig):
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

    return fake_resolve_databento_instrument


def _fake_read_lifecycle_for_product_instrument(
    *,
    store: object,
    product_id: str,
    publisher_id: int,
    instrument_id: int,
) -> None:
    _ = (store, product_id, publisher_id, instrument_id)


def _fake_estimate_cost_statistics_1d(cfg: OfflineStats1DConfig):
    def fake_estimate_cost_statistics_1d(
        *,
        client: object,
        dataset: str,
        symbols: object,
        stype_in: str = "raw_symbol",
        start: str,
        end: str,
    ) -> SimpleNamespace:
        _ = (client, dataset, symbols, stype_in, start, end)
        return SimpleNamespace(estimated_cost_usd=cfg.estimated_cost_usd)

    return fake_estimate_cost_statistics_1d


def _fake_pull_statistics_1d_by_instrument_id(
    stats_df_factory: StatsDataFrameFactory,
):
    def fake_pull_statistics_1d_by_instrument_id(
        *,
        dataset: str,
        instrument_id: int,
        start: str,
        end: str,
        source: str = "databento",
        extra: Mapping[str, Any] | None = None,
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        _ = (
            dataset,
            start,
            end,
            source,
            extra,
            force_refresh,
        )
        return stats_df_factory(instrument_id)

    return fake_pull_statistics_1d_by_instrument_id


def _fake_normalize_statistics_1d(cfg: OfflineStats1DConfig):
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

    return fake_normalize_statistics_1d
