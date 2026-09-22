"""Model boundary for the runner.

The runner talks to a model through this protocol. Concrete providers
(OpenAI, Anthropic, local) land in later PRs.
"""

from __future__ import annotations

from typing import Protocol, Sequence

from prometheus.types import AssistantReply, Message


class Model(Protocol):
    def complete(self, messages: Sequence[Message]) -> AssistantReply:
        """Return the next assistant message for this conversation."""
