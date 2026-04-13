from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import cast

from mxm.types import JSONValue


class JSONNormaliseError(ValueError):
    pass


def json_value_from_obj(
    x: object,
    *,
    fallback_repr: bool = False,
) -> JSONValue:
    """
    Convert an arbitrary Python object tree into JSONValue.

    Accepts:
    - None, bool, int, float, str
    - dataclass instances
    - list and tuple (recursively JSON-compatible)
    - dict with str keys (recursively JSON-compatible)

    By default, rejects all other values.

    Parameters
    ----------
    x:
        Object to normalise into JSONValue.
    fallback_repr:
        If True, unsupported leaf values are converted to
        ``{"__repr__": repr(x)}`` instead of raising.

    Returns
    -------
    JSONValue
        JSON-compatible representation of `x`.

    Raises
    ------
    JSONNormaliseError
        If `x` contains unsupported values and `fallback_repr=False`.
    """
    if x is None or isinstance(x, (bool, int, float, str)):
        return x

    if is_dataclass(x) and not isinstance(x, type):
        return json_value_from_obj(asdict(x), fallback_repr=fallback_repr)

    if isinstance(x, list):
        xs = cast(list[object], x)
        return [json_value_from_obj(v, fallback_repr=fallback_repr) for v in xs]

    if isinstance(x, tuple):
        xs = cast(tuple[object, ...], x)
        return [json_value_from_obj(v, fallback_repr=fallback_repr) for v in xs]

    if isinstance(x, dict):
        d = cast(dict[object, object], x)
        out: dict[str, JSONValue] = {}
        for k, v in d.items():
            if not isinstance(k, str):
                raise JSONNormaliseError(
                    f"JSON object keys must be str; got {type(k).__name__}"
                )
            out[k] = json_value_from_obj(v, fallback_repr=fallback_repr)
        return out

    if fallback_repr:
        return {"__repr__": repr(x)}

    raise JSONNormaliseError(f"Value is not JSON-serialisable: {type(x).__name__}")
