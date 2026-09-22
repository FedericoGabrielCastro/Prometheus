"""Concrete models the CLI can plug into the runner."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from prometheus.types import AssistantReply, Message, Role, ToolCall

Transport = Callable[[str, dict[str, Any], dict[str, str], float], dict[str, Any]]

_OPENAI_DEFAULT_URL = "https://api.openai.com/v1"
_OPENAI_DEFAULT_MODEL = "gpt-4o-mini"


class EchoModel:
    """Return the last user message. Useful for tests and dry wiring."""

    def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> AssistantReply:
        for message in reversed(messages):
            if message.role is Role.USER:
                return AssistantReply(content=message.content)
        return AssistantReply(content="")


class OpenAIModel:
    """OpenAI-compatible chat completions (including local servers)."""

    def __init__(
        self,
        api_key: str,
        *,
        model: str = _OPENAI_DEFAULT_MODEL,
        base_url: str = _OPENAI_DEFAULT_URL,
        timeout: float = 60.0,
        transport: Transport | None = None,
    ) -> None:
        if not api_key.strip():
            raise ValueError("api_key must not be empty")
        if timeout <= 0:
            raise ValueError("timeout must be > 0")
        self._api_key = api_key
        self._model = model
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._transport = transport or _http_post

    def complete(
        self,
        messages: Sequence[Message],
        *,
        tools: Sequence[dict[str, Any]] | None = None,
    ) -> AssistantReply:
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [_openai_message(message) for message in messages],
        }
        if tools:
            payload["tools"] = [
                {"type": "function", "function": schema} for schema in tools
            ]
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "Prometheus/0.1",
        }
        body = self._transport(url, payload, headers, self._timeout)
        return _reply_from_openai(body)


def _http_post(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> dict[str, Any]:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ConnectionError(f"openai HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ConnectionError(f"openai request failed: {exc.reason}") from exc
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConnectionError("openai returned invalid JSON") from exc


def _openai_message(message: Message) -> dict[str, Any]:
    payload: dict[str, Any] = {"role": message.role.value, "content": message.content}
    if message.role is Role.TOOL:
        payload["tool_call_id"] = message.tool_call_id
    if message.tool_calls:
        payload["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments),
                },
            }
            for call in message.tool_calls
        ]
    return payload


def _reply_from_openai(body: dict[str, Any]) -> AssistantReply:
    try:
        message = body["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as exc:
        raise ConnectionError("openai response missing choices[0].message") from exc
    raw_calls = message.get("tool_calls") or ()
    calls: list[ToolCall] = []
    for item in raw_calls:
        function = item.get("function") or {}
        arguments = function.get("arguments") or "{}"
        if isinstance(arguments, str):
            try:
                parsed = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                parsed = {}
        elif isinstance(arguments, dict):
            parsed = arguments
        else:
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {}
        calls.append(
            ToolCall(
                id=str(item.get("id") or f"call_{len(calls)}"),
                name=str(function.get("name") or ""),
                arguments=parsed,
            )
        )
    return AssistantReply(
        content=message.get("content") or "",
        tool_calls=tuple(call for call in calls if call.name),
    )
