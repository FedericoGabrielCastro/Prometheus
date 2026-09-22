from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread

import pytest

from prometheus import ToolCall, Workspace, builtin_tools


def test_read_write_list_roundtrip(tmp_path) -> None:
    tools = builtin_tools(tmp_path, shell=False, http=False)
    tools.execute(ToolCall(id="1", name="write_file", arguments={"path": "a/b.txt", "content": "fire"}))

    listed = tools.execute(ToolCall(id="2", name="list_dir", arguments={"path": "."}))
    assert "a/" in listed.splitlines()

    nested = tools.execute(ToolCall(id="3", name="list_dir", arguments={"path": "a"}))
    assert nested == "b.txt"

    text = tools.execute(ToolCall(id="4", name="read_file", arguments={"path": "a/b.txt"}))
    assert text == "fire"


def test_path_escape_is_rejected(tmp_path) -> None:
    tools = builtin_tools(tmp_path, shell=False, http=False)
    with pytest.raises(ValueError, match="escapes workspace"):
        tools.execute(ToolCall(id="1", name="read_file", arguments={"path": "../secret"}))


def test_symlink_escape_is_rejected(tmp_path) -> None:
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("nope", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(outside)

    tools = builtin_tools(tmp_path, shell=False, http=False)
    with pytest.raises(ValueError, match="escapes workspace"):
        tools.execute(ToolCall(id="1", name="read_file", arguments={"path": "link.txt"}))


def test_empty_dir_and_not_a_directory(tmp_path) -> None:
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    tools = builtin_tools(tmp_path, shell=False, http=False)

    assert tools.execute(ToolCall(id="1", name="list_dir", arguments={"path": "."})) == "file.txt"
    empty = tmp_path / "empty"
    empty.mkdir()
    assert tools.execute(ToolCall(id="2", name="list_dir", arguments={"path": "empty"})) == "(empty)"
    with pytest.raises(NotADirectoryError):
        tools.execute(ToolCall(id="3", name="list_dir", arguments={"path": "file.txt"}))


def test_run_command_stdout_and_exit_code(tmp_path) -> None:
    tools = builtin_tools(tmp_path, filesystem=False, http=False)
    ok = tools.execute(ToolCall(id="1", name="run_command", arguments={"command": "echo stolen"}))
    assert "exit_code: 0" in ok
    assert "stolen" in ok

    bad = tools.execute(ToolCall(id="2", name="run_command", arguments={"command": "exit 7"}))
    assert "exit_code: 7" in bad


def test_run_command_cwd_is_workspace(tmp_path) -> None:
    (tmp_path / "marker.txt").write_text("here", encoding="utf-8")
    tools = builtin_tools(tmp_path, filesystem=False, http=False)
    result = tools.execute(ToolCall(id="1", name="run_command", arguments={"command": "cat marker.txt"}))
    assert "here" in result


def test_run_command_rejects_empty(tmp_path) -> None:
    tools = builtin_tools(tmp_path, filesystem=False, http=False)
    with pytest.raises(ValueError, match="must not be empty"):
        tools.execute(ToolCall(id="1", name="run_command", arguments={"command": "   "}))


def test_http_get_local_server(tmp_path) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = b"pong"
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = server.server_address[1]
        tools = builtin_tools(tmp_path, filesystem=False, shell=False)
        result = tools.execute(
            ToolCall(id="1", name="http_get", arguments={"url": f"http://127.0.0.1:{port}/"})
        )
        assert "status: 200" in result
        assert "pong" in result
    finally:
        server.shutdown()
        server.server_close()


def test_http_get_rejects_non_http(tmp_path) -> None:
    tools = builtin_tools(tmp_path, filesystem=False, shell=False)
    with pytest.raises(ValueError, match="only http"):
        tools.execute(ToolCall(id="1", name="http_get", arguments={"url": "file:///etc/passwd"}))


def test_output_is_clipped(tmp_path) -> None:
    tools = Workspace(tmp_path, max_output=8).registry(shell=False, http=False)
    tools.execute(ToolCall(id="1", name="write_file", arguments={"path": "big.txt", "content": "abcdefghijklmnop"}))
    text = tools.execute(ToolCall(id="2", name="read_file", arguments={"path": "big.txt"}))
    assert text.startswith("abcdefgh")
    assert "truncated" in text


def test_builtin_groups_and_schemas(tmp_path) -> None:
    tools = builtin_tools(tmp_path)
    assert tools.names() == (
        "read_file",
        "write_file",
        "list_dir",
        "run_command",
        "http_get",
    )
    http_only = builtin_tools(tmp_path, filesystem=False, shell=False)
    assert http_only.names() == ("http_get",)
    with pytest.raises(ValueError, match="at least one"):
        builtin_tools(tmp_path, filesystem=False, shell=False, http=False)


def test_missing_workspace_root(tmp_path) -> None:
    with pytest.raises(NotADirectoryError):
        Workspace(tmp_path / "nope")
