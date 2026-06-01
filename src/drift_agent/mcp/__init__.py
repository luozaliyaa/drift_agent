"""Minimal MCP client support."""

from drift_agent.mcp.client import MCPClientError, SyncMCPClient
from drift_agent.mcp.config import MCPConfig, MCPServerConfig, load_mcp_config
from drift_agent.mcp.registry import MCPServerRegistry

__all__ = [
    "MCPClientError",
    "MCPConfig",
    "MCPServerRegistry",
    "MCPServerConfig",
    "SyncMCPClient",
    "load_mcp_config",
]
