from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class DatasetRange:
    """
    Databento dataset availability.

    Semantics (per Databento metadata.get_dataset_range):
      - start is inclusive
      - end is exclusive
    """

    start: str
    end: str


def _range_from_payload(payload: dict[str, Any]) -> DatasetRange:
    return DatasetRange(start=payload["start"], end=payload["end"])


def get_dataset_range(
    *,
    client,  # databento.Historical; keep untyped to avoid hard dependency
    dataset: str,
    schema: str | None = None,
) -> DatasetRange:
    """
    Entitlement-aware availability range for dataset, schema-aware if available.

    Uses: client.metadata.get_dataset_range(dataset=...)
    """
    payload: dict[str, str | dict[str, str]] = client.metadata.get_dataset_range(
        dataset=dataset
    )

    if schema:
        schema_map = payload.get("schema") or {}
        schema_payload = schema_map.get(schema)
        if (
            isinstance(schema_payload, dict)
            and "start" in schema_payload
            and "end" in schema_payload
        ):
            return _range_from_payload(schema_payload)

    return _range_from_payload(payload)


def clamp_end(*, end: str, available: DatasetRange) -> str:
    """
    Clamp requested end (exclusive) to availability end (exclusive).
    ISO8601 Z timestamps are lexicographically comparable when normalized, as returned by Databento.
    """
    return end if end <= available.end else available.end


def clamp_start(*, start: str, available: DatasetRange) -> str:
    """
    Clamp requested start (inclusive) to availability start (inclusive).
    """
    return start if start >= available.start else available.start
