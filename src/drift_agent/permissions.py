"""Permission checks for model-requested tool calls."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class PermissionAction(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionMode(str, Enum):
    ASK = "ask"
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class PermissionDecision:
    action: PermissionAction
    reason: str = ""

    @classmethod
    def allow(cls, reason: str = "") -> "PermissionDecision":
        return cls(PermissionAction.ALLOW, reason)

    @classmethod
    def ask(cls, reason: str) -> "PermissionDecision":
        return cls(PermissionAction.ASK, reason)

    @classmethod
    def deny(cls, reason: str) -> "PermissionDecision":
        return cls(PermissionAction.DENY, reason)


Approver = Callable[[str, dict[str, Any], str], bool]


class PermissionPolicy:
    """Three-gate permission pipeline for tools."""

    def __init__(
        self,
        workdir: str | Path | None = None,
        mode: PermissionMode | str = PermissionMode.ASK,
        approver: Approver | None = None,
    ) -> None:
        self.workdir = Path(workdir or Path.cwd()).resolve()
        self.mode = PermissionMode(mode)
        self.approver = approver or _deny_without_tty

    def check(self, tool_name: str, arguments: dict[str, Any]) -> PermissionDecision:
        hard_deny = self._check_hard_deny(tool_name, arguments)
        if hard_deny:
            return PermissionDecision.deny(hard_deny)

        rule_match = self._check_rules(tool_name, arguments)
        if not rule_match:
            return PermissionDecision.allow()

        if self.mode is PermissionMode.ALLOW:
            return PermissionDecision.allow(rule_match)
        if self.mode is PermissionMode.DENY:
            return PermissionDecision.deny(rule_match)

        approved = self.approver(tool_name, arguments, rule_match)
        if approved:
            return PermissionDecision.allow(rule_match)
        return PermissionDecision.deny(rule_match)

    def _check_hard_deny(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        if tool_name == "bash":
            command = str(arguments.get("command", "")).lower()
            for pattern in HARD_DENY_COMMAND_PATTERNS:
                if pattern in command:
                    return f"Blocked hard-deny command pattern: {pattern}"

        if tool_name in {"read_file", "write_file", "edit_file"}:
            path = str(arguments.get("path", ""))
            try:
                candidate = (self.workdir / path).resolve()
            except OSError as exc:
                return f"Invalid path: {exc}"
            if not candidate.is_relative_to(self.workdir):
                return f"Path escapes workspace: {path}"
        return None

    def _check_rules(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        if tool_name in {"write_file", "edit_file"}:
            return f"{tool_name} modifies workspace files"

        if tool_name == "bash":
            command = str(arguments.get("command", "")).lower()
            for pattern in ASK_COMMAND_PATTERNS:
                if pattern == ">":
                    if _has_output_redirect(command):
                        return f"Potentially destructive shell command: {pattern}"
                    continue
                if pattern in command:
                    return f"Potentially destructive shell command: {pattern}"
        return None


def prompt_approver(tool_name: str, arguments: dict[str, Any], reason: str) -> bool:
    print()
    print(f"Permission required: {reason}")
    print(f"Tool: {tool_name}")
    print(f"Arguments: {arguments}")
    choice = input("Allow? [y/N] ").strip().lower()
    return choice in {"y", "yes"}


def _deny_without_tty(tool_name: str, arguments: dict[str, Any], reason: str) -> bool:
    return False


def _has_output_redirect(command: str) -> bool:
    for match in re.finditer(r"[0-9]*>{1,2}", command):
        end = match.end()
        if command[end : end + 1] == "&" and command[end + 1 : end + 2].isdigit():
            continue
        return True
    return False


HARD_DENY_COMMAND_PATTERNS = [
    "rm -rf /",
    "sudo",
    "shutdown",
    "reboot",
    "mkfs",
    "dd if=",
    "> /dev/sda",
    "format c:",
]

ASK_COMMAND_PATTERNS = [
    "rm ",
    "del ",
    "erase ",
    "move ",
    "mv ",
    "chmod ",
    "chown ",
    "remove-item",
    "set-content",
    "new-item",
    "out-file",
    ">",
]
