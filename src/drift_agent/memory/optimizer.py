"""Periodic optimizer for compact Markdown memory files."""

from __future__ import annotations

from drift_agent.memory.llm import MemoryLLM
from drift_agent.memory.markdown_store import MarkdownMemoryStore
from drift_agent.memory.sqlite_store import SQLiteContextStore


class MemoryOptimizer:
    def __init__(
        self,
        *,
        markdown: MarkdownMemoryStore,
        sqlite: SQLiteContextStore,
        llm: MemoryLLM | None = None,
        interval_seconds: int = 64800,
    ) -> None:
        self.markdown = markdown
        self.sqlite = sqlite
        self.llm = llm
        self.interval_seconds = interval_seconds

    def maybe_optimize(self, *, force: bool = False) -> list[str]:
        if self.llm is None:
            return []
        pending = self.markdown.read_pending_text()
        if not has_pending_content(pending):
            if force:
                self.sqlite.mark_optimizer_ran()
            return []
        if not force and not self.sqlite.optimizer_due(self.interval_seconds):
            return []

        self.markdown.snapshot_pending()
        try:
            next_self, next_memory = self.llm.optimize_memory(
                self_model=self.markdown.read_self(),
                memory=self.markdown.read_index(),
                pending=pending,
            )
            self.markdown.write_self(next_self)
            self.markdown.write_index(next_memory)
            self.markdown.commit_pending_snapshot()
            self.sqlite.mark_optimizer_ran()
        except Exception:
            self.markdown.rollback_pending_snapshot()
            raise
        return ["SELF.md", "MEMORY.md", "PENDING.md"]


def has_pending_content(pending_text: str) -> bool:
    for line in pending_text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        return True
    return False
