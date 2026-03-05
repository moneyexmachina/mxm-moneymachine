# mxm/v1/utils/json_normalise.py
from __future__ import annotations

from typing import cast

from mxm.types import JSONValue


class JSONNormaliseError(ValueError):
    pass


def json_value_from_obj(x: object) -> JSONValue:
    """
    Convert an arbitrary Python object tree into strict JSONValue.

    Accepts only:
    - None, bool, int, float, str
    - list and tuple (recursively JSON-compatible)
    - dict with str keys (recursively JSON-compatible)

    Rejects all other values (including YAML timestamps, sets, bytes, etc.).
    """
    if x is None or isinstance(x, (bool, int, float, str)):
        return x

    if isinstance(x, list):
        xs = cast(list[object], x)
        return [json_value_from_obj(v) for v in xs]

    if isinstance(x, tuple):
        xs = cast(tuple[object, ...], x)
        return [json_value_from_obj(v) for v in xs]

    if isinstance(x, dict):
        d = cast(dict[object, object], x)
        out: dict[str, JSONValue] = {}
        for k, v in d.items():
            if not isinstance(k, str):
                raise JSONNormaliseError(
                    f"JSON object keys must be str; got {type(k).__name__}"
                )
            out[k] = json_value_from_obj(v)
        return out

    raise JSONNormaliseError(f"Value is not JSON-serialisable: {type(x).__name__}")
