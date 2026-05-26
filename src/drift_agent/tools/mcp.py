"""Reserved MCP tool provider interface."""

from __future__ import annotations

from typing import Any

from drift_agent.tools.base import ToolCallResult, ToolProvider, ToolSpec


class MCPToolProvider(ToolProvider):
    namespace = "mcp"

    def __init__(self, server_name: str = "default", enabled: bool = False) -> None:
        self.server_name = server_name
        self.enabled = enabled

    def as_provider_namespace(self) -> str:
        return f"mcp.{self.server_name}"

    def list_tools(self) -> list[ToolSpec]:
        return []

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult(canonical_id, f"Tool disabled: {canonical_id}", True)
