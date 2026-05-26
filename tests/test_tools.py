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


def test_workspace_tools_block_escaping_paths(tmp_path) -> None:
    tools = WorkspaceTools(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    output = tools.dispatch_json("read_file", {"path": "../outside.txt"})

    assert "Path escapes workspace" in output


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
