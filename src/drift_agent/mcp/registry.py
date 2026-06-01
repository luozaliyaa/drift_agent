"""Persistent MCP server registry."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from drift_agent.mcp.client import MCPClientError, SyncMCPClient
from drift_agent.mcp.config import MCPConfig, MCPServerConfig, load_mcp_config


class MCPServerRegistry:
    """Lazy persistent MCP client pool for configured stdio servers."""

    def __init__(
        self,
        config_path: str | Path = "mcp_servers.json",
        *,
        client_factory: Any | None = None,
    ) -> None:
        self.config_path = Path(config_path)
        self.client_factory = client_factory or SyncMCPClient
        self.config: MCPConfig = load_mcp_config(self.config_path)
        self._clients: dict[str, Any] = {}
        self._tool_cache: dict[str, list[dict[str, Any]]] = {}

    def get_config(self, server_name: str) -> MCPServerConfig | None:
        return self.config.get(server_name)

    def list_tools(self, server_name: str) -> list[dict[str, Any]]:
        if server_name in self._tool_cache:
            return self._tool_cache[server_name]
        client = self._client(server_name)
        tools = client.list_tools()
        if not isinstance(tools, list):
            tools = []
        self._tool_cache[server_name] = tools
        return tools

    def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._client(server_name).call_tool(tool_name, arguments or {})

    def reload(self) -> None:
        self.close_all()
        self.config = load_mcp_config(self.config_path)
        self._tool_cache.clear()

    def close_all(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        for client in clients:
            if hasattr(client, "__exit__"):
                client.__exit__(None, None, None)
            elif hasattr(client, "close"):
                client.close()

    def _client(self, server_name: str) -> Any:
        if server_name in self._clients:
            return self._clients[server_name]
        config = self.get_config(server_name)
        if config is None:
            raise MCPClientError(f"MCP server not configured: {server_name}")
        client = self.client_factory(config)
        if hasattr(client, "__enter__"):
            client = client.__enter__()
        else:
            if hasattr(client, "start"):
                client.start()
            if hasattr(client, "initialize"):
                client.initialize()
        self._clients[server_name] = client
        return client
