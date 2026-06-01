"""Workspace-local tools."""

from __future__ import annotations

import glob as glob_module
import shutil
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
                always_on=False,
                risk="shell",
                category="workspace",
                search_hint="Run commands, tests, build commands, PowerShell, shell, terminal.",
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
                risk="read-only",
                category="workspace",
                search_hint="Open or inspect a text file.",
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
                always_on=False,
                risk="write",
                category="workspace",
                search_hint="Create or overwrite a file.",
            ),
            "workspace.make_dir": ToolSpec(
                canonical_id="workspace.make_dir",
                provider=self.namespace,
                aliases=("make_dir", "mkdir"),
                description="Create a directory inside the workspace.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=self.run_make_dir,
                always_on=False,
                risk="write",
                category="workspace",
                search_hint="Create a directory or folder.",
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
                always_on=False,
                risk="write",
                category="workspace",
                search_hint="Edit a file by replacing exact text.",
            ),
            "workspace.move_file": ToolSpec(
                canonical_id="workspace.move_file",
                provider=self.namespace,
                aliases=("move_file", "rename_file"),
                description="Move or rename a file or directory inside the workspace.",
                parameters={
                    "type": "object",
                    "properties": {
                        "source": {"type": "string"},
                        "destination": {"type": "string"},
                    },
                    "required": ["source", "destination"],
                },
                handler=self.run_move_file,
                always_on=False,
                risk="write",
                category="workspace",
                search_hint="Move or rename a file or directory.",
            ),
            "workspace.delete_file": ToolSpec(
                canonical_id="workspace.delete_file",
                provider=self.namespace,
                aliases=("delete_file", "remove_file"),
                description="Delete a file inside the workspace.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=self.run_delete_file,
                always_on=False,
                risk="delete",
                category="workspace",
                search_hint="Delete or remove a local file.",
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
                risk="read-only",
                category="workspace",
                search_hint="Find files by glob pattern.",
            ),
            "workspace.list_dir": ToolSpec(
                canonical_id="workspace.list_dir",
                provider=self.namespace,
                aliases=("list_dir", "ls"),
                description="List files and directories inside a workspace directory.",
                parameters={
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                },
                handler=self.run_list_dir,
                risk="read-only",
                category="workspace",
                search_hint="List directory contents.",
            ),
            "workspace.file_info": ToolSpec(
                canonical_id="workspace.file_info",
                provider=self.namespace,
                aliases=("file_info", "stat"),
                description="Return metadata for a workspace file or directory.",
                parameters={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
                handler=self.run_file_info,
                risk="read-only",
                category="workspace",
                search_hint="Inspect file metadata, size, modified time.",
            ),
            "workspace.search_text": ToolSpec(
                canonical_id="workspace.search_text",
                provider=self.namespace,
                aliases=("search_text", "grep"),
                description="Search text in workspace files.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "pattern": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
                handler=self.run_search_text,
                risk="read-only",
                category="workspace",
                search_hint="Search text or grep through workspace files.",
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
                encoding="utf-8",
                errors="replace",
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

    def run_make_dir(self, path: str) -> str:
        target = self.safe_path(path)
        target.mkdir(parents=True, exist_ok=True)
        return f"Created directory {path}"

    def run_edit_file(self, path: str, old_text: str, new_text: str) -> str:
        target = self.safe_path(path)
        text = target.read_text(encoding="utf-8")
        if old_text not in text:
            return f"Error: Text not found in {path}"
        target.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
        return f"Edited {path}"

    def run_move_file(self, source: str, destination: str) -> str:
        source_path = self.safe_path(source)
        destination_path = self.safe_path(destination)
        destination_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source_path), str(destination_path))
        return f"Moved {source} to {destination}"

    def run_delete_file(self, path: str) -> str:
        target = self.safe_path(path)
        if target.is_dir():
            return f"Error: Refusing to delete directory {path}"
        target.unlink()
        return f"Deleted {path}"

    def run_glob(self, pattern: str) -> str:
        matches: list[str] = []
        for match in glob_module.glob(pattern, root_dir=self.workdir, recursive=True):
            if (self.workdir / match).resolve().is_relative_to(self.workdir):
                matches.append(str(match))
        return "\n".join(matches) if matches else "(no matches)"

    def run_list_dir(self, path: str = ".", limit: int | None = None) -> str:
        target = self.safe_path(path)
        entries = sorted(target.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower()))
        if limit is not None and limit > 0:
            visible = entries[:limit]
        else:
            visible = entries
        lines = [format_dir_entry(entry) for entry in visible]
        if limit is not None and limit > 0 and len(entries) > limit:
            lines.append(f"... ({len(entries) - limit} more entries)")
        return "\n".join(lines) if lines else "(empty)"

    def run_file_info(self, path: str) -> str:
        target = self.safe_path(path)
        stat = target.stat()
        kind = "directory" if target.is_dir() else "file"
        relative = target.relative_to(self.workdir)
        return "\n".join(
            [
                f"path: {relative}",
                f"type: {kind}",
                f"size: {stat.st_size}",
                f"modified: {int(stat.st_mtime)}",
            ]
        )

    def run_search_text(
        self,
        query: str,
        pattern: str = "**/*",
        limit: int | None = None,
    ) -> str:
        if not query:
            return "Error: query is required"
        max_matches = limit if limit is not None and limit > 0 else 50
        matches: list[str] = []
        for match in glob_module.glob(pattern, root_dir=self.workdir, recursive=True):
            path = (self.workdir / match).resolve()
            if not path.is_relative_to(self.workdir) or not path.is_file():
                continue
            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue
            except OSError:
                continue
            for line_number, line in enumerate(lines, start=1):
                if query in line:
                    matches.append(f"{match}:{line_number}: {line}")
                    if len(matches) >= max_matches:
                        return "\n".join(matches)
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


def format_dir_entry(path: Path) -> str:
    marker = "/" if path.is_dir() else ""
    size = "-" if path.is_dir() else str(path.stat().st_size)
    return f"{path.name}{marker}\t{size}"
