"""Workspace-local tools."""

from __future__ import annotations

import glob as glob_module
import subprocess
from pathlib import Path
from typing import Any

from drift_agent.permissions import PermissionPolicy
from drift_agent.tools.base import ToolCallResult, ToolProvider, ToolSpec, truncate_output
from drift_agent.tools.registry import ToolRegistry


class WorkspaceToolProvider(ToolProvider):
    namespace = "workspace"

    def __init__(
        self,
        workdir: str | Path | None = None,
        permission_policy: PermissionPolicy | None = None,
    ) -> None:
        self.workdir = Path(workdir or Path.cwd()).resolve()
        self.permission_policy = permission_policy or PermissionPolicy(self.workdir)
        self._specs = {
            "workspace.bash": ToolSpec(
                canonical_id="workspace.bash",
                provider=self.namespace,
                aliases=("bash",),
                description="Run a shell command in the workspace.",
                parameters={
                    "type": "object",
                    "properties": {"command": {"type": "string"}},
                    "required": ["command"],
                },
                handler=self.run_bash,
            ),
            "workspace.read_file": ToolSpec(
                canonical_id="workspace.read_file",
                provider=self.namespace,
                aliases=("read_file",),
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
            "workspace.write_file": ToolSpec(
                canonical_id="workspace.write_file",
                provider=self.namespace,
                aliases=("write_file",),
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
            "workspace.edit_file": ToolSpec(
                canonical_id="workspace.edit_file",
                provider=self.namespace,
                aliases=("edit_file",),
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
            "workspace.glob": ToolSpec(
                canonical_id="workspace.glob",
                provider=self.namespace,
                aliases=("glob",),
                description="Find workspace files matching a glob pattern.",
                parameters={
                    "type": "object",
                    "properties": {"pattern": {"type": "string"}},
                    "required": ["pattern"],
                },
                handler=self.run_glob,
            ),
        }

    def list_tools(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        spec = self._specs.get(canonical_id)
        if spec is None or spec.handler is None:
            return ToolCallResult(canonical_id, f"Error: Unknown tool: {canonical_id}", True)

        local_name = canonical_id.removeprefix(f"{self.namespace}.")
        decision = self.permission_policy.check(local_name, arguments)
        if decision.action == "deny":
            return ToolCallResult(
                canonical_id,
                f"Permission denied: {decision.reason}",
                True,
            )

        try:
            output = spec.handler(**arguments)
        except TypeError as exc:
            output = f"Error: Invalid arguments for {canonical_id}: {exc}"
            return ToolCallResult(canonical_id, output, True)
        except Exception as exc:
            output = f"Error: {exc}"
            return ToolCallResult(canonical_id, output, True)
        return ToolCallResult(canonical_id, truncate_output(output))

    def safe_path(self, path: str) -> Path:
        candidate = (self.workdir / path).resolve()
        if not candidate.is_relative_to(self.workdir):
            raise ValueError(f"Path escapes workspace: {path}")
        return candidate

    def run_bash(self, command: str) -> str:
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


class WorkspaceTools(ToolRegistry):
    """Compatibility wrapper for the previous workspace-only tool API."""

    def __init__(
        self,
        workdir: str | Path | None = None,
        permission_policy: PermissionPolicy | None = None,
    ) -> None:
        super().__init__()
        self.register_provider(WorkspaceToolProvider(workdir, permission_policy))
