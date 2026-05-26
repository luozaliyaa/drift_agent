from __future__ import annotations

from drift_agent.memory import MemoryManager
from drift_agent.memory.markdown_store import MarkdownMemoryStore
from drift_agent.memory.retrieval import select_relevant_memories
from drift_agent.memory.sqlite_store import SQLiteContextStore
from drift_agent.memory.types import MemoryItem, ToolCallRecord, TurnRecord


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


def test_memory_manager_can_be_disabled(tmp_path) -> None:
    manager = MemoryManager(
        memory_dir=tmp_path / ".memory",
        session_id="default",
        enabled=False,
    )

    assert manager.load_prompt_context("hello").to_prompt() == ""
    assert manager.record_turn("remember this", "ok", "success") == []
    assert not (tmp_path / ".memory").exists()
