from __future__ import annotations

from drift_agent.memory.consolidation import MemoryConsolidator
from drift_agent.memory.llm import parse_consolidation_response
from drift_agent.memory import MemoryManager
from drift_agent.memory.markdown_store import MarkdownMemoryStore
from drift_agent.memory.optimizer import MemoryOptimizer
from drift_agent.memory.retrieval import select_relevant_memories
from drift_agent.memory.sqlite_store import SQLiteContextStore
from drift_agent.memory.types import (
    ConsolidationResult,
    HistoryEntry,
    MemoryItem,
    PendingItem,
    RecentContext,
    RetrievalRequest,
    ToolCallRecord,
    TurnRecord,
)
from drift_agent.memory.vector_store import VectorMemoryStore


def test_markdown_store_writes_item_and_index(tmp_path) -> None:
    store = MarkdownMemoryStore(tmp_path / ".memory")

    path = store.write_item(
        MemoryItem(
            name="user-prefers-tabs",
            type="user",
            description="User prefers tabs",
            body="Use tabs for indentation.",
        )
    )

    assert path.exists()
    assert "user-prefers-tabs" in store.read_index()
    assert store.list_items()[0].body == "Use tabs for indentation."


def test_markdown_store_initializes_akashic_files(tmp_path) -> None:
    store = MarkdownMemoryStore(tmp_path / ".memory")

    assert store.self_path.exists()
    assert store.history_path.exists()
    assert store.pending_path.exists()
    assert store.recent_context_path.exists()
    assert store.journal_dir.exists()


def test_markdown_store_appends_idempotent_history_and_pending(tmp_path) -> None:
    store = MarkdownMemoryStore(tmp_path / ".memory")
    source_ref = ("turn:1", "turn:2")

    first = store.append_history_entries(
        [HistoryEntry(summary="User prefers quiet UI.")],
        source_ref,
    )
    second = store.append_history_entries(
        [HistoryEntry(summary="User prefers quiet UI.")],
        source_ref,
    )
    pending = store.append_pending_items(
        [PendingItem(tag="preference", content="User prefers quiet UI.")],
        source_ref,
    )

    assert first == ["User prefers quiet UI."]
    assert second == []
    assert pending == ["preference:User prefers quiet UI."]
    assert store.read_pending_items()[0].content == "User prefers quiet UI."


def test_recent_context_prompt_excludes_recent_turns(tmp_path) -> None:
    store = MarkdownMemoryStore(tmp_path / ".memory")
    store.write_recent_context(
        RecentContext(
            compression=["Recently discussing memory architecture."],
            ongoing_threads=["Continue optimizer implementation."],
            recent_turns=[("secret user text", "assistant text")],
            until="2026-06-01T00:00:00",
        )
    )

    prompt = store.read_recent_context().to_prompt()

    assert "Recently discussing memory architecture." in prompt
    assert "Continue optimizer implementation." in prompt
    assert "secret user text" not in prompt


def test_retrieval_selects_relevant_memories() -> None:
    items = [
        MemoryItem(
            name="tabs",
            type="user",
            description="User prefers tabs",
            body="Use tabs for indentation.",
        ),
        MemoryItem(
            name="deploy",
            type="project",
            description="Deployment notes",
            body="Use staging first.",
        ),
    ]

    selected = select_relevant_memories("Please format this with tabs", items)

    assert [item.name for item in selected] == ["tabs"]


def test_sqlite_store_records_turn_and_summary(tmp_path) -> None:
    store = SQLiteContextStore(tmp_path / ".memory")

    store.record_turn(
        TurnRecord(
            session_id="default",
            user_prompt="hello",
            assistant_answer="world",
            status="success",
            tool_calls=[
                ToolCallRecord(
                    name="read_file",
                    arguments='{"path":"README.md"}',
                    result_preview="contents",
                )
            ],
        )
    )

    summary, recent = store.load_session_context("default")

    assert "hello" in summary
    assert recent == [("hello", "world")]


def test_sqlite_store_tracks_consolidation_state(tmp_path) -> None:
    store = SQLiteContextStore(tmp_path / ".memory")
    for index in range(3):
        store.record_turn(
            TurnRecord(
                session_id="default",
                user_prompt=f"user {index}",
                assistant_answer=f"assistant {index}",
                status="success",
            )
        )

    turns = store.load_unconsolidated_turns("default", keep_count=1)
    source_ref = tuple(f"turn:{turn['id']}" for turn in turns)
    store.record_consolidation_write(source_ref, "batch")
    store.mark_turns_consolidated("default", [int(turn["id"]) for turn in turns])

    assert [turn["user_prompt"] for turn in turns] == ["user 0", "user 1"]
    assert store.has_consolidation_write(source_ref, "batch")
    assert store.load_unconsolidated_turns("default", keep_count=1) == []


