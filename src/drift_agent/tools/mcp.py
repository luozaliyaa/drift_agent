"""MCP tool provider interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from drift_agent.mcp import MCPClientError, MCPServerConfig, SyncMCPClient, load_mcp_config
from drift_agent.tools.base import ToolCallResult, ToolProvider, ToolSpec


class MCPToolProvider(ToolProvider):
    namespace = "mcp"

    def __init__(
        self,
        server_name: str = "default",
        enabled: bool = False,
        config_path: str | Path = "mcp_servers.json",
        client_factory: Any | None = None,
    ) -> None:
        self.server_name = server_name
        self.enabled = enabled
        self.config_path = Path(config_path)
        self.client_factory = client_factory or SyncMCPClient
        self._server_config: MCPServerConfig | None = None
        self._tool_names: dict[str, str] = {}

    def as_provider_namespace(self) -> str:
        return f"mcp.{self.server_name}"

    def list_tools(self) -> list[ToolSpec]:
        if not self.enabled:
            return []
        server = self._load_server_config()
        if server is None:
            return []
        try:
            with self.client_factory(server) as client:
                tools = client.list_tools()
        except (MCPClientError, OSError):
            return []
        specs: list[ToolSpec] = []
        for tool in tools:
            spec = self._spec_from_mcp_tool(tool)
            if spec is not None:
                specs.append(spec)
        return specs

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        if not self.enabled:
            return ToolCallResult(canonical_id, f"Tool disabled: {canonical_id}", True)
        server = self._load_server_config()
        if server is None:
            return ToolCallResult(
                canonical_id,
                f"Tool disabled: MCP server not configured: {self.server_name}",
                True,
            )
        tool_name = self._tool_names.get(canonical_id) or tool_name_from_canonical(
            canonical_id,
            self.server_name,
        )
        try:
            with self.client_factory(server) as client:
                result = client.call_tool(tool_name, arguments)
        except (MCPClientError, OSError) as exc:
            return ToolCallResult(canonical_id, f"Error: {exc}", True)
        return ToolCallResult(canonical_id, json.dumps(result, ensure_ascii=False))

    def _load_server_config(self) -> MCPServerConfig | None:
        if self._server_config is not None:
            return self._server_config
        config = load_mcp_config(self.config_path)
        self._server_config = config.get(self.server_name)
        return self._server_config

    def _spec_from_mcp_tool(self, tool: object) -> ToolSpec | None:
        if not isinstance(tool, dict):
            return None
        name = str(tool.get("name") or "").strip()
        if not name:
            return None
        canonical_id = f"mcp.{self.server_name}.{name}"
        self._tool_names[canonical_id] = name
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        return ToolSpec(
            canonical_id=canonical_id,
            provider=self.namespace,
            description=str(tool.get("description") or f"MCP tool {name}"),
            parameters=schema,
        )


def tool_name_from_canonical(canonical_id: str, server_name: str) -> str:
    prefix = f"mcp.{server_name}."
    if canonical_id.startswith(prefix):
        return canonical_id.removeprefix(prefix)
    return canonical_id.rsplit(".", 1)[-1]
