# src/mxm/v1/marketdata/datasets/daily_stats/api.py
from __future__ import annotations

from pathlib import Path

import pandas as pd
from mxm_refdata.api.ref_data_api import RefDataAPI

from mxm.v1.marketdata.datasets.daily_stats.store import DailyStatsStore
from mxm.v1.marketdata.mapping.vendors.databento.instrument_resolver import (
    resolve_databento_instrument,
)
from mxm.v1.marketdata.stores.layout import MarketdataLayout
from mxm.v1.marketdata.stores.sqlite.backend import SQLiteBackend
from mxm.v1.utils.date_utils import utc_day_start
from mxm.v1.utils.time_utils import ensure_utc_datetime_series

# ---------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------


def read_daily_stats_contract(
    *,
    contract_id: str,
    root: Path | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Read daily_stats for a single contract.

    Canonical output schema
    -----------------------
    DataFrame with:
      - trading_date  (UTC-midnight day label)
      - contract_id   (surface id, e.g. "{product_id}:{period_id}")
      - product_id
      - ... value/provenance columns from parquet ...

    Slicing semantics
    -----------------
    Slice is applied on trading_date with half-open interval [start, end).
    start/end are parsed via to_utc_ts(...).normalize().

    Notes
    -----
    - Missing values are preserved.
    - Output is sorted deterministically by (product_id, contract_id, trading_date).
    """
    layout = MarketdataLayout(root=(root or (Path.home() / ".mxm")))
    backend = _build_backend(layout)
    store = DailyStatsStore(layout=layout)
    api = RefDataAPI()
    contract = api.get_contract_by_id(contract_id)
    if contract is None:
        # Keep this explicit: downstream callers can decide whether to catch and treat as empty.
        raise ValueError(
            f"unknown contract_id={contract_id!r} (no refdata contract found)"
        )

    product_id = contract.product_id

    ident = resolve_databento_instrument(backend, contract)
    start_ts, end_ts = _parse_start_end(start, end)
    df = store.read(
        dataset=ident.dataset,
        publisher_id=ident.publisher_id,
        instrument_id=ident.instrument_id,
        start=start_ts,
        end=end_ts,
    )
    return _canonicalise(df=df, product_id=product_id, contract_id=contract_id)


def read_daily_stats_product(
    *,
    product_id: str,
    root: Path | None = None,
    start: str | pd.Timestamp | None = None,
    end: str | pd.Timestamp | None = None,
) -> pd.DataFrame:
    """
    Read daily_stats for all contracts we have for a product_id.

    Interpretation of "contracts we have"
    -------------------------------------
    This function enumerates the product's FuturesContracts from refdata, resolves each
    to a Databento instrument identity via SQLite mapping table, and reads daily_stats
    for those identities from the local parquet store.

    Contracts without a mapping are skipped (by design) and simply contribute no rows.

    Output schema
    -------------
    Same canonical schema as read_daily_stats_contract():
      trading_date, contract_id, product_id, ...

    No rolling/selection is performed here; that belongs in synthetic_asset layer.
    """
    layout = MarketdataLayout(root=(root or (Path.home() / ".mxm")))
    backend = _build_backend(layout)
    store = DailyStatsStore(layout=layout)
    start_ts, end_ts = _parse_start_end(start, end)

    frames: list[pd.DataFrame] = []
    api = RefDataAPI()

    for contract in list(api.get_contracts_for_product(product_id)):
        contract_id = contract.contract_id

        try:
            ident = resolve_databento_instrument(backend, contract)
        except Exception:
            # Explicitly skip unmapped/ambiguous contracts for this MVP read surface.
            # Inspection layer can later surface skipped counts.
            continue

        df = store.read(
            dataset=ident.dataset,
            publisher_id=ident.publisher_id,
            instrument_id=ident.instrument_id,
            start=start_ts,
            end=end_ts,
        )

        frames.append(
            _canonicalise(df=df, product_id=product_id, contract_id=contract_id)
        )

    if not frames:
        return _empty_canonical()

    out = pd.concat(frames, axis=0, ignore_index=True, sort=False)
    return _sort(out)


# ---------------------------------------------------------------------
# Canonicalisation
# ---------------------------------------------------------------------


def _canonicalise(
    *, df: pd.DataFrame, product_id: str, contract_id: str
) -> pd.DataFrame:
    if df is None or df.empty:
        return _empty_canonical()

    out = df.copy()
    if "session_date" not in out.columns:
        raise ValueError("daily_stats parquet missing required column 'session_date'")

    sd_utc = ensure_utc_datetime_series(out["session_date"])
    trading_date = sd_utc.dt.normalize()

    out = out.drop(columns=["session_date"])
    out.insert(0, "trading_date", trading_date)
    out.insert(1, "contract_id", contract_id)
    out.insert(2, "product_id", product_id)

    return _sort(out)


def _sort(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.sort_values(
        by=["product_id", "contract_id", "trading_date"], kind="mergesort"
    ).reset_index(drop=True)


def _empty_canonical() -> pd.DataFrame:
    out = pd.DataFrame(columns=["trading_date", "contract_id", "product_id"])
    out["trading_date"] = pd.to_datetime(pd.Series([], dtype="datetime64[ns, UTC]"))
    out["contract_id"] = pd.Series([], dtype="object")
    out["product_id"] = pd.Series([], dtype="object")
    return out


def _parse_start_end(
    start: str | pd.Timestamp | None,
    end: str | pd.Timestamp | None,
) -> tuple[pd.Timestamp | None, pd.Timestamp | None]:
    """
    Parse optional start/end into UTC-midnight boundaries.

    Semantics:
      - start/end are interpreted as day labels (UTC) and converted to 00:00Z.
      - Slicing is [start, end) at day resolution.
    """
    start_ts = utc_day_start(start) if start is not None else None
    end_ts = utc_day_start(end) if end is not None else None
    return start_ts, end_ts


# ---------------------------------------------------------------------
# Backend construction
# ---------------------------------------------------------------------


def _build_backend(layout: MarketdataLayout) -> SQLiteBackend:
    backend = SQLiteBackend(layout=layout)
    backend.ensure_migrated()
    return backend
