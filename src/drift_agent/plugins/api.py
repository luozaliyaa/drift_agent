"""Public plugin API."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from drift_agent.proactive.types import ProactiveSource
from drift_agent.tools.base import ToolCallResult, ToolSpec


@dataclass
class ToolHookContext:
    tool_name: str
    canonical_id: str
    arguments: dict[str, Any]
    raw_arguments: str | dict[str, Any] | None = None
    user_message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolHookResult:
    decision: str = "allow"
    reason: str = ""
    arguments: dict[str, Any] | None = None
    output: str = ""

    @classmethod
    def allow(cls, arguments: dict[str, Any] | None = None) -> "ToolHookResult":
        return cls(decision="allow", arguments=arguments)

    @classmethod
    def deny(cls, reason: str) -> "ToolHookResult":
        return cls(decision="deny", reason=reason, output=f"Error: {reason}")

    @classmethod
    def replace(cls, output: str) -> "ToolHookResult":
        return cls(decision="replace", output=output)


class Plugin:
    """Base class for local plugins."""

    name = ""
    enabled = True

    def initialize(self, root: Path) -> None:
        """Called after discovery. Override to load local plugin state."""

    def prompt_sections(self) -> list[str]:
        return []

    def tools(self) -> list[ToolSpec]:
        return []

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult(canonical_id, f"Error: Unknown plugin tool: {canonical_id}", True)

    def before_tool_call(self, context: ToolHookContext) -> ToolHookResult | dict[str, Any] | None:
        return None

    def after_tool_call(
        self,
        context: ToolHookContext,
        result: ToolCallResult,
    ) -> ToolCallResult | None:
        return None

    def after_turn(self, context: object) -> None:
        """Called after a turn is recorded."""

    def proactive_sources(self) -> list[ProactiveSource | dict[str, Any]]:
        return []
