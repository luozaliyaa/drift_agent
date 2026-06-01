"""Turn consolidation for Akashic-style Markdown memory."""

from __future__ import annotations

from datetime import UTC, datetime

from drift_agent.memory.llm import MemoryLLM
from drift_agent.memory.markdown_store import MarkdownMemoryStore
from drift_agent.memory.sqlite_store import SQLiteContextStore
from drift_agent.memory.types import MemoryRecord, RecentContext
from drift_agent.memory.vector_store import VectorMemoryStore, stable_record_id


class MemoryConsolidator:
    def __init__(
        self,
        *,
        markdown: MarkdownMemoryStore,
        sqlite: SQLiteContextStore,
        vector: VectorMemoryStore,
        llm: MemoryLLM | None = None,
        keep_count: int = 8,
        consolidation_min: int | None = None,
    ) -> None:
        self.markdown = markdown
        self.sqlite = sqlite
        self.vector = vector
        self.llm = llm
        self.keep_count = keep_count
        self.consolidation_min = consolidation_min

    def maybe_consolidate(self, session_id: str) -> list[str]:
        recent_turns = self.sqlite.load_recent_turns(session_id, self.keep_count)
        self.markdown.refresh_recent_turns(recent_turns)
        if self.llm is None:
            return []

        turns = self.sqlite.load_unconsolidated_turns(session_id, self.keep_count)
        minimum = self.consolidation_min or max(5, self.keep_count // 2)
        if len(turns) < minimum:
            return []

        source_ref = tuple(f"turn:{turn['id']}" for turn in turns)
        if self.sqlite.has_consolidation_write(source_ref, "batch"):
            return []

        result = self.llm.consolidate_turns(turns)
        now = datetime.now(UTC).isoformat(timespec="seconds")
        recent = RecentContext(
            compression=result.recent_context.compression,
            ongoing_threads=result.recent_context.ongoing_threads,
            recent_turns=recent_turns,
            until=result.recent_context.until or now,
        )
        self.markdown.write_recent_context(recent)

        writes: list[str] = []
        writes.extend(self.markdown.append_history_entries(result.history_entries, source_ref))
        writes.extend(self.markdown.append_pending_items(result.pending_items, source_ref))
        for entry in result.history_entries:
            record = MemoryRecord(
                id=stable_record_id("history", entry.summary),
                memory_type="history",
                content=entry.summary,
                summary=entry.summary,
                source_ref=source_ref,
            )
            self.vector.ingest(record)
        for item in result.pending_items:
            content = item.content.strip()
            if not content:
                continue
            record = MemoryRecord(
                id=stable_record_id(item.normalized_tag(), content),
                memory_type=item.normalized_tag(),
                content=content,
                summary=content,
                source_ref=source_ref,
            )
            self.vector.ingest(record)

        self.sqlite.record_consolidation_write(source_ref, "batch")
        self.sqlite.mark_turns_consolidated(
            session_id,
            [int(turn["id"]) for turn in turns],
        )
        return writes
