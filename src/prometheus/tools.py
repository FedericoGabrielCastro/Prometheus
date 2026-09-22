"""Tool protocol, registry, and schema generation."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from functools import wraps
from typing import Any, ParamSpec, TypeVar, overload

from prometheus.schema import docstring_description, schema_from_function
from prometheus.types import ToolCall

P = ParamSpec("P")
R = TypeVar("R")

_SPEC_ATTR = "__prometheus_tool__"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]

    @property
    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }

    @classmethod
    def from_function(
        cls,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> ToolSpec:
        existing = getattr(fn, _SPEC_ATTR, None)
        if isinstance(existing, ToolSpec):
            tool_name = name or existing.name
            _validate_name(tool_name)
            return cls(
                name=tool_name,
                description=existing.description if description is None else description,
                parameters=existing.parameters,
                handler=existing.handler,
            )
        tool_name = name or fn.__name__
        _validate_name(tool_name)
        return cls(
            name=tool_name,
            description=docstring_description(fn) if description is None else description,
            parameters=schema_from_function(fn),
            handler=fn,
        )


@overload
def tool(fn: Callable[P, R]) -> Callable[P, R]: ...


@overload
def tool(
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]: ...


def tool(
    fn: Callable[P, R] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Callable[P, R] | Callable[[Callable[P, R]], Callable[P, R]]:
    """Mark a function as a tool. Schema comes from type hints and the docstring."""

    def decorate(func: Callable[P, R]) -> Callable[P, R]:
        spec = ToolSpec.from_function(func, name=name, description=description)

        @wraps(func)
        def wrapped(*args: P.args, **kwargs: P.kwargs) -> R:
            return func(*args, **kwargs)

        setattr(wrapped, _SPEC_ATTR, spec)
        return wrapped

    if fn is not None:
        return decorate(fn)
    return decorate


class ToolRegistry:
    """Named tools the runner can execute and the model can see."""

    def __init__(self, functions: Iterable[Callable[..., Any]] | None = None) -> None:
        self._tools: dict[str, ToolSpec] = {}
        for fn in functions or ():
            self.add(fn)

    def add(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        description: str | None = None,
    ) -> ToolSpec:
        spec = ToolSpec.from_function(fn, name=name, description=description)
        if spec.name in self._tools:
            raise ValueError(f"tool already registered: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError as exc:
            raise KeyError(f"unknown tool: {name}") from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._tools)

    def schemas(self) -> tuple[dict[str, Any], ...]:
        return tuple(spec.schema for spec in self._tools.values())

    def execute(self, call: ToolCall) -> str:
        spec = self.get(call.name)
        arguments = _bound_arguments(spec, call.arguments)
        result = spec.handler(**arguments)
        return _stringify(result)

    def __contains__(self, name: str) -> bool:
        return name in self._tools

    def __len__(self) -> int:
        return len(self._tools)


def _bound_arguments(spec: ToolSpec, arguments: Mapping[str, Any]) -> dict[str, Any]:
    properties = spec.parameters.get("properties", {})
    required = spec.parameters.get("required", [])
    extra = sorted(set(arguments) - set(properties))
    if extra:
        raise TypeError(f"{spec.name} got unexpected arguments: {extra}")
    missing = [key for key in required if key not in arguments]
    if missing:
        raise TypeError(f"{spec.name} missing required arguments: {missing}")
    return dict(arguments)


def _validate_name(name: str) -> None:
    if not name.isidentifier() or name.startswith("_"):
        raise ValueError(f"invalid tool name: {name!r}")


def _stringify(result: Any) -> str:
    if result is None:
        return ""
    if isinstance(result, str):
        return result
    return json.dumps(result)
