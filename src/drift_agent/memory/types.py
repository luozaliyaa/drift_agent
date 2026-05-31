"""Shared memory data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


SUPPORTED_PENDING_TAGS = {
    "identity",
    "preference",
    "key_info",
    "health_long_term",
    "requested_memory",
    "correction",
}


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
class HistoryEntry:
    summary: str
    emotional_weight: int = 0
    occurred_at: str = ""
    source_ref: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PendingItem:
    tag: str
    content: str
    source_ref: tuple[str, ...] = field(default_factory=tuple)

    def normalized_tag(self) -> str:
        if self.tag in SUPPORTED_PENDING_TAGS:
            return self.tag
        return "requested_memory"


@dataclass(frozen=True)
class RecentContext:
    compression: list[str] = field(default_factory=list)
    ongoing_threads: list[str] = field(default_factory=list)
    recent_turns: list[tuple[str, str]] = field(default_factory=list)
    until: str = ""

    def to_prompt(self) -> str:
        lines: list[str] = []
        if self.compression:
            lines.append("## Compression")
            if self.until:
                lines.append(f"until: {self.until}")
            lines.extend(f"- {line}" for line in self.compression)
        if self.ongoing_threads:
            if lines:
                lines.append("")
            lines.append("## Ongoing Threads")
            lines.extend(f"- {line}" for line in self.ongoing_threads)
        return "\n".join(lines).strip()


@dataclass(frozen=True)
class ConsolidationResult:
    history_entries: list[HistoryEntry] = field(default_factory=list)
    pending_items: list[PendingItem] = field(default_factory=list)
    recent_context: RecentContext = field(default_factory=RecentContext)


@dataclass(frozen=True)
class MemoryRecord:
    id: str
    memory_type: str
    content: str
    summary: str = ""
    source_ref: tuple[str, ...] = field(default_factory=tuple)
    created_at: str = ""
    updated_at: str = ""


@dataclass(frozen=True)
class RetrievalRequest:
    query: str
    memory_type: str | None = None
    limit: int = 5


@dataclass(frozen=True)
class RetrievalResult:
    records: list[MemoryRecord] = field(default_factory=list)

    def to_prompt(self) -> str:
        lines: list[str] = []
        for record in self.records:
            stamp = f" {record.updated_at}" if record.updated_at else ""
            summary = record.summary or record.content
            lines.append(f"[{record.id}]{stamp} ({record.memory_type}) {summary}")
        return "\n".join(lines)


@dataclass(frozen=True)
class MemoryContext:
    index: str = ""
    self_model: str = ""
    recent_context: RecentContext = field(default_factory=RecentContext)
    vector_results: list[MemoryRecord] = field(default_factory=list)
    relevant_items: list[MemoryItem] = field(default_factory=list)
    session_summary: str = ""
    recent_turns: list[tuple[str, str]] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)

    def to_prompt(self) -> str:
        parts: list[str] = []
        if self.self_model:
            parts.append(
                "## Drift Agent Self Model\n\n"
                + self.self_model.strip()
            )
        if self.index:
            parts.append(
                "## Long-term Memory\n\n"
                "<memory_index>\n" + self.index.strip() + "\n</memory_index>"
            )
        recent_prompt = self.recent_context.to_prompt()
        if recent_prompt:
            parts.append(
                "## Recent Context\n\n"
                "<recent_context>\n" + recent_prompt + "\n</recent_context>"
            )
        if self.vector_results:
            result_prompt = RetrievalResult(self.vector_results).to_prompt()
            parts.append(
                "## Retrieved Memory\n\n"
                "<retrieved_memories>\n"
                + result_prompt
                + "\n</retrieved_memories>"
            )
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
