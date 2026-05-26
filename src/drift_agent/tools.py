"""Workspace tools exposed to the model."""

from __future__ import annotations

import glob as glob_module
import json
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_TOOL_OUTPUT_CHARS = 50000


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., str]

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class WorkspaceTools:
    """Dispatch map for model-callable workspace tools."""

    def __init__(self, workdir: str | Path | None = None) -> None:
        self.workdir = Path(workdir or Path.cwd()).resolve()
        self._specs = {
            "bash": ToolSpec(
                name="bash",
                description="Run a shell command in the workspace.",
                parameters={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
                handler=self.run_bash,
            ),
            "read_file": ToolSpec(
                name="read_file",
                description="Read a text file from the workspace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["path"],
                },
                handler=self.run_read_file,
            ),
            "write_file": ToolSpec(
                name="write_file",
                description="Write text content to a file inside the workspace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
                handler=self.run_write_file,
            ),
            "edit_file": ToolSpec(
                name="edit_file",
                description="Replace exact text once in a workspace file.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old_text": {"type": "string"},
                        "new_text": {"type": "string"},
                    },
                    "required": ["path", "old_text", "new_text"],
                },
                handler=self.run_edit_file,
            ),
            "glob": ToolSpec(
                name="glob",
                description="Find workspace files matching a glob pattern.",
                parameters={
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                    "required": ["pattern"],
                },
                handler=self.run_glob,
            ),
        }

    @property
    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def as_openai_tools(self) -> list[dict[str, Any]]:
        return [spec.as_openai_tool() for spec in self.specs]

    def dispatch_json(self, name: str, raw_arguments: str | dict[str, Any] | None) -> str:
        spec = self._specs.get(name)
        if spec is None:
            return f"Error: Unknown tool: {name}"

        try:
            arguments = _parse_arguments(raw_arguments)
            output = spec.handler(**arguments)
        except TypeError as exc:
            output = f"Error: Invalid arguments for {name}: {exc}"
        except Exception as exc:
            output = f"Error: {exc}"
        return _truncate(output)

    def safe_path(self, path: str) -> Path:
        candidate = (self.workdir / path).resolve()
        if not candidate.is_relative_to(self.workdir):
            raise ValueError(f"Path escapes workspace: {path}")
        return candidate

    def run_bash(self, command: str) -> str:
        lowered = command.lower()
        dangerous = [
            "rm -rf",
            "sudo",
            "shutdown",
            "reboot",
            "restart-computer",
            "format ",
            "del /",
            "rd /s",
            "rmdir /s",
            "remove-item",
            "> /dev/",
        ]
        if any(fragment in lowered for fragment in dangerous):
            return "Error: Dangerous command blocked"

        try:
            result = subprocess.run(
                command,
                shell=True,
                cwd=self.workdir,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except subprocess.TimeoutExpired:
            return "Error: Timeout (120s)"
        except (FileNotFoundError, OSError) as exc:
            return f"Error: {exc}"

        output = (result.stdout + result.stderr).strip()
        return output if output else "(no output)"

    def run_read_file(self, path: str, limit: int | None = None) -> str:
        lines = self.safe_path(path).read_text(encoding="utf-8").splitlines()
        if limit is not None and limit > 0 and limit < len(lines):
            lines = lines[:limit] + [f"... ({len(lines) - limit} more lines)"]
        return "\n".join(lines)

    def run_write_file(self, path: str, content: str) -> str:
        target = self.safe_path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return f"Wrote {len(content)} bytes to {path}"

    def run_edit_file(self, path: str, old_text: str, new_text: str) -> str:
        target = self.safe_path(path)
        text = target.read_text(encoding="utf-8")
        if old_text not in text:
            return f"Error: Text not found in {path}"
        target.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"

    def run_glob(self, pattern: str) -> str:
        matches: list[str] = []
        for match in glob_module.glob(pattern, root_dir=self.workdir, recursive=True):
            if (self.workdir / match).resolve().is_relative_to(self.workdir):
                matches.append(str(match))
        return "\n".join(matches) if matches else "(no matches)"


def _parse_arguments(raw_arguments: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw_arguments is None:
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    parsed = json.loads(raw_arguments or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must decode to an object")
    return parsed


def _truncate(output: str) -> str:
    if len(output) <= MAX_TOOL_OUTPUT_CHARS:
        return output
    return output[:MAX_TOOL_OUTPUT_CHARS] + "\n... (truncated)"
