from __future__ import annotations

from drift_agent.permissions import (
    PermissionAction,
    PermissionMode,
    PermissionPolicy,
)
from drift_agent.tools import WorkspaceTools


def test_permission_policy_allows_read_tools(tmp_path) -> None:
    policy = PermissionPolicy(tmp_path)

    decision = policy.check("read_file", {"path": "README.md"})

    assert decision.action is PermissionAction.ALLOW


def test_permission_policy_hard_denies_dangerous_bash(tmp_path) -> None:
    policy = PermissionPolicy(tmp_path, mode=PermissionMode.ALLOW)

    decision = policy.check("bash", {"command": "sudo shutdown now"})

    assert decision.action is PermissionAction.DENY
    assert "sudo" in decision.reason


def test_workspace_tools_ask_mode_approves_write(tmp_path) -> None:
    approvals = []

    def approve(tool_name, arguments, reason):
        approvals.append((tool_name, arguments, reason))
        return True

    policy = PermissionPolicy(tmp_path, mode="ask", approver=approve)
    tools = WorkspaceTools(tmp_path, permission_policy=policy)

    output = tools.dispatch_json(
        "write_file",
        {"path": "notes.txt", "content": "hello"},
    )

    assert output == "Wrote 5 bytes to notes.txt"
    assert (tmp_path / "notes.txt").read_text(encoding="utf-8") == "hello"
    assert approvals[0][0] == "write_file"


def test_workspace_tools_ask_mode_denies_write(tmp_path) -> None:
    policy = PermissionPolicy(tmp_path, mode="ask", approver=lambda *args: False)
    tools = WorkspaceTools(tmp_path, permission_policy=policy)

    output = tools.dispatch_json(
        "write_file",
        {"path": "notes.txt", "content": "hello"},
    )

    assert output.startswith("Permission denied:")
    assert not (tmp_path / "notes.txt").exists()


def test_workspace_tools_deny_mode_denies_edit(tmp_path) -> None:
    note = tmp_path / "notes.txt"
    note.write_text("hello", encoding="utf-8")
    policy = PermissionPolicy(tmp_path, mode="deny")
    tools = WorkspaceTools(tmp_path, permission_policy=policy)

    output = tools.dispatch_json(
        "edit_file",
        {"path": "notes.txt", "old_text": "hello", "new_text": "bye"},
    )

    assert output.startswith("Permission denied:")
    assert note.read_text(encoding="utf-8") == "hello"


def test_workspace_tools_allow_mode_allows_edit(tmp_path) -> None:
    note = tmp_path / "notes.txt"
    note.write_text("hello", encoding="utf-8")
    policy = PermissionPolicy(tmp_path, mode="allow")
    tools = WorkspaceTools(tmp_path, permission_policy=policy)

    output = tools.dispatch_json(
        "edit_file",
        {"path": "notes.txt", "old_text": "hello", "new_text": "bye"},
    )

    assert output == "Edited notes.txt"
    assert note.read_text(encoding="utf-8") == "bye"


def test_workspace_tools_hard_deny_wins_over_allow_mode(tmp_path) -> None:
    policy = PermissionPolicy(tmp_path, mode="allow")
    tools = WorkspaceTools(tmp_path, permission_policy=policy)

    output = tools.dispatch_json("bash", {"command": "sudo shutdown now"})

    assert output.startswith("Permission denied:")


def test_permission_policy_allows_stderr_merge_without_prompt(tmp_path) -> None:
    approvals = []

    def approve(tool_name, arguments, reason):
        approvals.append((tool_name, arguments, reason))
        return False

    policy = PermissionPolicy(tmp_path, mode="ask", approver=approve)

    decision = policy.check("bash", {"command": "curl example.test 2>&1"})

    assert decision.action is PermissionAction.ALLOW
    assert approvals == []


def test_permission_policy_still_asks_for_file_redirect(tmp_path) -> None:
    policy = PermissionPolicy(tmp_path, mode="ask", approver=lambda *args: False)

    decision = policy.check("bash", {"command": "echo hello > note.txt"})

    assert decision.action is PermissionAction.DENY
    assert ">" in decision.reason
