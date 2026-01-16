# src/mxm/v1/marketdata/vendor_mapping/databento.py
"""
Databento vendor helpers for contract mapping.

This module provides *vendor-facing* utilities to:
- enumerate instruments for a product family (typically via parent symbology)
- retrieve instrument definitions / metadata
- normalize the result into a join-friendly table keyed by (exp_year, exp_month)

Design constraints:
- No mxm-refdata imports here (vendor side only).
- Avoid embedding auth/secret handling; accept a pre-configured Databento client.
- Be tolerant to Databento SDK surface changes by using small adapter logic.

IMPORTANT:
The exact Databento method names can vary by SDK version. This module is written to
be resilient by probing available methods and handling dict-like / object-like rows.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Iterable, Optional

import pandas as pd

# -------------------------
# Public dataclass (optional)
# -------------------------


@dataclass(frozen=True, slots=True)
class DatabentoInstrumentRow:
    instrument_id: int
    raw_symbol: Optional[str]
    expiration_date: Optional[str]  # ISO "YYYY-MM-DD"
    exp_year: Optional[int]
    exp_month: Optional[int]
    meta: dict[str, Any]


# -------------------------
# Small utilities
# -------------------------


def _get(obj: Any, key: str, default: Any = None) -> Any:
    """
    Read key from dict-like or attribute-like objects.
    """
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _to_iso_date(d: Any) -> Optional[str]:
    if d is None:
        return None
    if isinstance(d, str):
        # Assume already ISO or close enough; do not parse aggressively.
        return d
    if isinstance(d, datetime):
        return d.date().isoformat()
    if isinstance(d, date):
        return d.isoformat()
    return None


def _extract_expiration_fields(
    defn: Any,
) -> tuple[Optional[str], Optional[int], Optional[int]]:
    """
    Extract a usable expiration anchor from a Databento instrument definition row.

    Databento may expose multiple date fields depending on dataset / venue.
    We try a small ordered set of likely candidates.

    Returns:
        (expiration_date_iso, exp_year, exp_month)
    """
    # Common candidates seen across vendor metadata APIs:
    # - expiration
    # - expire_date
    # - expiration_date
    # - last_trade_date
    # - maturity_date
    candidates = [
        "expiration",
        "expiration_date",
        "expire_date",
        "last_trade_date",
        "maturity_date",
    ]

    exp_iso: Optional[str] = None
    for k in candidates:
        v = _get(defn, k)
        exp_iso = _to_iso_date(v)
        if exp_iso:
            break

    if not exp_iso:
        return None, None, None

    try:
        yyyy, mm, _dd = exp_iso.split("-", 2)
        return exp_iso, int(yyyy), int(mm)
    except Exception:
        return exp_iso, None, None


def _records_from_any(x: Any) -> list[Any]:
    """
    Normalize Databento SDK return types into a list of rows.

    We handle:
    - list[dict] / list[obj]
    - pandas.DataFrame
    - objects exposing .to_df()
    - objects exposing .data or .items
    """
    if x is None:
        return []

    if isinstance(x, list):
        return x

    if isinstance(x, pd.DataFrame):
        return x.to_dict(orient="records")

    to_df = getattr(x, "to_df", None)
    if callable(to_df):
        df = to_df()
        if isinstance(df, pd.DataFrame):
            return df.to_dict(orient="records")

    # some SDK responses may be dict-like with "data" key
    if isinstance(x, dict) and "data" in x:
        return _records_from_any(x["data"])

    # last resort: if iterable of rows
    try:
        return list(x)
    except Exception:
        return [x]


# -------------------------
# Databento adapters
# -------------------------


def resolve_parent_symbol(
    client: Any,
    *,
    symbol: str,
    stype_in: str,
    stype_out: str = "parent",
) -> str:
    """
    Resolve a vendor symbol to a parent symbology.

    You will need to decide what `symbol` you pass:
    - could be a raw_symbol root / continuous symbol / vendor-specific "parent" handle
    - could be something discovered by your existing 20_symbol_discovery_es.py

    This function tries a few likely SDK entry points. If none exist, it raises.

    Returns:
        parent_symbol (string)
    """
    # Likely entry points (SDK-version-dependent):
    # - client.symbology.resolve(...)
    # - client.reference.resolve_symbol(...)
    # - client.symbology.resolve_symbol(...)
    symbology = getattr(client, "symbology", None)
    reference = getattr(client, "reference", None)

    # 1) client.symbology.resolve(...)
    if symbology is not None and hasattr(symbology, "resolve"):
        res = symbology.resolve(
            symbols=[symbol], stype_in=stype_in, stype_out=stype_out
        )
        rows = _records_from_any(res)
        if not rows:
            raise RuntimeError(
                f"No rows returned from symbology.resolve for symbol={symbol!r}"
            )
        # Heuristic: first row contains output in "symbol" or "stype_out" keyed field
        row0 = rows[0]
        out = (
            _get(row0, stype_out)
            or _get(row0, "symbol")
            or _get(row0, "resolved_symbol")
        )
        if not out:
            raise RuntimeError(
                f"Could not extract parent from resolve response row: {row0!r}"
            )
        return str(out)

    # 2) client.reference.resolve_symbol(...)
    if reference is not None and hasattr(reference, "resolve_symbol"):
        res = reference.resolve_symbol(
            symbol=symbol, stype_in=stype_in, stype_out=stype_out
        )
        rows = _records_from_any(res)
        if not rows:
            raise RuntimeError(
                f"No rows returned from reference.resolve_symbol for symbol={symbol!r}"
            )
        row0 = rows[0]
        out = (
            _get(row0, stype_out)
            or _get(row0, "symbol")
            or _get(row0, "resolved_symbol")
        )
        if not out:
            raise RuntimeError(
                f"Could not extract parent from resolve response row: {row0!r}"
            )
        return str(out)

    raise RuntimeError(
        "Databento client does not expose a recognized symbology resolution method. "
        "Please adapt resolve_parent_symbol() to your installed SDK."
    )


def list_instruments_for_parent(
    client: Any,
    *,
    parent: str,
    dataset: str,
) -> list[Any]:
    """
    Enumerate instruments under a parent identifier.

    This tries a few likely SDK shapes. Returns a list of raw rows/objects.
    """
    reference = getattr(client, "reference", None)
    symbology = getattr(client, "symbology", None)

    # Likely entry points:
    # - client.reference.list_instruments(dataset=..., parent=...)
    # - client.reference.get_instruments(...)
    # - client.symbology.instruments(...)
    if reference is not None and hasattr(reference, "list_instruments"):
        res = reference.list_instruments(dataset=dataset, parent=parent)
        return _records_from_any(res)

    if reference is not None and hasattr(reference, "get_instruments"):
        res = reference.get_instruments(dataset=dataset, parent=parent)
        return _records_from_any(res)

    if symbology is not None and hasattr(symbology, "list_instruments"):
        res = symbology.list_instruments(dataset=dataset, parent=parent)
        return _records_from_any(res)

    raise RuntimeError(
        "Databento client does not expose a recognized instruments enumeration method. "
        "Please adapt list_instruments_for_parent() to your installed SDK."
    )


def get_instrument_definitions(
    client: Any,
    *,
    instrument_ids: list[int],
    dataset: str,
) -> list[Any]:
    """
    Retrieve instrument definitions (metadata) for instrument_ids.

    Returns list of definition rows (dict-like or object-like).
    """
    reference = getattr(client, "reference", None)

    # Likely entry points:
    # - client.reference.get_definitions(dataset=..., instrument_ids=[...])
    # - client.reference.definitions(...)
    # - client.reference.get_instrument_definitions(...)
    if reference is not None and hasattr(reference, "get_definitions"):
        res = reference.get_definitions(dataset=dataset, instrument_ids=instrument_ids)
        return _records_from_any(res)

    if reference is not None and hasattr(reference, "definitions"):
        res = reference.definitions(dataset=dataset, instrument_ids=instrument_ids)
        return _records_from_any(res)

    if reference is not None and hasattr(reference, "get_instrument_definitions"):
        res = reference.get_instrument_definitions(
            dataset=dataset, instrument_ids=instrument_ids
        )
        return _records_from_any(res)

    raise RuntimeError(
        "Databento client does not expose a recognized instrument definitions method. "
        "Please adapt get_instrument_definitions() to your installed SDK."
    )


# -------------------------
# High-level normalization
# -------------------------


def normalize_instruments_with_definitions(
    instruments: Iterable[Any],
    definitions: Iterable[Any],
) -> pd.DataFrame:
    """
    Build a normalized DataFrame keyed by Databento instrument_id with expiry anchor fields.

    Expected minimal fields (best-effort):
    - instrument_id (int)
    - raw_symbol (str)
    - expiration_date (ISO str)
    - exp_year (int)
    - exp_month (int)

    We merge instrument rows with definitions by instrument_id if possible.
    """
    inst_rows = []
    for r in instruments:
        inst_id = _get(r, "instrument_id")
        if inst_id is None:
            # Some APIs might name it "id"
            inst_id = _get(r, "id")
        if inst_id is None:
            continue

        inst_rows.append(
            {
                "instrument_id": int(inst_id),
                "raw_symbol": _get(r, "raw_symbol")
                or _get(r, "symbol")
                or _get(r, "rawsymbol"),
                "inst_meta": dict(r) if isinstance(r, dict) else {},
            }
        )

    def_rows = []
    for d in definitions:
        inst_id = _get(d, "instrument_id") or _get(d, "id")
        if inst_id is None:
            continue
        exp_iso, exp_year, exp_month = _extract_expiration_fields(d)
        def_rows.append(
            {
                "instrument_id": int(inst_id),
                "expiration_date": exp_iso,
                "exp_year": exp_year,
                "exp_month": exp_month,
                "def_meta": dict(d) if isinstance(d, dict) else {},
            }
        )

    df_inst = pd.DataFrame(inst_rows)
    df_def = pd.DataFrame(def_rows)

    if df_inst.empty:
        return pd.DataFrame(
            columns=[
                "instrument_id",
                "raw_symbol",
                "expiration_date",
                "exp_year",
                "exp_month",
            ]
        )

    if df_def.empty:
        # definitions unavailable; return instruments only
        df_inst["expiration_date"] = None
        df_inst["exp_year"] = None
        df_inst["exp_month"] = None
        return df_inst[
            ["instrument_id", "raw_symbol", "expiration_date", "exp_year", "exp_month"]
        ]

    df = df_inst.merge(df_def, on="instrument_id", how="left")

    # Flatten meta: keep minimal observability; callers can keep raw meta if needed.
    return df[
        ["instrument_id", "raw_symbol", "expiration_date", "exp_year", "exp_month"]
    ]


def fetch_product_instruments_table(
    client: Any,
    *,
    dataset: str,
    parent: str,
) -> pd.DataFrame:
    """
    End-to-end vendor-side fetch for one product-parent:
    - enumerate instruments under parent
    - fetch definitions
    - normalize to a join-friendly table

    This is the main function the mapping script should call once parent is known.
    """
    instruments = list_instruments_for_parent(client, parent=parent, dataset=dataset)

    instrument_ids: list[int] = []
    for r in instruments:
        inst_id = _get(r, "instrument_id") or _get(r, "id")
        if inst_id is None:
            continue
        instrument_ids.append(int(inst_id))

    # Remove duplicates while preserving order
    seen = set()
    instrument_ids_unique: list[int] = []
    for x in instrument_ids:
        if x not in seen:
            seen.add(x)
            instrument_ids_unique.append(x)

    definitions = get_instrument_definitions(
        client, instrument_ids=instrument_ids_unique, dataset=dataset
    )

    return normalize_instruments_with_definitions(instruments, definitions)
