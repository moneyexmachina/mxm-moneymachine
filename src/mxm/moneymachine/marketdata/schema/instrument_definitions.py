from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import cast

import numpy as np
import pandas as pd

from mxm.moneymachine.utils.time_utils import fmt_run_ts
from mxm.types import JSONScalar

# ----------------------------
# Table names (SQLite)
# ----------------------------

TABLE_EVENTS = "instrument_definition_events"
TABLE_WATERMARKS = "instrument_definition_watermarks"
TABLE_CURRENT = "instrument_definition_current"


# ----------------------------
# JSON canonicalisation
# ----------------------------
def _is_missing_scalar(x: object) -> bool:
    """
    Return True for scalar pandas/numpy missing values.
    """
    if x is None:
        return True

    if x is pd.NaT:
        return True

    if isinstance(x, float):
        return bool(np.isnan(x))

    if isinstance(x, np.floating):
        value = cast(float, x)
        return bool(np.isnan(value))

    return False


def _json_safe_scalar(x: object) -> JSONScalar:
    """
    Convert pandas/numpy scalar-like values into JSON-safe Python scalars.
    """
    if _is_missing_scalar(x):
        return None

    if isinstance(x, pd.Timestamp):
        return fmt_run_ts(x)

    if isinstance(x, np.datetime64):
        dt64 = cast(object, x)
        return fmt_run_ts(pd.Timestamp(str(dt64)))

    if isinstance(x, np.generic):
        value = cast(object, x.item())

        if _is_missing_scalar(value):
            return None

        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")

        if isinstance(value, str | int | float | bool) or value is None:
            return value

        return repr(value)

    if isinstance(x, bytes | bytearray):
        return bytes(x).decode("utf-8", errors="replace")

    if isinstance(x, str | int | float | bool):
        return x

    return repr(x)


def canonicalise_record(record: dict[str, object]) -> dict[str, JSONScalar]:
    """
    Produce a JSON-serialisable, deterministic flat record suitable for hashing.

    Rules:
    - timestamps -> ISO8601 UTC with Z
    - numpy/pandas scalar values -> Python scalar values
    - NaN/NA/NaT -> None
    - unsupported leaf values -> repr(value)
    - no transformation of field names or meaning
    """
    return {k: _json_safe_scalar(v) for k, v in record.items()}


def canonical_json(record: dict[str, object]) -> str:
    """
    Deterministic JSON encoding used for event_uid hashing and SQLite payload_json.

    Rules:
    - sort_keys=True to stabilise order
    - separators=(',', ':') to remove whitespace variance
    - ensure_ascii=False because payloads may contain symbols
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
