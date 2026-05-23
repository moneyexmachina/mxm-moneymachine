from __future__ import annotations

from dataclasses import dataclass

from mxm.moneymachine.marketdata.types import (
    DatasetRangeResponse,
    DatasetRangeSchema,
    InstrumentDefinitionsClient,
)

# TODO(mxm-moneymachine v1):
# Add runtime contract tests for Databento metadata responses.
#
# Current guarantees are static only:
# - DatasetMetadataClient protocol
# - DatasetRangeResponse TypedDict
#
# Missing:
# 1. Structural unit tests validating parsing logic against representative
#    payload fixtures.
# 2. Integration smoke tests against the real Databento Historical client to
#    confirm runtime compatibility and detect upstream API shape drift.
#
# Suggested future tests:
# - tests/unittests/.../test_dataset_range_parsing.py
# - tests/integration/.../test_databento_dataset_range_contract.py
#
# Deferred during pyright cleanup phase to avoid scope expansion.


@dataclass(frozen=True)
class DatasetRange:
    start: str
    end: str


def _range_from_payload(payload: DatasetRangeSchema) -> DatasetRange:
    return DatasetRange(start=payload["start"], end=payload["end"])


def get_dataset_range(
    *,
    client: InstrumentDefinitionsClient,
    dataset: str,
    schema: str | None = None,
) -> DatasetRange:
    payload: DatasetRangeResponse = client.metadata.get_dataset_range(dataset=dataset)

    if schema is not None:
        schema_map = payload.get("schema")
        if schema_map is not None:
            schema_payload = schema_map.get(schema)
            if schema_payload is not None:
                return _range_from_payload(schema_payload)

    return _range_from_payload(payload)


def clamp_end(*, end: str, available: DatasetRange) -> str:
    return end if end <= available.end else available.end


def clamp_start(*, start: str, available: DatasetRange) -> str:
    return start if start >= available.start else available.start
