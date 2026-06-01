# Common Workspace Tools Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add common workspace utility tools to Drift Agent's built-in tool registry.

**Architecture:** Extend the existing `WorkspaceToolProvider` rather than adding a second provider. Keep all path checks centralized through `safe_path()` and update `PermissionPolicy` so new mutating tools obey the same ask/deny/allow flow as existing write/edit tools.

**Tech Stack:** Python 3.11, stdlib pathlib/shutil/os, pytest.

---

### Task 1: Add Common Workspace Tools

**Files:**
- Modify: `src/drift_agent/tools/workspace.py`
- Modify: `src/drift_agent/permissions.py`
- Test: `tests/test_tools.py`
- Test: `tests/test_tool_registry.py`

- [ ] **Step 1: Add failing tests for list/search/stat/mkdir/move/delete**

Add assertions that the default workspace tools expose `list_dir`, `file_info`, `search_text`, `make_dir`, `move_file`, and `delete_file`, and that they operate only inside the workspace.

- [ ] **Step 2: Implement the tools in `WorkspaceToolProvider`**

Add `ToolSpec` entries and handlers:
- `workspace.list_dir`
- `workspace.file_info`
- `workspace.search_text`
- `workspace.make_dir`
- `workspace.move_file`
- `workspace.delete_file`

- [ ] **Step 3: Update permission checks**

Treat `make_dir`, `move_file`, and `delete_file` as mutating tools. Hard-deny path escape for every path-like argument on the new tools.

- [ ] **Step 4: Keep Drift write restrictions aligned**

When Drift has already used `message_push`, allow only `write_file`, `edit_file`, `make_dir`, `move_file`, `delete_file`, and `finish_drift`, and keep mutating paths restricted to the drift directory.

- [ ] **Step 5: Run verification**

Run:

```powershell
& 'C:\Users\86158\AppData\Local\Programs\Python\Python311\python.exe' -m pytest
git diff --check
```
