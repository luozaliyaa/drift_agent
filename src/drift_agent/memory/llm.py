"""LLM helpers for memory consolidation and optimization."""

from __future__ import annotations

import json
from typing import Any, Protocol

from drift_agent.memory.types import (
    ConsolidationResult,
    HistoryEntry,
    PendingItem,
    RecentContext,
)


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...


class MemoryLLM:
    def __init__(self, client: ChatClient) -> None:
        self.client = client

    def consolidate_turns(self, turns: list[dict[str, object]]) -> ConsolidationResult:
        content = json.dumps(turns, ensure_ascii=False, indent=2)
        message = self.client.chat(
            [
                {
                    "role": "system",
                    "content": CONSOLIDATION_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": "Consolidate these turns as JSON only:\n" + content,
                },
            ],
            [],
        )
        return parse_consolidation_response(str(message.get("content") or ""))

    def optimize_memory(
        self,
        *,
        self_model: str,
        memory: str,
        pending: str,
    ) -> tuple[str, str]:
        payload = {
            "self_model": self_model,
            "memory": memory,
            "pending": pending,
        }
        message = self.client.chat(
            [
                {
                    "role": "system",
                    "content": OPTIMIZER_SYSTEM_PROMPT,
                },
                {
                    "role": "user",
                    "content": "Optimize these memory files as JSON only:\n"
                    + json.dumps(payload, ensure_ascii=False, indent=2),
                },
            ],
            [],
        )
        data = parse_json_object(str(message.get("content") or ""))
        return (
            str(data.get("self_model") or self_model).strip(),
            str(data.get("memory") or memory).strip(),
        )


CONSOLIDATION_SYSTEM_PROMPT = """You maintain a local coding agent memory.
Return one JSON object with keys:
- history_entries: array of {summary, emotional_weight}
- pending_items: array of {tag, content}
- recent_context: {until, compression, ongoing_threads}

Only treat user messages as facts about the user. Do not convert assistant advice
into user facts. Allowed pending tags: identity, preference, key_info,
health_long_term, requested_memory, correction.
"""


OPTIMIZER_SYSTEM_PROMPT = """You maintain compact full-prompt Markdown memory files.
Return one JSON object with keys:
- self_model: full replacement Markdown for SELF.md
- memory: full replacement Markdown for MEMORY.md

Merge pending facts into stable, concise Markdown. Ignore duplicates. Apply
correction items by replacing contradicted older facts. Keep both files compact.
"""


def parse_consolidation_response(content: str) -> ConsolidationResult:
    data = parse_json_object(content)
    history_entries = [
        HistoryEntry(
            summary=str(item.get("summary") or "").strip(),
            emotional_weight=to_int(item.get("emotional_weight"), 0),
        )
        for item in data.get("history_entries", [])
        if isinstance(item, dict) and str(item.get("summary") or "").strip()
    ]
    pending_items = [
        PendingItem(
            tag=str(item.get("tag") or "requested_memory").strip(),
            content=str(item.get("content") or "").strip(),
        )
        for item in data.get("pending_items", [])
        if isinstance(item, dict) and str(item.get("content") or "").strip()
    ]
    recent_raw = data.get("recent_context") or {}
    if not isinstance(recent_raw, dict):
        recent_raw = {}
    recent_context = RecentContext(
        until=str(recent_raw.get("until") or "").strip(),
        compression=list_of_strings(recent_raw.get("compression")),
        ongoing_threads=list_of_strings(recent_raw.get("ongoing_threads")),
    )
    return ConsolidationResult(
        history_entries=history_entries,
        pending_items=pending_items,
        recent_context=recent_context,
    )


def parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned or "{}")
    if not isinstance(data, dict):
        raise ValueError("Memory LLM response must be a JSON object")
    return data


def list_of_strings(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def to_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
