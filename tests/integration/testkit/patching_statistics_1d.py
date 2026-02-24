# tests/integrationtests/testkit/patching_statistics_1d.py
from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Callable

import pandas as pd
from _pytest.monkeypatch import MonkeyPatch

import mxm.v1.marketdata.orchestrators.statistics_1d as orch_mod
from mxm.v1.marketdata.schema.statistics_1d import STATISTICS_1D, coerce_statistics_1d
from tests.integration.testkit.fixtures_statistics import make_statistics_1d_rawish_df


@dataclass(frozen=True)
class OfflineStats1DConfig:
    """
    Configuration for hermetic/offline patching of the statistics_1d orchestrator.

    This patch bundle is deliberately narrow:
    - it removes all live dependencies (RefData periods lookup, dataset range call, vendor pull, etc.)
    - it keeps the orchestrator control flow intact (expected window, decision logic, store + ledger)
    """

    product_id: str
    instrument_id: int
    dataset: str = "TEST.DATASET"
    feed: str = "databento"
    publisher_id: int = 1

    # Cost surface: keep at 0.0 for idempotency proofs to avoid budget noise
    estimated_cost_usd: float = 0.0

    # Dataset availability returned by get_dataset_range (raw vendor timestamps; end-exclusive)
    avail_start: str = "2020-01-01T00:00:00Z"
    avail_end: str = "2020-02-01T00:00:00Z"

    # If True, normalize_statistics_1d will be patched to identity.
    # This is recommended for hermetic tests unless you maintain raw vendor-shaped fixtures.
    patch_normalize_to_identity: bool = True


@dataclass(frozen=True)
class OfflineIdent:
    """
    Minimal stand-in for DatabentoInstrumentIdentity.

    We only need the attributes that the orchestrator reads when recording attempts
    and when calling store.{read,write,scan_coverage,delete}.
    """

    feed: str
    dataset: str
    publisher_id: int
    instrument_id: int
    raw_symbol: str


def _canonicalize_for_store(
    df_raw: pd.DataFrame,
    *,
    dataset: str,
    publisher_id: int,
    instrument_id: int,
    raw_symbol: str,
) -> pd.DataFrame:
    df = df_raw.copy()

    # Fill required columns with deterministic defaults where missing
    # (This is the test equivalent of vendor normalization.)
    defaults: dict[str, object] = {
        "trading_date": pd.NaT,  # will be derived from ts_ref below if missing/NaT
        "rtype": 24,
        "quantity": 0.0,
        "ts_in_delta": 0,
        "update_action": 0,
        "is_trading_tick": False,
        "is_intraday": False,
        "is_null_set": False,
        "schema": "statistics",
        "publisher_id": int(publisher_id),
        "channel_id": 0,
        "dataset": dataset,
        "instrument_id": int(instrument_id),
        "raw_symbol": raw_symbol,
    }

    for col, val in defaults.items():
        if col not in df.columns:
            df[col] = val

    # Ensure the three timestamps exist (fixture should provide them, but be defensive)
    for col in ("ts_recv", "ts_event", "ts_ref"):
        if col not in df.columns:
            raise ValueError(f"test fixture missing required timestamp column: {col}")

    # Ensure trading_date exists and is populated for daily stat types.
    # Your coerce derives trading_date only if the column is missing, not if present but NaT.
    if "trading_date" not in df.columns or df["trading_date"].isna().all():
        df["trading_date"] = pd.to_datetime(df["ts_ref"], utc=True).dt.floor("D")

    # Ensure required booleans exist
    if "is_final" not in df.columns:
        df["is_final"] = False
    if "is_actual" not in df.columns:
        df["is_actual"] = True

    # Some fixtures might omit stat_flags; your schema requires it
    if "stat_flags" not in df.columns:
        df["stat_flags"] = 0

    # Ensure numeric columns are present
    if "price" not in df.columns:
        df["price"] = 0.0
    if "sequence" not in df.columns:
        df["sequence"] = 0

    # coerce_statistics_1d will:
    # - enforce UTC tz-aware timestamps
    # - coerce dtypes
    # - enforce column order and validate
    out = coerce_statistics_1d(
        df, dataset=dataset, schema="statistics", ensure_column_order=True
    )

    # One extra guard: ensure no missing columns (should be impossible after coerce)
    missing = [c for c in STATISTICS_1D.required if c not in out.columns]
    if missing:
        raise ValueError(f"canonicalize failed: missing columns {missing}")

    return out


def patch_statistics_1d_orchestrator_offline(
    monkeypatch: MonkeyPatch,
    *,
    cfg: OfflineStats1DConfig,
    stats_df_factory: Callable[[int], pd.DataFrame] | None = None,
) -> None:
    if stats_df_factory is None:
        stats_df_factory = lambda iid: make_statistics_1d_rawish_df(
            instrument_id=iid,
            raw_symbol="TEST.2020-01",
        )

    # Gates: bypass watermark requirement
    monkeypatch.setattr(
        orch_mod,
        "_gate_definitions_available",
        lambda *, backend, product_id: orch_mod.GateResult(
            name="instrument_definitions_watermark_exists",
            ok=True,
            detail="watermark=test",
        ),
    )

    # Avoid RefDataAPI period lookup via contract_year_month
    monkeypatch.setattr(orch_mod, "contract_year_month", lambda c: (2020, 1))

    # Dataset range availability
    monkeypatch.setattr(
        orch_mod,
        "get_dataset_range",
        lambda client, dataset, schema: SimpleNamespace(
            start=cfg.avail_start,
            end=cfg.avail_end,
        ),
    )

    # Mapping: deterministic identity
    monkeypatch.setattr(
        orch_mod,
        "resolve_databento_instrument",
        lambda backend, c: OfflineIdent(
            feed=cfg.feed,
            dataset=cfg.dataset,
            publisher_id=cfg.publisher_id,
            instrument_id=cfg.instrument_id,
            raw_symbol=str(getattr(c, "contract_id", "UNKNOWN")),
        ),
    )

    # Lifecycle: disabled
    monkeypatch.setattr(
        orch_mod,
        "read_lifecycle_for_product_instrument",
        lambda *, store, product_id, publisher_id, instrument_id: None,
    )

    # Cost estimator: deterministic
    monkeypatch.setattr(
        orch_mod,
        "estimate_cost_statistics_1d",
        lambda **kwargs: SimpleNamespace(
            estimated_cost_usd=float(cfg.estimated_cost_usd)
        ),
    )

    # Vendor pull: deterministic fixture
    monkeypatch.setattr(
        orch_mod,
        "pull_statistics_1d_by_instrument_id",
        lambda **kwargs: stats_df_factory(cfg.instrument_id),
    )

    # Normalization: canonicalize to match schema/store contract
    monkeypatch.setattr(
        orch_mod,
        "normalize_statistics_1d",
        lambda df_raw, dataset, raw_symbol: _canonicalize_for_store(
            df_raw,
            dataset=dataset,
            publisher_id=cfg.publisher_id,
            instrument_id=cfg.instrument_id,
            raw_symbol=str(raw_symbol),
        ),
    )
