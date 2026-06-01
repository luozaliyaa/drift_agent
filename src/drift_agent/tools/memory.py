"""Model-callable memory tools."""

from __future__ import annotations

import json
from typing import Any

from drift_agent.memory import MemoryManager
from drift_agent.tools.base import ToolCallResult, ToolProvider, ToolSpec


class MemoryToolProvider(ToolProvider):
    namespace = "memory"

    def __init__(self, memory_manager: MemoryManager | None, enabled: bool = True) -> None:
        self.memory_manager = memory_manager
        self.enabled = enabled and memory_manager is not None

    def list_tools(self) -> list[ToolSpec]:
        return [
            ToolSpec(
                canonical_id="memory.remember",
                description="Store a durable memory when the user asks to remember something.",
                parameters={
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "The exact fact, preference, or project context to remember.",
                        },
                        "memory_type": {
                            "type": "string",
                            "description": "Memory category such as preference, identity, project, or requested_memory.",
                            "default": "requested_memory",
                        },
                        "summary": {
                            "type": "string",
                            "description": "Short searchable summary.",
                        },
                    },
                    "required": ["content"],
                },
                provider=self.namespace,
                aliases=("remember",),
                enabled=self.enabled,
            ),
            ToolSpec(
                canonical_id="memory.recall",
                description="Search local semantic memory for relevant past facts or events.",
                parameters={
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "What to search memory for.",
                        },
                        "memory_type": {
                            "type": "string",
                            "description": "Optional memory category filter.",
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum number of records to return.",
                            "default": 5,
                        },
                    },
                    "required": ["query"],
                },
                provider=self.namespace,
                aliases=("recall_memory",),
                enabled=self.enabled,
            ),
            ToolSpec(
                canonical_id="memory.forget",
                description="Delete a local semantic memory by id.",
                parameters={
                    "type": "object",
                    "properties": {
                        "id": {
                            "type": "string",
                            "description": "The memory record id returned by recall.",
                        }
                    },
                    "required": ["id"],
                },
                provider=self.namespace,
                aliases=("forget_memory",),
                enabled=self.enabled,
            ),
        ]

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        if not self.enabled or self.memory_manager is None:
            return ToolCallResult(canonical_id, f"Tool disabled: {canonical_id}", True)
        if canonical_id == "memory.remember":
            content = str(arguments.get("content") or "").strip()
            if not content:
                return ToolCallResult(canonical_id, "Error: content is required", True)
            record = self.memory_manager.remember(
                content=content,
                memory_type=str(arguments.get("memory_type") or "requested_memory"),
                summary=str(arguments.get("summary") or ""),
            )
            if record is None:
                return ToolCallResult(canonical_id, "Memory is disabled.", True)
            return ToolCallResult(
                canonical_id,
                json.dumps(
                    {
                        "id": record.id,
                        "memory_type": record.memory_type,
                        "summary": record.summary,
                    },
                    ensure_ascii=False,
                ),
            )
        if canonical_id == "memory.recall":
            query = str(arguments.get("query") or "").strip()
            if not query:
                return ToolCallResult(canonical_id, "Error: query is required", True)
            try:
                limit = int(arguments.get("limit") or 5)
            except (TypeError, ValueError):
                return ToolCallResult(canonical_id, "Error: limit must be an integer", True)
            memory_type = arguments.get("memory_type")
            result = self.memory_manager.recall(
                query=query,
                memory_type=str(memory_type) if memory_type else None,
                limit=max(1, min(limit, 20)),
            )
            return ToolCallResult(
                canonical_id,
                json.dumps(
                    [
                        {
                            "id": record.id,
                            "memory_type": record.memory_type,
                            "summary": record.summary,
                            "content": record.content,
                            "updated_at": record.updated_at,
                        }
                        for record in result.records
                    ],
                    ensure_ascii=False,
                ),
            )
        if canonical_id == "memory.forget":
            record_id = str(arguments.get("id") or "").strip()
            if not record_id:
                return ToolCallResult(canonical_id, "Error: id is required", True)
            deleted = self.memory_manager.forget(record_id)
            return ToolCallResult(
                canonical_id,
                json.dumps({"deleted": deleted}, ensure_ascii=False),
                error=not deleted,
            )
        return ToolCallResult(canonical_id, f"Error: Unknown tool: {canonical_id}", True)
