"""High-level memory manager."""

from __future__ import annotations

from pathlib import Path

from drift_agent.memory.extraction import extract_memory_items
from drift_agent.memory.markdown_store import MarkdownMemoryStore
from drift_agent.memory.retrieval import select_relevant_memories
from drift_agent.memory.sqlite_store import SQLiteContextStore, json_dumps
from drift_agent.memory.types import (
    MemoryContext,
    ToolCallRecord,
    TurnRecord,
)


class MemoryManager:
    def __init__(
        self,
        memory_dir: str | Path = ".memory",
        session_id: str = "default",
        enabled: bool = True,
    ) -> None:
        self.memory_dir = Path(memory_dir)
        self.session_id = session_id
        self.enabled = enabled
        self.markdown = MarkdownMemoryStore(self.memory_dir) if enabled else None
        self.sqlite = SQLiteContextStore(self.memory_dir) if enabled else None

    def load_prompt_context(self, task: str) -> MemoryContext:
        if not self.enabled or self.markdown is None or self.sqlite is None:
            return MemoryContext()

        index = self.markdown.read_index()
        summary, recent_turns = self.sqlite.load_session_context(self.session_id)
        query = "\n".join([task, summary, *[turn[0] for turn in recent_turns]])
        relevant = select_relevant_memories(query, self.markdown.list_items())

        sources = []
        if index:
            sources.append("MEMORY.md index")
        sources.extend(f"memory:{item.name}" for item in relevant)
        if summary:
            sources.append(f"sqlite:{self.session_id}:summary")
        if recent_turns:
            sources.append(f"sqlite:{self.session_id}:recent_turns")

        return MemoryContext(
            index=index,
            relevant_items=relevant,
            session_summary=summary,
            recent_turns=recent_turns,
            sources=sources,
        )

    def record_turn(
        self,
        user_prompt: str,
        assistant_answer: str,
        status: str,
        tool_calls: list[dict[str, object]] | None = None,
    ) -> list[str]:
        if not self.enabled or self.markdown is None or self.sqlite is None:
            return []

        tool_records = [
            ToolCallRecord(
                name=str(call.get("name", "")),
                arguments=json_dumps(call.get("arguments", "")),
                result_preview=str(call.get("result", ""))[:1000],
            )
            for call in (tool_calls or [])
        ]
        self.sqlite.record_turn(
            TurnRecord(
                session_id=self.session_id,
                user_prompt=user_prompt,
                assistant_answer=assistant_answer,
                status=status,
                tool_calls=tool_records,
            )
        )

        written = []
        for item in extract_memory_items(user_prompt, assistant_answer):
            path = self.markdown.write_item(item)
            written.append(path.stem)
            self.sqlite.record_memory_event(self.session_id, path.stem, "extracted")
        return written
