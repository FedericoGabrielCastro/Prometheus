"""Agent runner: one loop, turn state, stop conditions.

The runner owns the loop. Tools never talk to the model. The model never
executes tools. That boundary is the whole design.
"""

from __future__ import annotations

from typing import Protocol

from prometheus.model import Model
from prometheus.types import (
    AssistantReply,
    Message,
    Role,
    RunResult,
    StopReason,
    ToolCall,
    Turn,
)


class ToolExecutor(Protocol):
    """Dispatch a tool call. `ToolRegistry` is the usual implementation."""

    def execute(self, call: ToolCall) -> str:
        """Run one tool call and return a string result for the model."""


class AgentRunner:
    def __init__(
        self,
        model: Model,
        *,
        tools: ToolExecutor | None = None,
        max_turns: int = 16,
        system_prompt: str | None = None,
    ) -> None:
        if max_turns < 1:
            raise ValueError("max_turns must be >= 1")
        self._model = model
        self._tools = tools
        self._max_turns = max_turns
        self._system_prompt = system_prompt

    def run(self, prompt: str) -> RunResult:
        messages = self._seed_messages(prompt)
        turns: list[Turn] = []

        schemas = self._tool_schemas()
        for index in range(self._max_turns):
            reply = self._model.complete(tuple(messages), tools=schemas)
            assistant = _assistant_message(reply)
            messages.append(assistant)

            if not reply.tool_calls:
                turns.append(Turn(index=index, assistant=assistant))
                return RunResult(
                    output=reply.content,
                    stop_reason=StopReason.COMPLETED,
                    turns=tuple(turns),
                    messages=tuple(messages),
                )

            tool_results = tuple(self._run_tools(reply.tool_calls))
            messages.extend(tool_results)
            turns.append(
                Turn(index=index, assistant=assistant, tool_results=tool_results)
            )

        last = turns[-1].assistant.content if turns else ""
        return RunResult(
            output=last,
            stop_reason=StopReason.MAX_TURNS,
            turns=tuple(turns),
            messages=tuple(messages),
        )

    def _seed_messages(self, prompt: str) -> list[Message]:
        messages: list[Message] = []
        if self._system_prompt:
            messages.append(Message(role=Role.SYSTEM, content=self._system_prompt))
        messages.append(Message(role=Role.USER, content=prompt))
        return messages

    def _run_tools(self, calls: tuple[ToolCall, ...]) -> list[Message]:
        results: list[Message] = []
        for call in calls:
            results.append(
                Message(
                    role=Role.TOOL,
                    content=self._execute(call),
                    tool_call_id=call.id,
                )
            )
        return results

    def _execute(self, call: ToolCall) -> str:
        if self._tools is None:
            return f"error: tool {call.name!r} is not available"
        try:
            return self._tools.execute(call)
        except Exception as exc:
            return f"error: {type(exc).__name__}: {exc}"

    def _tool_schemas(self) -> tuple[dict, ...] | None:
        if self._tools is None:
            return None
        schemas = getattr(self._tools, "schemas", None)
        if schemas is None:
            return None
        return tuple(schemas() if callable(schemas) else schemas)


def _assistant_message(reply: AssistantReply) -> Message:
    return Message(
        role=Role.ASSISTANT,
        content=reply.content,
        tool_calls=reply.tool_calls,
    )
