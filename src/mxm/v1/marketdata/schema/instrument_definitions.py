from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from mxm.v1.utils.time_utils import fmt_run_ts

# ----------------------------
# Table names (SQLite)
# ----------------------------

TABLE_EVENTS = "instrument_definition_events"
TABLE_WATERMARKS = "instrument_definition_watermarks"
TABLE_CURRENT = "instrument_definition_current"


# ----------------------------
# JSON canonicalisation
# ----------------------------


def _json_safe_scalar(x: Any) -> Any:
    """
    Convert pandas/numpy scalars and missing values into JSON-safe Python values.
    """
    # Missing values
    if x is None:
        return None

    # pandas missing / NaT / numpy NaN
    try:
        if pd.isna(x):
            return None
    except Exception:
        # pd.isna can raise on some objects; ignore and continue.
        pass

    # Timestamps
    if isinstance(x, pd.Timestamp):
        return fmt_run_ts(x)

    # numpy scalar -> python scalar
    if isinstance(x, (np.generic,)):
        return x.item()

    # bytes -> decode (conservative)
    if isinstance(x, (bytes, bytearray)):
        return x.decode("utf-8", errors="replace")

    return x


def canonicalise_record(record: dict[str, Any]) -> dict[str, Any]:
    """
    Produce a JSON-serialisable, deterministic record suitable for hashing.

    Rules:
    - timestamps -> ISO8601 UTC with Z
    - numpy/pandas scalars -> python scalars
    - NaN/NA/NaT -> None
    - no transformation of field names or meaning
    """
    out: dict[str, Any] = {}
    for k, v in record.items():
        out[k] = _json_safe_scalar(v)
    return out


def canonical_json(record: dict[str, Any]) -> str:
    """
    Deterministic JSON encoding used for event_uid hashing and SQLite payload_json.

    Rules:
    - sort_keys=True to stabilise order
    - separators=(',', ':') to remove whitespace variance
    - ensure_ascii=False (payload may contain symbols)
    - allow_nan=False to prevent NaN literals
    """
    rec = canonicalise_record(record)
    return json.dumps(
        rec,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    )


def event_uid_from_payload_json(payload_json: str) -> str:
    """
    Deterministic UID for idempotency.
    """
    h = hashlib.sha256()
    h.update(payload_json.encode("utf-8"))
    return h.hexdigest()


# ----------------------------
# Convenience datatypes
# ----------------------------


@dataclass(frozen=True)
class InstrumentDefinitionEvent:
    event_uid: str
    publisher_id: int
    instrument_id: int
    ts_event: str
    ts_recv: str
    security_update_action: str
    rtype: int | None
    payload_json: str
