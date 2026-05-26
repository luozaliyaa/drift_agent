# Add Tool Permissions

## What

Add an s03-style permission layer before model-requested tools execute.

## Why

The agent can now call local tools that read, write, edit files, and run shell commands. Before the tool surface grows further, the project needs an explicit permission boundary so risky operations are denied or confirmed by the user instead of executing silently.

## Scope

- Add a permission policy with hard-deny, rule-matching, and user-approval gates.
- Gate all tool dispatch through the permission policy.
- Require confirmation for file writes, file edits, and potentially destructive shell commands.
- Add CLI options for permission behavior.
- Add tests for allowed, denied, and approval-required tool calls.

## Non-goals

- Persistent permission grants.
- Fine-grained project policy files.
- Sandboxed process isolation.
- Full command parser for every shell dialect.
