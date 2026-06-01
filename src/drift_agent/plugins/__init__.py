"""Local plugin system for drift-agent."""

from drift_agent.plugins.api import Plugin, ToolHookContext, ToolHookResult
from drift_agent.plugins.manager import PluginManager, PluginToolProvider

__all__ = [
    "Plugin",
    "PluginManager",
    "PluginToolProvider",
    "ToolHookContext",
    "ToolHookResult",
]
