"""Shared types for the agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class StopReason(StrEnum):
    """Why the runner left the loop."""

    COMPLETED = "completed"
    MAX_TURNS = "max_turns"


@dataclass(frozen=True, slots=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Message:
    role: Role
    content: str = ""
    tool_call_id: str | None = None
    tool_calls: tuple[ToolCall, ...] = ()

    def __post_init__(self) -> None:
        if self.role is Role.TOOL and not self.tool_call_id:
            raise ValueError("tool messages require tool_call_id")
        if self.tool_calls and self.role is not Role.ASSISTANT:
            raise ValueError("only assistant messages may include tool_calls")


@dataclass(frozen=True, slots=True)
class AssistantReply:
    """What a model returns for one turn."""

    content: str = ""
    tool_calls: tuple[ToolCall, ...] = ()


@dataclass(frozen=True, slots=True)
class Turn:
    index: int
    assistant: Message
    tool_results: tuple[Message, ...] = ()


@dataclass(frozen=True, slots=True)
class RunResult:
    output: str
    stop_reason: StopReason
    turns: tuple[Turn, ...]
    messages: tuple[Message, ...]

    @property
    def completed(self) -> bool:
        return self.stop_reason is StopReason.COMPLETED