def test_vector_store_remember_retrieve_and_forget(tmp_path) -> None:
    store = VectorMemoryStore(tmp_path / ".memory")
    record = store.remember("User prefers tabs for indentation.", "preference")

    result = store.retrieve(RetrievalRequest(query="tabs indentation"))
    deleted = store.forget(record.id)
    after_delete = store.retrieve(RetrievalRequest(query="tabs indentation"))

    assert result.records[0].id == record.id
    assert deleted is True
    assert after_delete.records == []


def test_parse_consolidation_response_accepts_json_block() -> None:
    result = parse_consolidation_response(
        """```json
        {
          "history_entries": [{"summary": "User chose memory design.", "emotional_weight": 3}],
          "pending_items": [{"tag": "preference", "content": "User prefers compact plans."}],
          "recent_context": {
            "until": "2026-06-01T00:00:00",
            "compression": ["Discussing memory."],
            "ongoing_threads": ["Implement it."]
          }
        }
        ```"""
    )

    assert result.history_entries[0].summary == "User chose memory design."
    assert result.pending_items[0].tag == "preference"
    assert result.recent_context.compression == ["Discussing memory."]


def test_consolidator_writes_markdown_and_vector_records(tmp_path) -> None:
    class FakeLLM:
        def consolidate_turns(self, turns):
            return ConsolidationResult(
                history_entries=[HistoryEntry(summary="User requested Akashic memory.")],
                pending_items=[
                    PendingItem(tag="requested_memory", content="Build Akashic memory.")
                ],
                recent_context=RecentContext(
                    compression=["Working on Akashic memory."],
                    ongoing_threads=["Finish tests."],
                ),
            )

    markdown = MarkdownMemoryStore(tmp_path / ".memory")
    sqlite = SQLiteContextStore(tmp_path / ".memory")
    vector = VectorMemoryStore(tmp_path / ".memory")
    for index in range(3):
        sqlite.record_turn(
            TurnRecord(
                session_id="default",
                user_prompt=f"user {index}",
                assistant_answer=f"assistant {index}",
                status="success",
            )
        )
    consolidator = MemoryConsolidator(
        markdown=markdown,
        sqlite=sqlite,
        vector=vector,
        llm=FakeLLM(),
        keep_count=0,
        consolidation_min=2,
    )

    writes = consolidator.maybe_consolidate("default")
    second = consolidator.maybe_consolidate("default")

    assert "User requested Akashic memory." in writes
    assert second == []
    assert "Build Akashic memory." in markdown.read_pending_text()
    assert vector.retrieve(RetrievalRequest(query="Akashic memory")).records


def test_optimizer_updates_memory_and_clears_pending(tmp_path) -> None:
    class FakeLLM:
        def optimize_memory(self, *, self_model, memory, pending):
            return (
                "# Self\n\n- Optimized self.",
                "# Memory\n\n- User wants Akashic memory.",
            )

    markdown = MarkdownMemoryStore(tmp_path / ".memory")
    sqlite = SQLiteContextStore(tmp_path / ".memory")
    markdown.append_pending_items(
        [PendingItem(tag="requested_memory", content="User wants Akashic memory.")],
        ("turn:1",),
    )
    optimizer = MemoryOptimizer(markdown=markdown, sqlite=sqlite, llm=FakeLLM())

    writes = optimizer.maybe_optimize(force=True)

    assert writes == ["SELF.md", "MEMORY.md", "PENDING.md"]
    assert "Optimized self" in markdown.read_self()
    assert "User wants Akashic memory" in markdown.read_index()
    assert "User wants Akashic memory" not in markdown.read_pending_text()


def test_memory_manager_extracts_explicit_memory(tmp_path) -> None:
    manager = MemoryManager(memory_dir=tmp_path / ".memory", session_id="default")

    written = manager.record_turn(
        user_prompt="Remember that I prefer tabs for indentation.",
        assistant_answer="Got it.",
        status="success",
    )
    context = manager.load_prompt_context("How should I indent Python?")

    assert written
    assert "prefer tabs" in context.index.lower()
    assert context.relevant_items
    assert "tabs" in context.to_prompt().lower()


def test_memory_manager_recall_and_forget(tmp_path) -> None:
    manager = MemoryManager(memory_dir=tmp_path / ".memory", session_id="default")
    record = manager.remember("User prefers compact status updates.", "preference")

    result = manager.recall("compact updates")
    deleted = manager.forget(record.id)

    assert result.records[0].id == record.id
    assert deleted is True
    assert manager.recall("compact updates").records == []


def test_memory_manager_can_be_disabled(tmp_path) -> None:
    manager = MemoryManager(
        memory_dir=tmp_path / ".memory",
        session_id="default",
        enabled=False,
    )

    assert manager.load_prompt_context("hello").to_prompt() == ""
    assert manager.record_turn("remember this", "ok", "success") == []
    assert not (tmp_path / ".memory").exists()
