# Design

## Overview

The permission layer follows the reference s03 pattern:

1. Hard deny: known dangerous operations are always blocked.
2. Rule match: risky but potentially valid operations are flagged.
3. User approval: flagged operations run only when the user approves.

Read-only tools such as `read_file` and `glob` run without prompting. Mutating tools such as `write_file` and `edit_file` require approval by default.

## Components

- `PermissionPolicy`: evaluates a tool name and parsed arguments.
- `PermissionDecision`: returns allow/deny/ask plus a reason.
- `PermissionMode`: controls how approval prompts behave: `ask`, `allow`, or `deny`.
- `WorkspaceTools`: calls the policy before dispatching a tool handler.

## Rules

- Hard deny shell commands containing severe patterns such as `rm -rf /`, `sudo`, `shutdown`, `reboot`, `mkfs`, `dd if=`, and direct disk/device writes.
- Ask before `write_file` and `edit_file`.
- Ask before shell commands that look mutating or destructive, including delete, move, chmod, format, and PowerShell removal commands.
- Deny any file operation that escapes the workspace.

## CLI

Live CLI defaults to `--permission-mode ask`. The user can choose `--permission-mode allow` for trusted local experiments or `--permission-mode deny` to refuse any approval-required operation.

When prompting, the CLI shows the tool, arguments, and reason. `y` or `yes` approves; anything else denies.

## Tests

Tests use injected permission modes and approvers so they do not block on interactive input.
