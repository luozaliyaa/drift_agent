"""Persistent MCP server registry."""

from __future__ import annotations

import json
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

    def server_names(self) -> list[str]:
        return sorted(self.config.servers)

    def list_servers(self) -> list[dict[str, Any]]:
        return [
            {
                "name": server.name,
                "command": server.command,
                "args": list(server.args),
                "cwd": str(server.cwd) if server.cwd else "",
                "timeout_seconds": server.timeout_seconds,
                "env_keys": sorted(server.env),
                "running": name in self._clients,
                "tools_cached": name in self._tool_cache,
            }
            for name, server in sorted(self.config.servers.items())
        ]

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

    def add_server(
        self,
        *,
        name: str,
        command: str,
        args: list[str] | tuple[str, ...] | None = None,
        env: dict[str, str] | None = None,
        cwd: str | Path | None = None,
        timeout_seconds: float = 15.0,
        persist: bool = True,
    ) -> MCPServerConfig:
        clean_name = validate_server_name(name)
        clean_command = str(command).strip()
        if not clean_command:
            raise MCPClientError("MCP server command is required")
        try:
            timeout = float(timeout_seconds)
        except (TypeError, ValueError):
            timeout = 15.0
        server = MCPServerConfig(
            name=clean_name,
            command=clean_command,
            args=tuple(str(arg) for arg in (args or ())),
            env={str(key): str(value) for key, value in (env or {}).items()},
            cwd=Path(str(cwd)) if cwd else None,
            timeout_seconds=max(1.0, timeout),
        )
        self.close_server(clean_name)
        servers = dict(self.config.servers)
        servers[clean_name] = server
        self.config = MCPConfig(servers)
        self._tool_cache.pop(clean_name, None)
        if persist:
            self.save_config()
        return server

    def remove_server(self, name: str, *, persist: bool = True) -> bool:
        clean_name = validate_server_name(name)
        existed = clean_name in self.config.servers
        self.close_server(clean_name)
        servers = dict(self.config.servers)
        servers.pop(clean_name, None)
        self.config = MCPConfig(servers)
        self._tool_cache.pop(clean_name, None)
        if persist:
            self.save_config()
        return existed

    def save_config(self) -> None:
        payload = {
            "servers": {
                name: serialize_server_config(server)
                for name, server in sorted(self.config.servers.items())
            }
        }
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.config_path.with_name(self.config_path.name + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tmp_path.replace(self.config_path)

    def close_server(self, server_name: str) -> None:
        client = self._clients.pop(server_name, None)
        self._tool_cache.pop(server_name, None)
        if client is None:
            return
        if hasattr(client, "__exit__"):
            client.__exit__(None, None, None)
        elif hasattr(client, "close"):
            client.close()

    def close_all(self) -> None:
        clients = list(self._clients.values())
        self._clients.clear()
        self._tool_cache.clear()
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


def validate_server_name(name: str) -> str:
    clean_name = str(name).strip()
    if not clean_name:
        raise MCPClientError("MCP server name is required")
    allowed = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")
    if any(char not in allowed for char in clean_name):
        raise MCPClientError(
            "MCP server name may only contain letters, numbers, dots, underscores, and dashes"
        )
    return clean_name


def serialize_server_config(server: MCPServerConfig) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "command": server.command,
    }
    if server.args:
        payload["args"] = list(server.args)
    if server.env:
        payload["env"] = dict(server.env)
    if server.cwd:
        payload["cwd"] = str(server.cwd)
    if server.timeout_seconds != 15.0:
        payload["timeout_seconds"] = server.timeout_seconds
    return payload
