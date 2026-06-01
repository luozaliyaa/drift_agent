"""MCP tool provider interface."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from drift_agent.mcp import MCPClientError, MCPServerConfig, MCPServerRegistry, SyncMCPClient, load_mcp_config
from drift_agent.tools.base import ToolCallResult, ToolProvider, ToolSpec


class MCPToolProvider(ToolProvider):
    namespace = "mcp"

    def __init__(
        self,
        server_name: str = "default",
        enabled: bool = False,
        config_path: str | Path = "mcp_servers.json",
        client_factory: Any | None = None,
        registry: MCPServerRegistry | None = None,
        include_all_servers: bool = False,
    ) -> None:
        self.server_name = server_name
        self.enabled = enabled
        self.config_path = Path(config_path)
        self.client_factory = client_factory or SyncMCPClient
        self.registry = registry
        self.include_all_servers = include_all_servers
        self._server_config: MCPServerConfig | None = None
        self._tool_names: dict[str, tuple[str, str]] = {}

    def as_provider_namespace(self) -> str:
        return f"mcp.{self.server_name}"

    def list_tools(self) -> list[ToolSpec]:
        if not self.enabled:
            return []
        specs: list[ToolSpec] = []
        for server_name in self._server_names():
            try:
                tools = self._list_mcp_tools(server_name)
            except (MCPClientError, OSError):
                continue
            for tool in tools:
                spec = self._spec_from_mcp_tool(tool, server_name)
                if spec is not None:
                    specs.append(spec)
        return specs

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        if not self.enabled:
            return ToolCallResult(canonical_id, f"Tool disabled: {canonical_id}", True)
        server_name, tool_name = self._tool_names.get(canonical_id) or server_and_tool_from_canonical(
            canonical_id
        )
        if self._load_server_config(server_name) is None and self.registry is None:
            return ToolCallResult(
                canonical_id,
                f"Tool disabled: MCP server not configured: {server_name}",
                True,
            )
        try:
            result = self._call_mcp_tool(server_name, tool_name, arguments)
        except (MCPClientError, OSError) as exc:
            return ToolCallResult(canonical_id, f"Error: {exc}", True)
        return ToolCallResult(canonical_id, json.dumps(result, ensure_ascii=False))

    def _server_names(self) -> list[str]:
        if self.include_all_servers and self.registry is not None:
            return self.registry.server_names()
        return [self.server_name]

    def _list_mcp_tools(self, server_name: str) -> list[dict[str, Any]]:
        if self.registry is not None:
            return self.registry.list_tools(server_name)
        server = self._load_server_config(server_name)
        if server is None:
            return []
        with self.client_factory(server) as client:
            return client.list_tools()

    def _call_mcp_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any],
    ) -> dict[str, Any]:
        if self.registry is not None:
            return self.registry.call_tool(server_name, tool_name, arguments)
        server = self._load_server_config(server_name)
        if server is None:
            raise MCPClientError(f"MCP server not configured: {server_name}")
        with self.client_factory(server) as client:
            return client.call_tool(tool_name, arguments)

    def _load_server_config(self, server_name: str | None = None) -> MCPServerConfig | None:
        server_name = server_name or self.server_name
        if server_name == self.server_name and self._server_config is not None:
            return self._server_config
        if self.registry is not None:
            return self.registry.get_config(server_name)
        config = load_mcp_config(self.config_path)
        server = config.get(server_name)
        if server_name == self.server_name:
            self._server_config = server
        return server

    def _spec_from_mcp_tool(self, tool: object, server_name: str) -> ToolSpec | None:
        if not isinstance(tool, dict):
            return None
        name = str(tool.get("name") or "").strip()
        if not name:
            return None
        canonical_id = f"mcp.{server_name}.{name}"
        self._tool_names[canonical_id] = (server_name, name)
        schema = tool.get("inputSchema")
        if not isinstance(schema, dict):
            schema = {"type": "object", "properties": {}}
        return ToolSpec(
            canonical_id=canonical_id,
            provider=self.namespace,
            description=str(tool.get("description") or f"MCP tool {name}"),
            parameters=schema,
            always_on=False,
            risk="mcp",
            category="mcp",
            search_hint=f"Remote MCP tool from server {server_name}: {name}",
        )


class MCPManagementProvider(ToolProvider):
    namespace = "mcp_admin"

    def __init__(
        self,
        registry: MCPServerRegistry,
        *,
        tool_registry: Any | None = None,
        mcp_provider_namespace: str = "mcp",
    ) -> None:
        self.registry = registry
        self.tool_registry = tool_registry
        self.mcp_provider_namespace = mcp_provider_namespace

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                canonical_id="mcp_list",
                provider=self.namespace,
                aliases=("mcp.list",),
                description="List configured MCP servers without revealing secret values.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                always_on=True,
                risk="read-only",
                category="mcp-admin",
                search_hint="List MCP servers and connection status.",
            ),
            ToolSpec(
                canonical_id="mcp_add",
                provider=self.namespace,
                aliases=("mcp.add",),
                description="Add or replace an MCP server configuration and refresh MCP tools.",
                parameters={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string"},
                        "command": {"type": "string"},
                        "args": {
                            "type": "array",
                            "items": {"type": "string"},
                            "default": [],
                        },
                        "env": {
                            "type": "object",
                            "additionalProperties": {"type": "string"},
                            "default": {},
                        },
                        "cwd": {"type": "string"},
                        "timeout_seconds": {"type": "number", "default": 15},
                    },
                    "required": ["name", "command"],
                },
                always_on=False,
                risk="mcp-admin",
                category="mcp-admin",
                search_hint="Add, install, configure, or connect a new MCP server.",
            ),
            ToolSpec(
                canonical_id="mcp_remove",
                provider=self.namespace,
                aliases=("mcp.remove",),
                description="Remove an MCP server configuration, close it, and refresh MCP tools.",
                parameters={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
                always_on=False,
                risk="mcp-admin",
                category="mcp-admin",
                search_hint="Remove, disconnect, or delete an MCP server.",
            ),
            ToolSpec(
                canonical_id="mcp_reload",
                provider=self.namespace,
                aliases=("mcp.reload",),
                description="Reload MCP server configuration from disk and refresh MCP tools.",
                parameters={
                    "type": "object",
                    "properties": {},
                },
                always_on=False,
                risk="mcp-admin",
                category="mcp-admin",
                search_hint="Reload MCP server configuration from mcp_servers.json.",
            ),
        ]

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        try:
            if canonical_id == "mcp_list":
                return ToolCallResult(canonical_id, self._list_servers())
            if canonical_id == "mcp_add":
                return self._add_server(canonical_id, arguments)
            if canonical_id == "mcp_remove":
                return self._remove_server(canonical_id, arguments)
            if canonical_id == "mcp_reload":
                self.registry.reload()
                self._refresh_mcp_tools()
                return ToolCallResult(canonical_id, self._list_servers())
        except (MCPClientError, OSError, ValueError) as exc:
            return ToolCallResult(canonical_id, f"Error: {exc}", True)
        return ToolCallResult(canonical_id, f"Error: Unknown tool: {canonical_id}", True)

    def _add_server(
        self,
        canonical_id: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        args = arguments.get("args") or []
        if isinstance(args, str):
            args = [args]
        if not isinstance(args, list):
            return ToolCallResult(canonical_id, "Error: args must be a list of strings", True)
        env = arguments.get("env") or {}
        if not isinstance(env, dict):
            return ToolCallResult(canonical_id, "Error: env must be an object", True)
        server = self.registry.add_server(
            name=str(arguments.get("name") or ""),
            command=str(arguments.get("command") or ""),
            args=[str(arg) for arg in args],
            env={str(key): str(value) for key, value in env.items()},
            cwd=str(arguments.get("cwd") or "") or None,
            timeout_seconds=arguments.get("timeout_seconds") or 15.0,
        )
        self._refresh_mcp_tools()
        return ToolCallResult(
            canonical_id,
            json.dumps(
                {
                    "added": server.name,
                    "command": server.command,
                    "args": list(server.args),
                    "env_keys": sorted(server.env),
                    "servers": self.registry.list_servers(),
                },
                ensure_ascii=False,
            ),
        )

    def _remove_server(
        self,
        canonical_id: str,
        arguments: dict[str, Any],
    ) -> ToolCallResult:
        name = str(arguments.get("name") or "")
        removed = self.registry.remove_server(name)
        self._refresh_mcp_tools()
        return ToolCallResult(
            canonical_id,
            json.dumps(
                {
                    "removed": removed,
                    "name": name,
                    "servers": self.registry.list_servers(),
                },
                ensure_ascii=False,
            ),
            error=not removed,
        )

    def _list_servers(self) -> str:
        return json.dumps(self.registry.list_servers(), ensure_ascii=False)

    def _refresh_mcp_tools(self) -> None:
        if self.tool_registry is not None:
            self.tool_registry.refresh_provider(self.mcp_provider_namespace)


def tool_name_from_canonical(canonical_id: str, server_name: str) -> str:
    prefix = f"mcp.{server_name}."
    if canonical_id.startswith(prefix):
        return canonical_id.removeprefix(prefix)
    return canonical_id.rsplit(".", 1)[-1]


def server_and_tool_from_canonical(canonical_id: str) -> tuple[str, str]:
    parts = canonical_id.split(".")
    if len(parts) >= 3 and parts[0] == "mcp":
        return parts[1], ".".join(parts[2:])
    return "default", canonical_id.rsplit(".", 1)[-1]
