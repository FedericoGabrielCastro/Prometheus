"""Command-line entry point: `prometheus run`."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from prometheus import AgentRunner, StopReason, __version__, builtin_tools
from prometheus.providers import EchoModel, OpenAIModel
from prometheus.tools import ToolRegistry
from prometheus.types import RunResult

_DEFAULT_MODEL = "gpt-4o-mini"
_DEFAULT_BASE_URL = "https://api.openai.com/v1"


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help(sys.stderr)
        return 2
    try:
        return handler(args)
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="prometheus",
        description="Python agent runner + tools.",
    )
    parser.add_argument("--version", action="version", version=f"prometheus {__version__}")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="Run the agent loop on a prompt.")
    run.add_argument("prompt", nargs="+", help="User prompt. Use - to read stdin.")
    run.add_argument("--root", default=".", help="Workspace root for built-in tools.")
    run.add_argument("--max-turns", type=int, default=16, dest="max_turns")
    run.add_argument("--system", default=None, help="Optional system prompt.")
    run.add_argument(
        "--model",
        choices=("echo", "openai"),
        default=None,
        help="echo is local. openai needs OPENAI_API_KEY (default when the key is set).",
    )
    run.add_argument("--model-name", default=_DEFAULT_MODEL, dest="model_name")
    run.add_argument("--base-url", default=_DEFAULT_BASE_URL, dest="base_url")
    run.add_argument("--api-key", default=None, dest="api_key")
    run.add_argument("--no-filesystem", action="store_true")
    run.add_argument("--no-shell", action="store_true")
    run.add_argument("--no-http", action="store_true")
    run.add_argument("-v", "--verbose", action="store_true")
    run.set_defaults(handler=_cmd_run)
    return parser


def _cmd_run(args: argparse.Namespace) -> int:
    prompt = _read_prompt(args.prompt)
    if prompt is None:
        return 1
    model_name = args.model or (
        "openai" if (args.api_key or os.environ.get("OPENAI_API_KEY")) else None
    )
    if model_name is None:
        print(
            "error: set OPENAI_API_KEY or pass --model echo / --model openai",
            file=sys.stderr,
        )
        return 1
    try:
        model = _build_model(args, model_name)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    tools = _build_tools(args)
    runner = AgentRunner(
        model,
        tools=tools,
        max_turns=args.max_turns,
        system_prompt=args.system,
    )
    result = runner.run(prompt)
    if args.verbose:
        _print_turns(result)
        print(
            f"{result.stop_reason} in {len(result.turns)} turn(s)",
            file=sys.stderr,
        )
    print(result.output)
    return 0 if result.stop_reason is StopReason.COMPLETED else 2


def _read_prompt(parts: list[str]) -> str | None:
    if parts == ["-"]:
        prompt = sys.stdin.read()
    else:
        prompt = " ".join(parts)
    prompt = prompt.strip()
    if not prompt:
        print("error: prompt must not be empty", file=sys.stderr)
        return None
    return prompt


def _build_model(args: argparse.Namespace, name: str) -> EchoModel | OpenAIModel:
    if name == "echo":
        return EchoModel()
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY", "")
    if not api_key.strip():
        raise ValueError("OPENAI_API_KEY is not set")
    return OpenAIModel(
        api_key,
        model=args.model_name,
        base_url=args.base_url,
    )


def _build_tools(args: argparse.Namespace) -> ToolRegistry | None:
    filesystem = not args.no_filesystem
    shell = not args.no_shell
    http = not args.no_http
    if not (filesystem or shell or http):
        return None
    root = Path(args.root)
    return builtin_tools(
        root,
        filesystem=filesystem,
        shell=shell,
        http=http,
    )


def _print_turns(result: RunResult) -> None:
    for turn in result.turns:
        for call in turn.assistant.tool_calls:
            print(f"turn {turn.index + 1}: {call.name}({call.arguments})", file=sys.stderr)
        for message in turn.tool_results:
            preview = message.content.replace("\n", " ")[:120]
            print(f"  -> {preview}", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(main())
