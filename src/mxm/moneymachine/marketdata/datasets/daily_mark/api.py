from __future__ import annotations

from pathlib import Path

import pandas as pd

from mxm.moneymachine.marketdata.datasets.daily_mark.store import DailyMarkStore
from mxm.moneymachine.marketdata.stores.layout import MarketdataLayout
from mxm.refdata.api.ref_data_api import RefDataAPI

# ---------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------


def read_daily_mark_contract(
    *,
    calendar_id: str,
    contract_id: str,
    root: Path | None = None,
    start_session_id: int | None = None,
    end_session_id: int | None = None,
) -> pd.DataFrame:
    """
    Read daily_mark for a single contract and calendar identity.

    Canonical output schema
    -----------------------
    DataFrame with:
      - session_id
      - contract_id
      - product_id
      - ... value/provenance columns from parquet ...

    Slicing semantics
    -----------------
    Slice is applied on session_id with half-open interval
    [start_session_id, end_session_id).

    Notes
    -----
    - Missing values are preserved.
    - Output is sorted deterministically by (product_id, contract_id, session_id).
    """
    layout = MarketdataLayout(root=(root or (Path.home() / ".mxm")))
    store = DailyMarkStore(layout=layout)
    api = RefDataAPI()

    contract = api.get_contract_by_id(contract_id)
    product_id = contract.product_id

    df = store.read(
        calendar_id=calendar_id,
        contract_id=contract_id,
        start_session_id=start_session_id,
        end_session_id=end_session_id,
    )
    return _canonicalise(df=df, product_id=product_id, contract_id=contract_id)


def read_daily_mark_contract_meta(
    *,
    calendar_id: str,
    contract_id: str,
    root: Path | None = None,
) -> dict[str, object] | None:
    """
    Read daily_mark meta for a single contract and calendar identity.

    This is the contract-level companion to `read_daily_mark_contract(...)`.

    Returns
    -------
    dict[str, object] | None
        Enriched meta dict if the underlying daily_mark artifact/meta exists,
        else None.

    Enriched fields
    ---------------
    Adds the following contract-centric fields on top of the stored meta:
      - contract_id
      - product_id
      - calendar_id
      - path
    """
    layout = MarketdataLayout(root=(root or (Path.home() / ".mxm")))
    store = DailyMarkStore(layout=layout)
    api = RefDataAPI()

    contract = api.get_contract_by_id(contract_id)
    product_id = contract.product_id

    meta = store.read_meta(
        calendar_id=calendar_id,
        contract_id=contract_id,
    )
    if meta is None:
        return None

    out = dict(meta)
    out["contract_id"] = contract_id
    out["product_id"] = product_id
    out["calendar_id"] = calendar_id
    out["path"] = str(
        store.mark_path(
            calendar_id=calendar_id,
            contract_id=contract_id,
        )
    )
    return out


def read_daily_mark_product(
    *,
    calendar_id: str,
    product_id: str,
    root: Path | None = None,
    start_session_id: int | None = None,
    end_session_id: int | None = None,
) -> pd.DataFrame:
    """
    Read daily_mark for all contracts we have for a product_id under one calendar_id.

    Interpretation of "contracts we have"
    -------------------------------------
    This function enumerates the product's FuturesContracts from refdata and reads
    daily_mark surfaces from the local parquet store by (calendar_id, contract_id).

    Contracts without a stored daily_mark surface are skipped (by design) and simply
    contribute no rows.

    Output schema
    -------------
    Same canonical schema as read_daily_mark_contract():
      session_id, contract_id, product_id, ...

    No rolling/selection is performed here; that belongs in synthetic_asset layer.
    """
    layout = MarketdataLayout(root=(root or (Path.home() / ".mxm")))
    store = DailyMarkStore(layout=layout)

    frames: list[pd.DataFrame] = []
    api = RefDataAPI()

    for contract in list(api.get_contracts_for_product(product_id)):
        contract_id = str(contract.contract_id)

        try:
            df = store.read(
                calendar_id=calendar_id,
                contract_id=contract_id,
                start_session_id=start_session_id,
                end_session_id=end_session_id,
            )
        except FileNotFoundError:
            # Explicitly skip contracts without a local daily_mark surface.
            continue

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
    *,
    df: pd.DataFrame,
    product_id: str,
    contract_id: str,
) -> pd.DataFrame:
    if df.empty:
        return _empty_canonical()

    out = df.copy()
    if "session_id" not in out.columns:
        raise ValueError("daily_mark parquet missing required column 'session_id'")

    out.insert(1, "product_id", product_id)

    # Defensive contract identity check at API boundary.
    unique_contract_ids = out["contract_id"].dropna().unique().tolist()
    if len(unique_contract_ids) != 1 or str(unique_contract_ids[0]) != contract_id:
        raise ValueError(
            "daily_mark parquet content does not match requested contract_id: "
            f"expected {contract_id!r}, got {unique_contract_ids!r}"
        )

    return _sort(out)


def _sort(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.sort_values(
        by=["product_id", "contract_id", "session_id"],
        kind="mergesort",
    ).reset_index(drop=True)


def _empty_canonical() -> pd.DataFrame:
    out = pd.DataFrame(columns=["session_id", "contract_id", "product_id"])
    out["session_id"] = pd.Series([], dtype="int32")
    out["contract_id"] = pd.Series([], dtype="object")
    out["product_id"] = pd.Series([], dtype="object")
    return out
