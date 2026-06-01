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


def test_workspace_tools_ask_mode_allows_write_without_prompt(tmp_path) -> None:
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
    assert approvals == []


def test_workspace_tools_ask_mode_denies_delete(tmp_path) -> None:
    note = tmp_path / "notes.txt"
    note.write_text("hello", encoding="utf-8")
    policy = PermissionPolicy(tmp_path, mode="ask", approver=lambda *args: False)
    tools = WorkspaceTools(tmp_path, permission_policy=policy)

    output = tools.dispatch_json("delete_file", {"path": "notes.txt"})

    assert output.startswith("Permission denied:")
    assert note.exists()


def test_workspace_tools_deny_mode_allows_edit(tmp_path) -> None:
    note = tmp_path / "notes.txt"
    note.write_text("hello", encoding="utf-8")
    policy = PermissionPolicy(tmp_path, mode="deny")
    tools = WorkspaceTools(tmp_path, permission_policy=policy)

    output = tools.dispatch_json(
        "edit_file",
        {"path": "notes.txt", "old_text": "hello", "new_text": "bye"},
    )

    assert output == "Edited notes.txt"
    assert note.read_text(encoding="utf-8") == "bye"


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


def test_permission_policy_allows_output_redirect_without_prompt(tmp_path) -> None:
    policy = PermissionPolicy(tmp_path, mode="ask", approver=lambda *args: False)

    decision = policy.check("bash", {"command": "echo hello > note.txt"})

    assert decision.action is PermissionAction.ALLOW


def test_permission_policy_asks_for_shell_delete(tmp_path) -> None:
    policy = PermissionPolicy(tmp_path, mode="ask", approver=lambda *args: False)

    decision = policy.check("bash", {"command": "rm -rf notes.txt"})

    assert decision.action is PermissionAction.DENY
    assert "deletes local files" in decision.reason


def test_permission_policy_allows_delete_under_configured_dir(tmp_path) -> None:
    policy = PermissionPolicy(
        tmp_path,
        mode="ask",
        approver=lambda *args: False,
        allow_delete_without_ask_dirs=["tmp"],
    )

    tool_decision = policy.check("delete_file", {"path": "tmp/cache.txt"})
    shell_decision = policy.check("bash", {"command": "Remove-Item -LiteralPath tmp/cache.txt"})

    assert tool_decision.action is PermissionAction.ALLOW
    assert shell_decision.action is PermissionAction.ALLOW
