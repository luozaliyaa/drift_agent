from __future__ import annotations

import subprocess

from drift_agent.permissions import PermissionPolicy
from drift_agent.tools import WorkspaceTools


def test_workspace_tools_read_write_edit_and_glob(tmp_path) -> None:
    tools = WorkspaceTools(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    assert tools.dispatch_json(
        "write_file",
        {"path": "notes/plan.txt", "content": "first"},
    ) == "Wrote 5 bytes to notes/plan.txt"
    assert tools.dispatch_json("read_file", {"path": "notes/plan.txt"}) == "first"
    assert tools.dispatch_json(
        "edit_file",
        {"path": "notes/plan.txt", "old_text": "first", "new_text": "second"},
    ) == "Edited notes/plan.txt"
    assert tools.dispatch_json("glob", {"pattern": "**/*.txt"}) == "notes\\plan.txt" or (
        tools.dispatch_json("glob", {"pattern": "**/*.txt"}) == "notes/plan.txt"
    )


def test_workspace_common_file_tools(tmp_path) -> None:
    tools = WorkspaceTools(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    assert tools.dispatch_json("make_dir", {"path": "notes"}) == "Created directory notes"
    assert tools.dispatch_json(
        "write_file",
        {"path": "notes/plan.txt", "content": "alpha\nbeta\nalpha"},
    ) == "Wrote 16 bytes to notes/plan.txt"
    listing = tools.dispatch_json("list_dir", {"path": "notes"})
    info = tools.dispatch_json("file_info", {"path": "notes/plan.txt"})
    matches = tools.dispatch_json(
        "search_text",
        {"query": "alpha", "pattern": "**/*.txt", "limit": 5},
    )
    moved = tools.dispatch_json(
        "move_file",
        {"source": "notes/plan.txt", "destination": "archive/plan.txt"},
    )
    deleted = tools.dispatch_json("delete_file", {"path": "archive/plan.txt"})

    assert "plan.txt" in listing
    assert "type: file" in info
    assert "size:" in info
    assert "notes/plan.txt:1: alpha" in matches or "notes\\plan.txt:1: alpha" in matches
    assert moved == "Moved notes/plan.txt to archive/plan.txt"
    assert deleted == "Deleted archive/plan.txt"
    assert not (tmp_path / "archive" / "plan.txt").exists()


def test_workspace_tools_block_escaping_paths(tmp_path) -> None:
    tools = WorkspaceTools(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    output = tools.dispatch_json("read_file", {"path": "../outside.txt"})

    assert "Path escapes workspace" in output


def test_workspace_common_tools_block_escaping_paths(tmp_path) -> None:
    tools = WorkspaceTools(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    mkdir = tools.dispatch_json("make_dir", {"path": "../outside"})
    move = tools.dispatch_json(
        "move_file",
        {"source": "missing.txt", "destination": "../outside.txt"},
    )
    delete = tools.dispatch_json("delete_file", {"path": "../outside.txt"})

    assert "Path escapes workspace" in mkdir
    assert "Path escapes workspace" in move
    assert "Path escapes workspace" in delete


def test_workspace_tools_block_dangerous_bash(tmp_path) -> None:
    tools = WorkspaceTools(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    output = tools.dispatch_json("bash", {"command": "sudo shutdown now"})

    assert output.startswith("Permission denied:")


def test_workspace_tools_decodes_bash_output_as_utf8_with_replacement(
    monkeypatch,
    tmp_path,
) -> None:
    captured = {}

    class FakeCompleted:
        stdout = "晴天"
        stderr = "\udcff"

    def fake_run(*args, **kwargs):
        captured.update(kwargs)
        return FakeCompleted()

    monkeypatch.setattr(subprocess, "run", fake_run)
    tools = WorkspaceTools(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    output = tools.dispatch_json("bash", {"command": "weather"})

    assert output == "晴天\udcff"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
