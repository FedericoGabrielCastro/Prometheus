from prometheus import AssistantReply, Message, ToolCall


class ScriptedModel:
    def __init__(self, replies: list[AssistantReply]) -> None:
        self._replies = replies
        self.seen: list[tuple[Message, ...]] = []
        self.tools_seen: list[tuple[dict, ...] | None] = []

    def complete(
        self,
        messages: tuple[Message, ...],
        *,
        tools: tuple[dict, ...] | None = None,
    ) -> AssistantReply:
        self.seen.append(messages)
        self.tools_seen.append(tools)
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
