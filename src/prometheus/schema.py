"""JSON Schema for tool parameters, derived from type hints."""

from __future__ import annotations

import inspect
import types
from enum import Enum
from typing import Annotated, Any, Literal, Union, get_args, get_origin

_JSON_TYPES: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
}


def schema_from_function(fn: Any) -> dict[str, Any]:
    """Build a JSON Schema object from a callable's signature and hints."""

    hints = _type_hints(fn)
    signature = inspect.signature(fn)
    properties: dict[str, Any] = {}
    required: list[str] = []

    for name, param in signature.parameters.items():
        if name in {"self", "cls"}:
            continue
        if param.kind is inspect.Parameter.VAR_POSITIONAL:
            raise TypeError(f"{fn.__name__} cannot accept *{name}")
        if param.kind is inspect.Parameter.VAR_KEYWORD:
            raise TypeError(f"{fn.__name__} cannot accept **{name}")
        if param.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise TypeError(f"{fn.__name__} cannot use positional-only parameter {name!r}")

        annotated = hints.get(name, str)
        schema, description = _annotated(annotated)
        prop = python_to_json_schema(schema)
        if description:
            prop["description"] = description
        if param.default is not inspect.Parameter.empty:
            if _json_safe(param.default):
                prop["default"] = param.default
        else:
            required.append(name)
        properties[name] = prop

    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


def python_to_json_schema(tp: Any) -> dict[str, Any]:
    """Map a Python type annotation to a JSON Schema fragment."""

    origin = get_origin(tp)
    args = get_args(tp)

    if origin is Annotated:
        return python_to_json_schema(args[0])

    if origin in {Union, types.UnionType}:
        return _union_schema(args)

    if origin is Literal:
        return {"enum": list(args)}

    if origin in {list, tuple} or tp in {list, tuple}:
        if not args:
            return {"type": "array"}
        return {"type": "array", "items": python_to_json_schema(args[0])}

    if origin is dict or tp is dict:
        return {"type": "object"}

    if tp in _JSON_TYPES:
        return {"type": _JSON_TYPES[tp]}

    if isinstance(tp, type) and issubclass(tp, Enum):
        return {"enum": [member.value for member in tp]}

    raise TypeError(f"unsupported tool parameter type: {tp!r}")


def docstring_description(fn: Any) -> str:
    doc = inspect.getdoc(fn)
    if not doc:
        return ""
    return doc.split("\n\n", 1)[0].strip()


def _annotated(tp: Any) -> tuple[Any, str | None]:
    if get_origin(tp) is Annotated:
        args = get_args(tp)
        notes = [item for item in args[1:] if isinstance(item, str)]
        return args[0], notes[0] if notes else None
    return tp, None


def _union_schema(args: tuple[Any, ...]) -> dict[str, Any]:
    non_none = [arg for arg in args if arg is not type(None)]
    if len(non_none) == 1 and len(non_none) != len(args):
        return python_to_json_schema(non_none[0])
    return {"anyOf": [python_to_json_schema(arg) for arg in args]}


def _type_hints(fn: Any) -> dict[str, Any]:
    try:
        return dict(inspect.get_annotations(fn, eval_str=True))
    except Exception:
        return {}


def _json_safe(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool, list, dict))
