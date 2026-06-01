"""High-level memory manager."""

from __future__ import annotations

from pathlib import Path

from drift_agent.memory.consolidation import MemoryConsolidator
from drift_agent.memory.extraction import extract_memory_items
from drift_agent.memory.llm import MemoryLLM
from drift_agent.memory.markdown_store import MarkdownMemoryStore
from drift_agent.memory.optimizer import MemoryOptimizer
from drift_agent.memory.retrieval import select_relevant_memories
from drift_agent.memory.sqlite_store import SQLiteContextStore, json_dumps
from drift_agent.memory.types import (
    MemoryContext,
    MemoryRecord,
    PendingItem,
    RetrievalRequest,
    RetrievalResult,
    ToolCallRecord,
    TurnRecord,
)
from drift_agent.memory.vector_store import VectorMemoryStore


class MemoryManager:
    def __init__(
        self,
        memory_dir: str | Path = ".memory",
        session_id: str = "default",
        enabled: bool = True,
        llm: MemoryLLM | None = None,
        keep_count: int = 8,
        consolidation_min: int | None = None,
        optimizer_interval_seconds: int = 64800,
        optimize_now: bool = False,
    ) -> None:
        self.memory_dir = Path(memory_dir)
        self.session_id = session_id
        self.enabled = enabled
        self.llm = llm
        self.keep_count = keep_count
        self.consolidation_min = consolidation_min
        self.optimizer_interval_seconds = optimizer_interval_seconds
        self.optimize_now = optimize_now
        self.markdown = MarkdownMemoryStore(self.memory_dir) if enabled else None
        self.sqlite = SQLiteContextStore(self.memory_dir) if enabled else None
        self.vector = VectorMemoryStore(self.memory_dir) if enabled else None
        self.consolidator = (
            MemoryConsolidator(
                markdown=self.markdown,
                sqlite=self.sqlite,
                vector=self.vector,
                llm=self.llm,
                keep_count=self.keep_count,
                consolidation_min=self.consolidation_min,
            )
            if enabled and self.markdown and self.sqlite and self.vector
            else None
        )
        self.optimizer = (
            MemoryOptimizer(
                markdown=self.markdown,
                sqlite=self.sqlite,
                llm=self.llm,
                interval_seconds=self.optimizer_interval_seconds,
            )
            if enabled and self.markdown and self.sqlite
            else None
        )
        if self.enabled:
            self._migrate_legacy_items()
            if self.optimize_now and self.optimizer is not None:
                self.optimizer.maybe_optimize(force=True)

    def configure_llm(self, llm: MemoryLLM) -> None:
        self.llm = llm
        if not self.enabled or self.markdown is None or self.sqlite is None:
            return
        if self.vector is not None:
            self.consolidator = MemoryConsolidator(
                markdown=self.markdown,
                sqlite=self.sqlite,
                vector=self.vector,
                llm=self.llm,
                keep_count=self.keep_count,
                consolidation_min=self.consolidation_min,
            )
        self.optimizer = MemoryOptimizer(
            markdown=self.markdown,
            sqlite=self.sqlite,
            llm=self.llm,
            interval_seconds=self.optimizer_interval_seconds,
        )

    def load_prompt_context(self, task: str) -> MemoryContext:
        if (
            not self.enabled
            or self.markdown is None
            or self.sqlite is None
            or self.vector is None
        ):
            return MemoryContext()

        self_model = self.markdown.read_self()
        index = self.markdown.read_index()
        recent_context = self.markdown.read_recent_context()
        summary, recent_turns = self.sqlite.load_session_context(self.session_id)
        query = "\n".join([task, summary, *[turn[0] for turn in recent_turns]])
        relevant = select_relevant_memories(query, self.markdown.list_items())
        vector_results = self.vector.retrieve(RetrievalRequest(query=query)).records

        sources = []
        if self_model:
            sources.append("SELF.md")
        if index:
            sources.append("MEMORY.md index")
        if recent_context.to_prompt():
            sources.append("RECENT_CONTEXT.md")
        sources.extend(f"memory2:{record.id}" for record in vector_results)
        sources.extend(f"memory:{item.name}" for item in relevant)
        if summary:
            sources.append(f"sqlite:{self.session_id}:summary")
        if recent_turns:
            sources.append(f"sqlite:{self.session_id}:recent_turns")

        return MemoryContext(
            index=index,
            self_model=self_model,
            recent_context=recent_context,
            vector_results=vector_results,
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
        if self.llm is None:
            written.extend(self._record_heuristic_memories(user_prompt, assistant_answer))
        if self.consolidator is not None:
            written.extend(self.consolidator.maybe_consolidate(self.session_id))
        if self.optimizer is not None:
            written.extend(self.optimizer.maybe_optimize(force=self.optimize_now))
            self.optimize_now = False
        return written

    def remember(
        self,
        content: str,
        memory_type: str = "requested_memory",
        summary: str = "",
    ) -> MemoryRecord | None:
        if not self.enabled or self.vector is None:
            return None
        record = self.vector.remember(
            content=content,
            memory_type=memory_type,
            summary=summary,
            source_ref=(f"manual:{self.session_id}",),
        )
        if self.markdown is not None:
            self.markdown.append_pending_items(
                [PendingItem(tag=memory_type, content=content)],
                source_ref=(f"manual:{record.id}",),
            )
        return record

    def recall(
        self,
        query: str,
        memory_type: str | None = None,
        limit: int = 5,
    ) -> RetrievalResult:
        if not self.enabled or self.vector is None:
            return RetrievalResult()
        return self.vector.retrieve_explicit(
            RetrievalRequest(query=query, memory_type=memory_type, limit=limit)
        )

    def forget(self, record_id: str) -> bool:
        if not self.enabled or self.vector is None:
            return False
        return self.vector.forget(record_id)

    def optimize(self, force: bool = True) -> list[str]:
        if self.optimizer is None:
            return []
        return self.optimizer.maybe_optimize(force=force)

    def _record_heuristic_memories(
        self,
        user_prompt: str,
        assistant_answer: str,
    ) -> list[str]:
        if self.markdown is None or self.sqlite is None or self.vector is None:
            return []
        written = []
        for item in extract_memory_items(user_prompt, assistant_answer):
            path = self.markdown.write_item(item)
            written.append(path.stem)
            self.sqlite.record_memory_event(self.session_id, path.stem, "extracted")
            self.vector.remember(
                content=item.body,
                memory_type=item.type,
                summary=item.description,
                source_ref=(f"legacy-item:{path.stem}",),
            )
        return written

    def _migrate_legacy_items(self) -> None:
        if self.markdown is None or self.sqlite is None or self.vector is None:
            return
        if self.sqlite.get_state("migration:legacy_items") == "done":
            return
        for item in self.markdown.list_items():
            self.vector.remember(
                content=item.body,
                memory_type=item.type,
                summary=item.description,
                source_ref=(f"legacy-item:{item.name}",),
            )
        self.sqlite.set_state("migration:legacy_items", "done")
