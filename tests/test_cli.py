import io
import sys

import pytest

from prometheus.cli import main
from prometheus.providers import EchoModel, OpenAIModel
from prometheus.types import AssistantReply, Message, Role, ToolCall


NO_TOOLS = ["--no-filesystem", "--no-shell", "--no-http"]


def test_echo_run_prints_prompt(capsys, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    code = main(["run", "--model", "echo", *NO_TOOLS, "steal", "the", "fire"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "steal the fire"


def test_echo_verbose_and_stdin(capsys, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(sys, "stdin", io.StringIO("  from stdin  \n"))
    code = main(["run", "--model", "echo", "-v", *NO_TOOLS, "-"])
    captured = capsys.readouterr()
    assert code == 0
    assert captured.out.strip() == "from stdin"
    assert "completed in 1 turn" in captured.err


def test_missing_model_and_empty_prompt(capsys, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(["run", *NO_TOOLS, "hello"]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err
    assert main(["run", "--model", "echo", *NO_TOOLS, "   "]) == 1
    assert "prompt must not be empty" in capsys.readouterr().err


def test_openai_flag_without_key(capsys, monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert main(["run", "--model", "openai", *NO_TOOLS, "hi"]) == 1
    assert "OPENAI_API_KEY" in capsys.readouterr().err


def test_help_without_command(capsys) -> None:
    assert main([]) == 2
    assert "prometheus" in capsys.readouterr().err.lower()


def test_bad_root(capsys, tmp_path) -> None:
    missing = tmp_path / "nope"
    code = main(["run", "--model", "echo", "--root", str(missing), "hi"])
    assert code == 1
    assert "not a directory" in capsys.readouterr().err


def test_echo_model_uses_last_user_message() -> None:
    reply = EchoModel().complete(
        [
            Message(role=Role.SYSTEM, content="sys"),
            Message(role=Role.USER, content="one"),
            Message(role=Role.USER, content="two"),
        ]
    )
    assert reply == AssistantReply(content="two")


def test_openai_model_maps_tool_calls() -> None:
    captured: dict = {}

    def transport(url, payload, headers, timeout):
        captured["url"] = url
        captured["payload"] = payload
        captured["headers"] = headers
        return {
            "choices": [
                {
                    "message": {
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "c1",
                                "function": {
                                    "name": "list_dir",
                                    "arguments": '{"path": "."}',
                                },
                            }
                        ],
                    }
                }
            ]
        }

    model = OpenAIModel("sk-test", model="gpt-4o-mini", transport=transport)
    reply = model.complete(
        [Message(role=Role.USER, content="files?")],
        tools=[{"name": "list_dir", "description": "List", "parameters": {}}],
    )
    assert reply.content == ""
    assert reply.tool_calls == (ToolCall(id="c1", name="list_dir", arguments={"path": "."}),)
    assert captured["url"].endswith("/chat/completions")
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["payload"]["tools"][0]["function"]["name"] == "list_dir"


def test_openai_model_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="api_key"):
        OpenAIModel("  ")


def test_openai_invalid_arguments_become_empty_dict() -> None:
    def transport(url, payload, headers, timeout):
        return {
            "choices": [
                {
                    "message": {
                        "content": "ok",
                        "tool_calls": [
                            {"id": "c1", "function": {"name": "spark", "arguments": "nope"}}
                        ],
                    }
                }
            ]
        }

    reply = OpenAIModel("sk-test", transport=transport).complete(
        [Message(role=Role.USER, content="x")]
    )
    assert reply.tool_calls[0].arguments == {}
    assert reply.content == "ok"
