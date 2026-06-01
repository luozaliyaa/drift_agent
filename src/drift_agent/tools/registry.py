"""Tool registry and dispatch."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from drift_agent.memory import MemoryManager
from drift_agent.permissions import PermissionPolicy
from drift_agent.tools.base import (
    ToolCallResult,
    ToolProvider,
    ToolSpec,
    decode_tool_name,
    parse_arguments,
)


class ToolRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, ToolProvider] = {}
        self._specs: dict[str, ToolSpec] = {}
        self._aliases: dict[str, str] = {}
        self.last_canonical_id: str | None = None

    @property
    def specs(self) -> list[ToolSpec]:
        return list(self._specs.values())

    def register_provider(self, provider: ToolProvider) -> None:
        self._providers[provider.namespace] = provider
        for spec in provider.list_tools():
            if not spec.enabled:
                continue
            if spec.canonical_id in self._specs:
                raise ValueError(f"Duplicate tool id: {spec.canonical_id}")
            self._specs[spec.canonical_id] = spec
            self._aliases[spec.encoded_name] = spec.canonical_id
            self._aliases[spec.canonical_id] = spec.canonical_id
            for alias in spec.aliases:
                self._aliases[alias] = spec.canonical_id

    def as_openai_tools(self) -> list[dict[str, Any]]:
        return [spec.as_openai_tool() for spec in self.specs]

    def list_tool_info(self) -> list[dict[str, str]]:
        return [
            {
                "id": spec.canonical_id,
                "encoded_name": spec.encoded_name,
                "description": spec.description,
                "provider": spec.provider,
            }
            for spec in self.specs
        ]

    def resolve_name(self, name: str) -> str:
        if name in self._aliases:
            return self._aliases[name]
        decoded = decode_tool_name(name)
        if decoded in self._specs:
            return decoded
        return decoded

    def dispatch_json(
        self,
        name: str,
        raw_arguments: str | dict[str, Any] | None,
    ) -> str:
        return self.dispatch(name, raw_arguments).output

    def dispatch(
        self,
        name: str,
        raw_arguments: str | dict[str, Any] | None,
    ) -> ToolCallResult:
        canonical_id = self.resolve_name(name)
        self.last_canonical_id = canonical_id
        spec = self._specs.get(canonical_id)
        if spec is None:
            return ToolCallResult(canonical_id, f"Error: Unknown tool: {canonical_id}", True)

        provider = self._providers.get(spec.provider)
        if provider is None:
            return ToolCallResult(canonical_id, f"Error: Missing provider: {spec.provider}", True)

        try:
            arguments = parse_arguments(raw_arguments)
        except ValueError as exc:
            return ToolCallResult(canonical_id, f"Error: {exc}", True)
        return provider.call_tool(canonical_id, arguments)


def create_default_tool_registry(
    workdir: str | Path | None = None,
    permission_policy: PermissionPolicy | None = None,
    enable_web_tools: bool = False,
    enable_mcp_tools: bool = False,
    memory_manager: MemoryManager | None = None,
) -> ToolRegistry:
    from drift_agent.tools.mcp import MCPToolProvider
    from drift_agent.tools.memory import MemoryToolProvider
    from drift_agent.tools.web import WebToolProvider
    from drift_agent.tools.workspace import WorkspaceToolProvider

    registry = ToolRegistry()
    registry.register_provider(WorkspaceToolProvider(workdir, permission_policy))
    if memory_manager is not None:
        registry.register_provider(MemoryToolProvider(memory_manager, enabled=True))
    if enable_web_tools:
        registry.register_provider(WebToolProvider(enabled=True))
    if enable_mcp_tools:
        registry.register_provider(MCPToolProvider(enabled=False))
    return registry
