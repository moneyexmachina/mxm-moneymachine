from __future__ import annotations

from typing import TypedDict


class DatasetRangeSchema(TypedDict):
    start: str
    end: str


class DatasetRangeResponse(DatasetRangeSchema, total=False):
    """
    Vendor dataset-range response.

    Required top-level keys:
      - 'start': ISO8601 timestamp (inclusive start)
      - 'end':   ISO8601 timestamp (exclusive end)

    Optional top-level keys:
      - 'schema': mapping keyed by schema name with per-schema ranges
    """

    schema: dict[str, DatasetRangeSchema]
