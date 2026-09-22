"""First-party tools: filesystem, shell, HTTP.

All filesystem and shell work is rooted at a workspace directory. Paths
that resolve outside that root are rejected. HTTP is limited to http(s).
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Annotated
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from prometheus.tools import ToolRegistry

_DEFAULT_COMMAND_TIMEOUT = 30.0
_DEFAULT_HTTP_TIMEOUT = 15.0
_DEFAULT_MAX_OUTPUT = 32_000


class Workspace:
    """A rooted workspace the built-in tools are allowed to touch."""

    def __init__(
        self,
        root: str | Path,
        *,
        command_timeout: float = _DEFAULT_COMMAND_TIMEOUT,
        http_timeout: float = _DEFAULT_HTTP_TIMEOUT,
        max_output: int = _DEFAULT_MAX_OUTPUT,
    ) -> None:
        self.root = Path(root).expanduser().resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(f"workspace root is not a directory: {self.root}")
        if command_timeout <= 0:
            raise ValueError("command_timeout must be > 0")
        if http_timeout <= 0:
            raise ValueError("http_timeout must be > 0")
        if max_output < 1:
            raise ValueError("max_output must be >= 1")
        self._command_timeout = command_timeout
        self._http_timeout = http_timeout
        self._max_output = max_output

    def resolve(self, path: str) -> Path:
        """Resolve a user path against the workspace root. Reject escapes."""
        target = (self.root / path).resolve()
        if not target.is_relative_to(self.root):
            raise ValueError(f"path escapes workspace: {path}")
        return target

    def read_file(
        self,
        path: Annotated[str, "Path relative to the workspace root"],
    ) -> str:
        """Read a UTF-8 text file from the workspace."""
        target = self.resolve(path)
        text = target.read_text(encoding="utf-8")
        return _clip(text, self._max_output)

    def write_file(
        self,
        path: Annotated[str, "Path relative to the workspace root"],
        content: Annotated[str, "UTF-8 text to write"],
    ) -> str:
        """Write a UTF-8 text file in the workspace, creating parent dirs."""
        target = self.resolve(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"wrote {len(content.encode('utf-8'))} bytes to {target.relative_to(self.root)}"

    def list_dir(
        self,
        path: Annotated[str, "Directory relative to the workspace root"] = ".",
    ) -> str:
        """List entries in a workspace directory. Directories end with /."""
        target = self.resolve(path)
        if not target.is_dir():
            raise NotADirectoryError(f"not a directory: {path}")
        names: list[str] = []
        for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            names.append(f"{entry.name}/" if entry.is_dir() else entry.name)
        return "\n".join(names) if names else "(empty)"

    def run_command(
        self,
        command: Annotated[str, "Shell command to run with cwd=workspace root"],
    ) -> str:
        """Run a shell command in the workspace and return stdout, stderr, and exit code."""
        if not command.strip():
            raise ValueError("command must not be empty")
        try:
            completed = subprocess.run(
                command,
                shell=True,
                cwd=self.root,
                capture_output=True,
                text=True,
                timeout=self._command_timeout,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError(
                f"command timed out after {self._command_timeout:.0f}s"
            ) from exc
        stdout = _clip(completed.stdout.rstrip("\n"), self._max_output)
        stderr = _clip(completed.stderr.rstrip("\n"), self._max_output)
        lines = [f"exit_code: {completed.returncode}"]
        if stdout:
            lines.extend(["stdout:", stdout])
        if stderr:
            lines.extend(["stderr:", stderr])
        return "\n".join(lines)

    def http_get(
        self,
        url: Annotated[str, "http or https URL to fetch"],
    ) -> str:
        """Fetch a URL over HTTP(S) and return status plus body."""
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("only http and https URLs are allowed")
        request = Request(url, headers={"User-Agent": "Prometheus/0.1"})
        try:
            with urlopen(request, timeout=self._http_timeout) as response:
                status = getattr(response, "status", 200)
                body = response.read(self._max_output + 1)
                final_url = response.geturl()
        except HTTPError as exc:
            status = exc.code
            body = exc.read(self._max_output + 1)
            final_url = exc.geturl() if hasattr(exc, "geturl") else url
        except URLError as exc:
            raise ConnectionError(f"http_get failed: {exc.reason}") from exc
        text = _clip(body.decode("utf-8", errors="replace"), self._max_output)
        return f"status: {status}\nurl: {final_url}\nbody:\n{text}"

    def registry(
        self,
        *,
        filesystem: bool = True,
        shell: bool = True,
        http: bool = True,
    ) -> ToolRegistry:
        functions = []
        if filesystem:
            functions.extend([self.read_file, self.write_file, self.list_dir])
        if shell:
            functions.append(self.run_command)
        if http:
            functions.append(self.http_get)
        if not functions:
            raise ValueError("at least one built-in group must be enabled")
        return ToolRegistry(functions)


def builtin_tools(
    root: str | Path | None = None,
    *,
    filesystem: bool = True,
    shell: bool = True,
    http: bool = True,
    command_timeout: float = _DEFAULT_COMMAND_TIMEOUT,
    http_timeout: float = _DEFAULT_HTTP_TIMEOUT,
    max_output: int = _DEFAULT_MAX_OUTPUT,
) -> ToolRegistry:
    """Return a registry of first-party tools rooted at `root` (cwd by default)."""
    workspace = Workspace(
        root or Path.cwd(),
        command_timeout=command_timeout,
        http_timeout=http_timeout,
        max_output=max_output,
    )
    return workspace.registry(filesystem=filesystem, shell=shell, http=http)


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return f"{text[:limit]}\n... truncated ({len(text)} chars)"
