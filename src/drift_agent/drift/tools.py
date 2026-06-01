"""Tool layer for Drift runs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from drift_agent.memory import MemoryManager
from drift_agent.permissions import PermissionPolicy
from drift_agent.tools import create_default_tool_registry
from drift_agent.tools.base import ToolCallResult, ToolSpec, parse_arguments


class DriftToolSet:
    def __init__(
        self,
        *,
        workdir: str | Path | None = None,
        drift_dir: str | Path = "drift",
        permission_mode: str = "deny",
        memory_manager: MemoryManager | None = None,
        enable_web_tools: bool = True,
    ) -> None:
        self.workdir = Path(workdir or Path.cwd()).resolve()
        self.drift_dir = (self.workdir / drift_dir).resolve()
        self.permission_policy = PermissionPolicy(
            self.workdir,
            mode=permission_mode,
        )
        self.registry = create_default_tool_registry(
            self.workdir,
            permission_policy=self.permission_policy,
            enable_web_tools=enable_web_tools,
            memory_manager=memory_manager,
        )
        self.memory_manager = memory_manager
        self.message_sent = False
        self.message = ""
        self.finished = False
        self.finish_payload: dict[str, Any] | None = None

    def as_openai_tools(self) -> list[dict[str, Any]]:
        specs = [spec.as_openai_tool() for spec in self.registry.specs]
        specs.extend(spec.as_openai_tool() for spec in self._drift_specs())
        return specs

    def dispatch(
        self,
        name: str,
        raw_arguments: str | dict[str, Any] | None,
    ) -> ToolCallResult:
        canonical_id = self.registry.resolve_name(name)
        if canonical_id == "drift.message_push" or name in {"message_push", "drift__message_push"}:
            return self._message_push(raw_arguments)
        if canonical_id == "drift.finish_drift" or name in {"finish_drift", "drift__finish_drift"}:
            return self._finish_drift(raw_arguments)
        if canonical_id == "drift.fetch_messages" or name in {"fetch_messages", "drift__fetch_messages"}:
            return self._fetch_messages(raw_arguments)
        if canonical_id == "drift.search_messages" or name in {"search_messages", "drift__search_messages"}:
            return self._search_messages(raw_arguments)
        if canonical_id == "drift.mount_server" or name in {"mount_server", "drift__mount_server"}:
            return ToolCallResult("drift.mount_server", "MCP mount_server is reserved for a later phase.", True)

        canonical_id = self.registry.resolve_name(name)
        if self.message_sent and canonical_id not in {
            "workspace.write_file",
            "workspace.edit_file",
        }:
            return ToolCallResult(
                canonical_id,
                "Error: after message_push only write_file, edit_file, or finish_drift may be called.",
                True,
            )
        if canonical_id in {"workspace.write_file", "workspace.edit_file"}:
            try:
                arguments = parse_arguments(raw_arguments)
            except ValueError as exc:
                return ToolCallResult(canonical_id, f"Error: {exc}", True)
            path = str(arguments.get("path") or "")
            if not self._path_in_drift_dir(path):
                return ToolCallResult(
                    canonical_id,
                    "Error: Drift writes are restricted to the drift directory.",
                    True,
                )
            return self.registry.dispatch(canonical_id, arguments)
        return self.registry.dispatch(canonical_id, raw_arguments)

    def _message_push(self, raw_arguments: str | dict[str, Any] | None) -> ToolCallResult:
        if self.message_sent:
            return ToolCallResult("drift.message_push", "Error: message_push already used.", True)
        try:
            arguments = parse_arguments(raw_arguments)
        except ValueError as exc:
            return ToolCallResult("drift.message_push", f"Error: {exc}", True)
        message = str(arguments.get("message") or "").strip()
        if not message:
            return ToolCallResult("drift.message_push", "Error: message is required.", True)
        self.message_sent = True
        self.message = message
        return ToolCallResult(
            "drift.message_push",
            json.dumps({"sent": True, "message": message}, ensure_ascii=False),
        )

    def _finish_drift(self, raw_arguments: str | dict[str, Any] | None) -> ToolCallResult:
        try:
            arguments = parse_arguments(raw_arguments)
        except ValueError as exc:
            return ToolCallResult("drift.finish_drift", f"Error: {exc}", True)
        message_result = str(arguments.get("message_result") or "").strip()
        if message_result not in {"sent", "silent"}:
            return ToolCallResult(
                "drift.finish_drift",
                "Error: message_result must be sent or silent.",
                True,
            )
        expected = "sent" if self.message_sent else "silent"
        if message_result != expected:
            return ToolCallResult(
                "drift.finish_drift",
                f"Error: message_result must be {expected} for this run.",
                True,
            )
        self.finished = True
        self.finish_payload = {
            "message_result": message_result,
            "skill": str(arguments.get("skill") or "").strip(),
            "one_line": str(arguments.get("one_line") or "").strip(),
            "next": str(arguments.get("next") or "").strip(),
        }
        return ToolCallResult(
            "drift.finish_drift",
            json.dumps({"finished": True, **self.finish_payload}, ensure_ascii=False),
        )

    def _fetch_messages(self, raw_arguments: str | dict[str, Any] | None) -> ToolCallResult:
        if self.memory_manager is None or self.memory_manager.sqlite is None:
            return ToolCallResult("drift.fetch_messages", "[]")
        try:
            arguments = parse_arguments(raw_arguments)
        except ValueError as exc:
            return ToolCallResult("drift.fetch_messages", f"Error: {exc}", True)
        limit = bounded_int(arguments.get("limit"), 8)
        turns = self.memory_manager.sqlite.load_recent_turns(
            self.memory_manager.session_id,
            recent_limit=limit,
        )
        return ToolCallResult(
            "drift.fetch_messages",
            json.dumps(
                [
                    {"user": user_prompt, "assistant": assistant_answer}
                    for user_prompt, assistant_answer in turns
                ],
                ensure_ascii=False,
            ),
        )

    def _search_messages(self, raw_arguments: str | dict[str, Any] | None) -> ToolCallResult:
        result = self._fetch_messages(raw_arguments)
        if result.error:
            return result
        try:
            arguments = parse_arguments(raw_arguments)
            query = str(arguments.get("query") or "").lower()
            rows = json.loads(result.output)
        except (ValueError, json.JSONDecodeError):
            return ToolCallResult("drift.search_messages", "[]")
        if not query:
            return ToolCallResult("drift.search_messages", result.output)
        filtered = [
            row
            for row in rows
            if query in str(row.get("user", "")).lower()
            or query in str(row.get("assistant", "")).lower()
        ]
        return ToolCallResult(
            "drift.search_messages",
            json.dumps(filtered, ensure_ascii=False),
        )

    def _path_in_drift_dir(self, path: str) -> bool:
        target = (self.workdir / path).resolve()
        return target.is_relative_to(self.drift_dir)

    def _drift_specs(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                canonical_id="drift.message_push",
                provider="drift",
                aliases=("message_push",),
                description="Send one terminal notice to the user for this Drift run.",
                parameters={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            ),
            ToolSpec(
                canonical_id="drift.finish_drift",
                provider="drift",
                aliases=("finish_drift",),
                description="Finish the Drift run and record whether a message was sent.",
                parameters={
                    "type": "object",
                    "properties": {
                        "message_result": {"type": "string", "enum": ["sent", "silent"]},
                        "skill": {"type": "string"},
                        "one_line": {"type": "string"},
                        "next": {"type": "string"},
                    },
                    "required": ["message_result", "one_line"],
                },
            ),
            ToolSpec(
                canonical_id="drift.fetch_messages",
                provider="drift",
                aliases=("fetch_messages",),
                description="Fetch recent local chat turns from memory.",
                parameters={
                    "type": "object",
                    "properties": {"limit": {"type": "integer"}},
                },
            ),
            ToolSpec(
                canonical_id="drift.search_messages",
                provider="drift",
                aliases=("search_messages",),
                description="Search recent local chat turns by keyword.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {"type": "string"},
                        "limit": {"type": "integer"},
                    },
                    "required": ["query"],
                },
            ),
            ToolSpec(
                canonical_id="drift.mount_server",
                provider="drift",
                aliases=("mount_server",),
                description="Reserved MCP mount hook for a future Drift phase.",
                parameters={
                    "type": "object",
                    "properties": {"server": {"type": "string"}},
                    "required": ["server"],
                },
            ),
        ]


def bounded_int(value: object, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(1, min(parsed, 50))
