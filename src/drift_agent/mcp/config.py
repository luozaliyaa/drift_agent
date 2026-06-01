"""MCP server configuration loading."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class MCPServerConfig:
    name: str
    command: str
    args: tuple[str, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    cwd: Path | None = None
    timeout_seconds: float = 15.0


@dataclass(frozen=True)
class MCPConfig:
    servers: dict[str, MCPServerConfig] = field(default_factory=dict)

    def get(self, name: str) -> MCPServerConfig | None:
        return self.servers.get(name)


def load_mcp_config(path: str | Path = "mcp_servers.json") -> MCPConfig:
    config_path = Path(path)
    if not config_path.exists():
        return MCPConfig()
    try:
        raw = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return MCPConfig()
    raw_servers = raw.get("servers", raw) if isinstance(raw, dict) else raw
    servers: dict[str, MCPServerConfig] = {}
    if isinstance(raw_servers, dict):
        iterable = [
            {"name": name, **value}
            for name, value in raw_servers.items()
            if isinstance(value, dict)
        ]
    elif isinstance(raw_servers, list):
        iterable = [item for item in raw_servers if isinstance(item, dict)]
    else:
        iterable = []
    for item in iterable:
        server = parse_server_config(item)
        if server is not None:
            servers[server.name] = server
    return MCPConfig(servers)


def parse_server_config(raw: dict[str, Any]) -> MCPServerConfig | None:
    name = str(raw.get("name") or raw.get("server") or "").strip()
    command = str(raw.get("command") or "").strip()
    if not name or not command:
        return None
    args = raw.get("args") or raw.get("arguments") or []
    if isinstance(args, str):
        args = [args]
    if not isinstance(args, list):
        args = []
    env = raw.get("env") or {}
    if not isinstance(env, dict):
        env = {}
    cwd = raw.get("cwd")
    timeout = raw.get("timeout_seconds", raw.get("timeout", 15.0))
    try:
        timeout_seconds = float(timeout)
    except (TypeError, ValueError):
        timeout_seconds = 15.0
    return MCPServerConfig(
        name=name,
        command=command,
        args=tuple(str(arg) for arg in args),
        env={str(key): str(value) for key, value in env.items()},
        cwd=Path(str(cwd)) if cwd else None,
        timeout_seconds=max(1.0, timeout_seconds),
    )
