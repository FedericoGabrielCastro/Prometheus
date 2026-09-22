"""Model boundary for the runner.

The runner talks to a model through this protocol. Concrete providers
live in `prometheus.providers` (`EchoModel`, `OpenAIModel`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Protocol

from prometheus.types import AssistantReply, Message


class Model(Protocol):
    def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> AssistantReply:
        """Return the next assistant message for this conversation.

        `tools` is the JSON schemas from the registry, or None when no
        tools are configured.
        """
