import pytest

from prometheus import (
    AgentRunner,
    AssistantReply,
    Message,
    Role,
    StopReason,
    ToolCall,
)


class ScriptedModel:
    def __init__(self, replies: list[AssistantReply]) -> None:
        self._replies = replies
        self.seen: list[tuple[Message, ...]] = []

    def complete(self, messages: tuple[Message, ...]) -> AssistantReply:
        self.seen.append(messages)
        return self._replies[len(self.seen) - 1]


class MapExecutor:
    def __init__(self, results: dict[str, str] | None = None) -> None:
        self.results = results or {}
        self.calls: list[ToolCall] = []

    def execute(self, call: ToolCall) -> str:
        self.calls.append(call)
        if call.name not in self.results:
            raise KeyError(call.name)
        return self.results[call.name]


def test_completes_on_first_reply_without_tools() -> None:
    model = ScriptedModel([AssistantReply(content="stolen.")])
    result = AgentRunner(model).run("steal the fire")

    assert result.completed
    assert result.output == "stolen."
    assert result.stop_reason is StopReason.COMPLETED
    assert len(result.turns) == 1
    assert result.messages[0] == Message(role=Role.USER, content="steal the fire")
    assert result.messages[-1].role is Role.ASSISTANT


def test_system_prompt_is_the_first_message() -> None:
    model = ScriptedModel([AssistantReply(content="ok")])
    AgentRunner(model, system_prompt="you are fire").run("go")

    assert model.seen[0][0] == Message(role=Role.SYSTEM, content="you are fire")
    assert model.seen[0][1].role is Role.USER


def test_tool_call_then_final_answer() -> None:
    model = ScriptedModel(
        [
            AssistantReply(
                tool_calls=(ToolCall(id="c1", name="spark", arguments={"n": 1}),)
            ),
            AssistantReply(content="lit."),
        ]
    )
    tools = MapExecutor({"spark": "ember"})
    result = AgentRunner(model, tools=tools).run("ignite")

    assert result.completed
    assert result.output == "lit."
    assert len(result.turns) == 2
    assert result.turns[0].tool_results[0].content == "ember"
    assert tools.calls[0].arguments == {"n": 1}

    second_prompt = model.seen[1]
    assert second_prompt[-1] == Message(
        role=Role.TOOL, content="ember", tool_call_id="c1"
    )


def test_multiple_tool_calls_in_one_turn() -> None:
    model = ScriptedModel(
        [
            AssistantReply(
                tool_calls=(
                    ToolCall(id="a", name="left"),
                    ToolCall(id="b", name="right"),
                )
            ),
            AssistantReply(content="done"),
        ]
    )
    tools = MapExecutor({"left": "L", "right": "R"})
    result = AgentRunner(model, tools=tools).run("split")

    assert [msg.content for msg in result.turns[0].tool_results] == ["L", "R"]
    assert [call.name for call in tools.calls] == ["left", "right"]


def test_stops_at_max_turns_when_model_keeps_calling_tools() -> None:
    replies = [
        AssistantReply(content=f"turn-{i}", tool_calls=(ToolCall(id=str(i), name="loop"),))
        for i in range(3)
    ]
    model = ScriptedModel(replies)
    result = AgentRunner(model, tools=MapExecutor({"loop": "again"}), max_turns=3).run(
        "never stop"
    )

    assert not result.completed
    assert result.stop_reason is StopReason.MAX_TURNS
    assert result.output == "turn-2"
    assert len(result.turns) == 3
    assert len(model.seen) == 3


def test_missing_executor_feeds_error_back_to_the_model() -> None:
    model = ScriptedModel(
        [
            AssistantReply(tool_calls=(ToolCall(id="c1", name="missing"),)),
            AssistantReply(content="gave up"),
        ]
    )
    result = AgentRunner(model).run("use a tool")

    assert result.completed
    tool_message = result.turns[0].tool_results[0]
    assert "missing" in tool_message.content
    assert tool_message.content.startswith("error:")


def test_tool_exceptions_become_tool_messages() -> None:
    model = ScriptedModel(
        [
            AssistantReply(tool_calls=(ToolCall(id="c1", name="boom"),)),
            AssistantReply(content="caught"),
        ]
    )
    result = AgentRunner(model, tools=MapExecutor()).run("explode")

    assert result.turns[0].tool_results[0].content.startswith("error: KeyError")
    assert result.output == "caught"


def test_max_turns_must_be_at_least_one() -> None:
    with pytest.raises(ValueError, match="max_turns"):
        AgentRunner(ScriptedModel([]), max_turns=0)


def test_tool_message_requires_call_id() -> None:
    with pytest.raises(ValueError, match="tool_call_id"):
        Message(role=Role.TOOL, content="nope")
