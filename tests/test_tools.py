from enum import StrEnum
from typing import Annotated, Literal

import pytest

from prometheus import (
    AgentRunner,
    AssistantReply,
    ToolCall,
    ToolRegistry,
    tool,
)
from prometheus.schema import schema_from_function
from tests.fakes import ScriptedModel


class Hue(StrEnum):
    RED = "red"
    BLUE = "blue"


@tool
def spark(n: int = 1) -> str:
    """Make n sparks."""
    return "ember" * n


@tool(name="add_up", description="Sum two integers.")
def add(a: int, b: int) -> int:
    return a + b


def test_schema_from_type_hints_and_docstring() -> None:
    spec = ToolRegistry([spark]).get("spark")

    assert spec.description == "Make n sparks."
    assert spec.parameters == {
        "type": "object",
        "properties": {"n": {"type": "integer", "default": 1}},
        "additionalProperties": False,
    }
    assert spec.schema["name"] == "spark"


def test_annotated_and_optional_and_literal() -> None:
    def paint(
        color: Literal["red", "blue"],
        layers: Annotated[int, "how many coats"],
        gloss: bool | None = None,
        tags: list[str] | None = None,
    ) -> str:
        return color

    schema = schema_from_function(paint)
    assert schema["required"] == ["color", "layers"]
    assert schema["properties"]["color"] == {"enum": ["red", "blue"]}
    assert schema["properties"]["layers"] == {
        "type": "integer",
        "description": "how many coats",
    }
    assert schema["properties"]["gloss"] == {"type": "boolean", "default": None}
    assert schema["properties"]["tags"] == {
        "type": "array",
        "items": {"type": "string"},
        "default": None,
    }


def test_enum_parameters() -> None:
    def pick(hue: Hue) -> str:
        return hue.value

    assert schema_from_function(pick)["properties"]["hue"] == {"enum": ["red", "blue"]}


def test_rejects_varargs() -> None:
    def bad(*args: str) -> str:
        return ""

    with pytest.raises(TypeError, match=r"\*args"):
        schema_from_function(bad)


def test_registry_executes_and_stringifies() -> None:
    registry = ToolRegistry([spark, add])

    assert registry.execute(ToolCall(id="1", name="spark", arguments={"n": 2})) == "emberember"
    assert registry.execute(ToolCall(id="2", name="add_up", arguments={"a": 2, "b": 3})) == "5"
    assert "spark" in registry
    assert registry.names() == ("spark", "add_up")


def test_missing_and_extra_arguments() -> None:
    registry = ToolRegistry([add])

    with pytest.raises(TypeError, match="missing required"):
        registry.execute(ToolCall(id="1", name="add_up", arguments={"a": 1}))
    with pytest.raises(TypeError, match="unexpected arguments"):
        registry.execute(
            ToolCall(id="1", name="add_up", arguments={"a": 1, "b": 2, "z": 9})
        )


def test_unknown_and_duplicate_tools() -> None:
    registry = ToolRegistry([spark])

    with pytest.raises(KeyError, match="unknown tool"):
        registry.get("nope")
    with pytest.raises(ValueError, match="already registered"):
        registry.add(spark)
    with pytest.raises(ValueError, match="invalid tool name"):
        registry.add(spark, name="not-valid")


def test_none_and_json_results() -> None:
    @tool
    def silence() -> None:
        """Return nothing."""
        return None

    @tool
    def payload() -> dict[str, int]:
        """Return a dict."""
        return {"n": 1}

    registry = ToolRegistry([silence, payload])
    assert registry.execute(ToolCall(id="1", name="silence")) == ""
    assert registry.execute(ToolCall(id="2", name="payload")) == '{"n": 1}'


def test_runner_passes_schemas_and_executes_registry() -> None:
    model = ScriptedModel(
        [
            AssistantReply(tool_calls=(ToolCall(id="c1", name="spark", arguments={"n": 2}),)),
            AssistantReply(content="lit."),
        ]
    )
    registry = ToolRegistry([spark])
    result = AgentRunner(model, tools=registry).run("ignite")

    assert result.output == "lit."
    assert result.turns[0].tool_results[0].content == "emberember"
    assert model.tools_seen[0] is not None
    assert model.tools_seen[0][0]["name"] == "spark"
    assert model.tools_seen[1] == model.tools_seen[0]


def test_unsupported_parameter_type() -> None:
    def bad(when: complex) -> str:
        return str(when)

    with pytest.raises(TypeError, match="unsupported"):
        schema_from_function(bad)
