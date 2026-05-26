"""Shared memory data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class MemoryItem:
    name: str
    type: str
    description: str
    body: str
    path: Path | None = None


@dataclass(frozen=True)
class ToolCallRecord:
    name: str
    arguments: str
    result_preview: str


@dataclass(frozen=True)
class TurnRecord:
    session_id: str
    user_prompt: str
    assistant_answer: str
    status: str
    tool_calls: list[ToolCallRecord] = field(default_factory=list)


@dataclass(frozen=True)
class MemoryContext:
    index: str = ""
    relevant_items: list[MemoryItem] = field(default_factory=list)
    session_summary: str = ""
    recent_turns: list[tuple[str, str]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        parts: list[str] = []
        if self.index:
            parts.append("<memory_index>\n" + self.index.strip() + "\n</memory_index>")
        if self.relevant_items:
            item_parts = []
            for item in self.relevant_items:
                item_parts.append(
                    f"## {item.name}\n"
                    f"type: {item.type}\n"
                    f"description: {item.description}\n\n"
                    f"{item.body.strip()}"
                )
            parts.append(
                "<relevant_memories>\n"
                + "\n\n".join(item_parts)
                + "\n</relevant_memories>"
            )
        if self.session_summary:
            parts.append(
                "<session_summary>\n"
                + self.session_summary.strip()
                + "\n</session_summary>"
            )
        if self.recent_turns:
            lines = []
            for user_prompt, assistant_answer in self.recent_turns:
                lines.append(f"user: {user_prompt}")
                lines.append(f"assistant: {assistant_answer}")
            parts.append("<recent_turns>\n" + "\n".join(lines) + "\n</recent_turns>")
        return "\n\n".join(parts)

    def describe_sources(self) -> str:
        return "\n".join(f"- {source}" for source in self.sources)
