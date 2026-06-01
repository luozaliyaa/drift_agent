"""Tool registry and dispatch."""

from __future__ import annotations

import json
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
        self._register_provider_specs(provider)
        self._rebuild_aliases()

    def refresh_provider(self, namespace: str) -> None:
        provider = self._providers.get(namespace)
        if provider is None:
            return
        for canonical_id, spec in list(self._specs.items()):
            if spec.provider == namespace:
                del self._specs[canonical_id]
        self._register_provider_specs(provider)
        self._rebuild_aliases()

    def _register_provider_specs(self, provider: ToolProvider) -> None:
        for spec in provider.list_tools():
            if not spec.enabled:
                continue
            if spec.canonical_id in self._specs:
                raise ValueError(f"Duplicate tool id: {spec.canonical_id}")
            self._specs[spec.canonical_id] = spec

    def _rebuild_aliases(self) -> None:
        self._aliases = {}
        for spec in self._specs.values():
            self._aliases[spec.encoded_name] = spec.canonical_id
            self._aliases[spec.canonical_id] = spec.canonical_id
            for alias in spec.aliases:
                self._aliases[alias] = spec.canonical_id

    def as_openai_tools(
        self,
        visible_names: set[str] | list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        if visible_names is None:
            return [spec.as_openai_tool() for spec in self.specs]
        visible = {self.resolve_name(name) for name in visible_names}
        return [
            spec.as_openai_tool()
            for spec in self.specs
            if spec.canonical_id in visible
        ]

    def always_on_names(self) -> set[str]:
        return {
            spec.canonical_id
            for spec in self.specs
            if spec.always_on or spec.canonical_id == "tool_search"
        }

    def is_visible(
        self,
        name: str,
        visible_names: set[str] | list[str] | tuple[str, ...] | None,
    ) -> bool:
        if visible_names is None:
            return True
        canonical_id = self.resolve_name(name)
        return canonical_id in {self.resolve_name(item) for item in visible_names}

    def search(self, query: str, limit: int = 8) -> list[dict[str, str]]:
        terms = [term.casefold() for term in query.replace(":", " ").split() if term]
        scored: list[tuple[int, ToolSpec]] = []
        for spec in self.specs:
            if spec.canonical_id == "tool_search":
                continue
            haystack = " ".join(
                [
                    spec.canonical_id,
                    spec.encoded_name,
                    *spec.aliases,
                    spec.description,
                    spec.provider,
                    spec.category,
                    spec.risk,
                    spec.search_hint,
                ]
            ).casefold()
            if not terms:
                score = 1
            else:
                score = sum(3 if term in spec.canonical_id.casefold() else 0 for term in terms)
                score += sum(2 if term in " ".join(spec.aliases).casefold() else 0 for term in terms)
                score += sum(1 if term in haystack else 0 for term in terms)
            if score > 0:
                scored.append((score, spec))
        scored.sort(key=lambda item: (-item[0], item[1].canonical_id))
        return [tool_info(spec) for _score, spec in scored[: max(1, limit)]]

    def exact_tool_match(self, name: str) -> str | None:
        canonical_id = self.resolve_name(name)
        if canonical_id in self._specs and canonical_id != "tool_search":
            return canonical_id
        return None

    def list_tool_info(self) -> list[dict[str, str]]:
        return [tool_info(spec) for spec in self.specs]

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


class ToolSearchProvider(ToolProvider):
    namespace = "tool_search"

    def __init__(self, registry: ToolRegistry, enabled: bool = True) -> None:
        self.registry = registry
        self.enabled = enabled

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                canonical_id="tool_search",
                provider=self.namespace,
                aliases=("search_tools",),
                description=(
                    "Search available deferred tools by name or capability. "
                    "Use select or tool to unlock an exact tool for this turn."
                ),
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Capability or keyword to search for.",
                        },
                        "select": {
                            "type": "string",
                            "description": "Exact tool id, encoded name, or alias to unlock.",
                        },
                        "tool": {
                            "type": "string",
                            "description": "Alias for select.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of matching tools to return.",
                            "default": 8,
                        },
                    },
                },
                enabled=self.enabled,
                always_on=True,
                risk="read-only",
                category="meta",
            )
        ]

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        if not self.enabled:
            return ToolCallResult(canonical_id, "Tool search is disabled.", True)
        try:
            limit = int(arguments.get("limit") or 8)
        except (TypeError, ValueError):
            limit = 8
        selected = str(arguments.get("select") or arguments.get("tool") or "").strip()
        query = selected or str(arguments.get("query") or "").strip()
        exact = self.registry.exact_tool_match(selected or query)
        matches = [tool_info(self.registry._specs[exact])] if exact else self.registry.search(query, limit)
        return ToolCallResult(
            canonical_id,
            json.dumps(
                {
                    "selected": exact or "",
                    "tools": matches,
                    "hint": "Call tool_search with select set to an exact id to unlock a deferred tool.",
                },
                ensure_ascii=False,
            ),
        )


def tool_info(spec: ToolSpec) -> dict[str, str]:
    return {
        "id": spec.canonical_id,
        "encoded_name": spec.encoded_name,
        "description": spec.description,
        "provider": spec.provider,
        "always_on": str(spec.always_on).lower(),
        "risk": spec.risk,
        "category": spec.category,
        "search_hint": spec.search_hint,
    }


def create_default_tool_registry(
    workdir: str | Path | None = None,
    permission_policy: PermissionPolicy | None = None,
    enable_web_tools: bool = False,
    enable_mcp_tools: bool = False,
    mcp_config_path: str | Path = "mcp_servers.json",
    mcp_server: str = "github",
    memory_manager: MemoryManager | None = None,
    plugin_manager: Any | None = None,
    enable_tool_search: bool = True,
    mcp_registry: Any | None = None,
) -> ToolRegistry:
    from drift_agent.tools.mcp import MCPManagementProvider, MCPToolProvider, SyncMCPClient
    from drift_agent.tools.memory import MemoryToolProvider
    from drift_agent.tools.web import WebToolProvider
    from drift_agent.tools.workspace import WorkspaceToolProvider
    from drift_agent.plugins import PluginToolProvider

    registry = ToolRegistry()
    registry.register_provider(WorkspaceToolProvider(workdir, permission_policy))
    if memory_manager is not None:
        registry.register_provider(MemoryToolProvider(memory_manager, enabled=True))
    if enable_web_tools:
        registry.register_provider(WebToolProvider(enabled=True))
    if enable_mcp_tools:
        if mcp_registry is None:
            from drift_agent.mcp import MCPServerRegistry

            mcp_registry = MCPServerRegistry(mcp_config_path, client_factory=SyncMCPClient)
        mcp_provider = MCPToolProvider(
            server_name=mcp_server,
            enabled=True,
            config_path=mcp_config_path,
            registry=mcp_registry,
            include_all_servers=True,
        )
        registry.register_provider(
            mcp_provider
        )
        registry.register_provider(
            MCPManagementProvider(
                mcp_registry,
                tool_registry=registry,
                mcp_provider_namespace=mcp_provider.namespace,
            )
        )
    if plugin_manager is not None and plugin_manager.enabled:
        registry.register_provider(PluginToolProvider(plugin_manager))
    if enable_tool_search:
        registry.register_provider(ToolSearchProvider(registry, enabled=True))
    return registry
