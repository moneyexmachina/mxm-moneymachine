from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypedDict, cast

import databento as db

# TODO(mxm-moneymachine v1):
# Add runtime contract tests for Databento metadata responses.
#
# Current guarantees are static only:
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


class DatasetRangeSchema(TypedDict):
    start: str
    end: str


class DatasetRangeResponse(DatasetRangeSchema, total=False):
    schema: dict[str, DatasetRangeSchema]


@dataclass(frozen=True)
class DatasetRange:
    start: str
    end: str


def _range_from_payload(payload: DatasetRangeSchema) -> DatasetRange:
    return DatasetRange(start=payload["start"], end=payload["end"])


def _as_string_object_dict(
    value: object,
    *,
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a dict")

    raw = cast(dict[object, object], value)

    result: dict[str, object] = {}
    for key, item in raw.items():
        if not isinstance(key, str):
            raise TypeError(f"{label} keys must be strings")
        result[key] = item

    return result


def _coerce_dataset_range_schema(
    payload: Mapping[str, object],
) -> DatasetRangeSchema:
    start = payload.get("start")
    end = payload.get("end")

    if not isinstance(start, str):
        raise TypeError("dataset range payload missing string 'start'")

    if not isinstance(end, str):
        raise TypeError("dataset range payload missing string 'end'")

    return {"start": start, "end": end}


def _coerce_dataset_range_response(
    payload: Mapping[str, object],
) -> DatasetRangeResponse:
    base = _coerce_dataset_range_schema(payload)

    response: DatasetRangeResponse = {
        "start": base["start"],
        "end": base["end"],
    }

    schema_raw = payload.get("schema")
    if schema_raw is None:
        return response

    schema_mapping = _as_string_object_dict(
        schema_raw,
        label="dataset range payload 'schema'",
    )

    schema: dict[str, DatasetRangeSchema] = {}
    for schema_name, schema_payload_raw in schema_mapping.items():
        schema_payload = _as_string_object_dict(
            schema_payload_raw,
            label=f"dataset range schema payload for {schema_name!r}",
        )
        schema[schema_name] = _coerce_dataset_range_schema(schema_payload)

    response["schema"] = schema
    return response


def get_dataset_range(
    *,
    client: db.Historical,
    dataset: str,
    schema: str | None = None,
) -> DatasetRange:
    raw_payload = client.metadata.get_dataset_range(dataset=dataset)
    payload_mapping = _as_string_object_dict(
        raw_payload,
        label="dataset range response",
    )
    payload = _coerce_dataset_range_response(payload_mapping)

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
