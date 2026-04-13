from __future__ import annotations

from dataclasses import dataclass

import pytest

from mxm.v1.utils.json_normalise import JSONNormaliseError, json_value_from_obj


@dataclass(frozen=True)
class Example:
    a: int
    b: str


class Unsupported:
    pass


def test_json_value_from_obj_primitives() -> None:
    assert json_value_from_obj(None) is None
    assert json_value_from_obj(True) is True
    assert json_value_from_obj(1) == 1
    assert json_value_from_obj(1.5) == 1.5
    assert json_value_from_obj("x") == "x"


def test_json_value_from_obj_list_and_tuple() -> None:
    assert json_value_from_obj([1, "x", None]) == [1, "x", None]
    assert json_value_from_obj((1, "x", None)) == [1, "x", None]


def test_json_value_from_obj_dict_and_nested_values() -> None:
    x = {
        "a": 1,
        "b": [2, 3],
        "c": {"d": "x"},
    }
    assert json_value_from_obj(x) == {
        "a": 1,
        "b": [2, 3],
        "c": {"d": "x"},
    }


def test_json_value_from_obj_dataclass() -> None:
    x = Example(a=1, b="two")
    assert json_value_from_obj(x) == {"a": 1, "b": "two"}


def test_json_value_from_obj_nested_dataclass() -> None:
    x = {
        "example": Example(a=3, b="z"),
        "items": [Example(a=4, b="y")],
    }
    assert json_value_from_obj(x) == {
        "example": {"a": 3, "b": "z"},
        "items": [{"a": 4, "b": "y"}],
    }


def test_json_value_from_obj_raises_on_non_string_dict_key() -> None:
    with pytest.raises(JSONNormaliseError, match="JSON object keys must be str"):
        json_value_from_obj({1: "x"})


def test_json_value_from_obj_raises_on_unsupported_value_by_default() -> None:
    with pytest.raises(JSONNormaliseError, match="Value is not JSON-serialisable"):
        json_value_from_obj(Unsupported())


def test_json_value_from_obj_fallback_repr_for_unsupported_value() -> None:
    out = json_value_from_obj(Unsupported(), fallback_repr=True)
    assert isinstance(out, dict)
    assert "__repr__" in out


def test_json_value_from_obj_fallback_repr_propagates_recursively() -> None:
    out = json_value_from_obj({"x": [Unsupported()]}, fallback_repr=True)
    assert isinstance(out, dict)
    assert isinstance(out["x"], list)
    assert isinstance(out["x"][0], dict)
    assert "__repr__" in out["x"][0]
