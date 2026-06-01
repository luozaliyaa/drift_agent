from __future__ import annotations

import json

from drift_agent.drift.tools import DriftToolSet


def test_message_push_can_only_be_called_once(tmp_path) -> None:
    tools = DriftToolSet(workdir=tmp_path, drift_dir="drift", permission_mode="allow")

    first = tools.dispatch("message_push", {"message": "hello"})
    second = tools.dispatch("message_push", {"message": "again"})

    assert first.error is False
    assert second.error is True
    assert "already used" in second.output


def test_after_message_push_only_write_edit_or_finish_allowed(tmp_path) -> None:
    tools = DriftToolSet(workdir=tmp_path, drift_dir="drift", permission_mode="allow")

    tools.dispatch("message_push", {"message": "hello"})
    denied = tools.dispatch("web__fetch", {"url": "https://example.com"})

    assert denied.error is True
    assert "after message_push" in denied.output


def test_finish_drift_validates_message_result(tmp_path) -> None:
    tools = DriftToolSet(workdir=tmp_path, drift_dir="drift", permission_mode="allow")

    mismatch = tools.dispatch(
        "finish_drift",
        {"message_result": "sent", "skill": "audit", "one_line": "audit: done"},
    )
    tools.dispatch("message_push", {"message": "hello"})
    finished = tools.dispatch(
        "finish_drift",
        {"message_result": "sent", "skill": "audit", "one_line": "audit: sent"},
    )

    assert mismatch.error is True
    assert "must be silent" in mismatch.output
    assert finished.error is False
    assert tools.finished is True
    assert tools.finish_payload["skill"] == "audit"


def test_drift_writes_are_restricted_to_drift_directory(tmp_path) -> None:
    tools = DriftToolSet(workdir=tmp_path, drift_dir="drift", permission_mode="allow")

    outside = tools.dispatch("write_file", {"path": "notes.txt", "content": "no"})
    inside = tools.dispatch("write_file", {"path": "drift/notes.txt", "content": "yes"})

    assert outside.error is True
    assert "restricted" in outside.output
    assert inside.error is False
    assert (tmp_path / "drift" / "notes.txt").read_text(encoding="utf-8") == "yes"


def test_fetch_and_search_messages_use_memory_store(tmp_path) -> None:
    from drift_agent.memory import MemoryManager

    memory = MemoryManager(tmp_path / ".memory", session_id="default")
    memory.record_turn("hello world", "assistant answer", "success")
    tools = DriftToolSet(
        workdir=tmp_path,
        drift_dir="drift",
        permission_mode="allow",
        memory_manager=memory,
    )

    fetched = tools.dispatch("fetch_messages", {"limit": 3})
    searched = tools.dispatch("search_messages", {"query": "world", "limit": 3})

    assert json.loads(fetched.output)[0]["user"] == "hello world"
    assert json.loads(searched.output)[0]["assistant"] == "assistant answer"
