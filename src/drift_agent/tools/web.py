"""Reserved web tools provider."""

from __future__ import annotations

from typing import Any

from drift_agent.tools.base import ToolCallResult, ToolProvider, ToolSpec


class WebToolProvider(ToolProvider):
    namespace = "web"

    def __init__(self, enabled: bool = False) -> None:
        self.enabled = enabled
        self._specs = [
            ToolSpec(
                canonical_id="web.search",
                provider=self.namespace,
                description="Search the web. Reserved for a future web provider.",
                parameters={
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
                enabled=enabled,
            ),
            ToolSpec(
                canonical_id="web.fetch",
                provider=self.namespace,
                description="Fetch a URL. Reserved for a future web provider.",
                parameters={
                    "type": "object",
                    "properties": {"url": {"type": "string"}},
                    "required": ["url"],
                },
                enabled=enabled,
            ),
        ]

    def list_tools(self) -> list[ToolSpec]:
        return self._specs

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        return ToolCallResult(canonical_id, f"Tool disabled: {canonical_id}", True)
