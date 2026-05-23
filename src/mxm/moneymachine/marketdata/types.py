from __future__ import annotations

from typing import Protocol, TypedDict


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


class DatasetMetadataClient(Protocol):
    """
    Minimal protocol for vendor dataset metadata access used by MXM orchestrators.
    """

    def get_dataset_range(self, dataset: str) -> DatasetRangeResponse:
        """
        Return a mapping containing at least 'start' and 'end' ISO8601 timestamps,
        and optionally a per-schema mapping under 'schema'.

        Exact structure is vendor-defined; orchestrators should read only the keys
        they require.
        """
        ...


class InstrumentDefinitionsClient(Protocol):
    """
    Minimal protocol required by the instrument_definitions orchestrator.

    This is a control-plane abstraction over vendor clients (e.g. Databento Historical)
    that exposes dataset-range discovery via `client.metadata.get_dataset_range(...)`.
    """

    metadata: DatasetMetadataClient
