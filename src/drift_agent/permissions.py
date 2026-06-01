"""Permission checks for model-requested tool calls."""

from __future__ import annotations

import re
import shlex
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
        allow_delete_without_ask_dirs: list[str | Path] | tuple[str | Path, ...] = (),
    ) -> None:
        self.workdir = Path(workdir or Path.cwd()).resolve()
        self.mode = PermissionMode(mode)
        self.approver = approver or _deny_without_tty
        self.allow_delete_without_ask_dirs = tuple(
            self._resolve_path(path) for path in allow_delete_without_ask_dirs
        )

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

        for key in PATH_ARGUMENTS_BY_TOOL.get(tool_name, ()):
            path = str(arguments.get(key, ""))
            if not path:
                continue
            try:
                candidate = (self.workdir / path).resolve()
            except OSError as exc:
                return f"Invalid path: {exc}"
            if not candidate.is_relative_to(self.workdir):
                return f"Path escapes workspace: {path}"
        return None

    def _check_rules(self, tool_name: str, arguments: dict[str, Any]) -> str | None:
        if tool_name == "delete_file":
            path = str(arguments.get("path") or "")
            if self._delete_path_allowed(path):
                return None
            return f"{tool_name} deletes local files"

        if tool_name == "bash":
            command = str(arguments.get("command", "")).lower()
            delete_paths = local_delete_paths(command)
            if delete_paths is not None and not self._delete_paths_allowed(delete_paths):
                return "Shell command deletes local files"
        return None

    def _resolve_path(self, path: str | Path) -> Path:
        candidate = Path(path)
        if candidate.is_absolute():
            return candidate.resolve()
        return (self.workdir / candidate).resolve()

    def _delete_paths_allowed(self, paths: list[str]) -> bool:
        return bool(paths) and all(self._delete_path_allowed(path) for path in paths)

    def _delete_path_allowed(self, path: str) -> bool:
        if not path:
            return False
        target = self._resolve_delete_target(path)
        return any(target.is_relative_to(allowed) for allowed in self.allow_delete_without_ask_dirs)

    def _resolve_delete_target(self, path: str) -> Path:
        cleaned = strip_quotes(path)
        wildcard_index = min(
            [index for marker in ("*", "?") if (index := cleaned.find(marker)) >= 0],
            default=-1,
        )
        if wildcard_index >= 0:
            cleaned = cleaned[:wildcard_index].rstrip("\\/")
        if not cleaned:
            cleaned = "."
        target = Path(cleaned)
        if not target.is_absolute() and target.parent != Path("."):
            return self._resolve_path(target.parent)
        return self._resolve_path(target)


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


def local_delete_paths(command: str) -> list[str] | None:
    """Return local paths targeted by delete commands, or None when no delete command appears."""

    paths: list[str] = []
    saw_delete = False
    for segment in split_shell_segments(command):
        tokens = shell_tokens(segment)
        index = 0
        while index < len(tokens):
            token = normalize_token(tokens[index])
            if token not in DELETE_COMMANDS:
                index += 1
                continue
            saw_delete = True
            index += 1
            while index < len(tokens):
                current = strip_quotes(tokens[index])
                normalized = normalize_token(current)
                if normalized in SHELL_BOUNDARY_TOKENS:
                    break
                if normalized in DELETE_PATH_OPTIONS:
                    if index + 1 < len(tokens):
                        paths.append(strip_quotes(tokens[index + 1]))
                        index += 2
                        continue
                    break
                if is_delete_option(current) or is_redirect_token(current):
                    index += 1
                    continue
                paths.append(current)
                index += 1
    if not saw_delete:
        return None
    return [path for path in paths if path and not looks_like_nonlocal_delete_target(path)]


def split_shell_segments(command: str) -> list[str]:
    return [segment for segment in re.split(r"\s*(?:&&|\|\||;|\|)\s*", command) if segment]


def shell_tokens(segment: str) -> list[str]:
    try:
        return shlex.split(segment, posix=False)
    except ValueError:
        return segment.split()


def normalize_token(token: str) -> str:
    return strip_quotes(token).lower()


def strip_quotes(value: str) -> str:
    return value.strip().strip("\"'")


def is_delete_option(token: str) -> bool:
    normalized = normalize_token(token)
    return normalized.startswith("-") or normalized.startswith("/")


def is_redirect_token(token: str) -> bool:
    normalized = normalize_token(token)
    return normalized.startswith(">") or bool(re.match(r"^\d*>", normalized))


def looks_like_nonlocal_delete_target(path: str) -> bool:
    lowered = path.lower()
    return lowered.startswith(("http://", "https://", "file://", "nul", "/dev/"))


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

DELETE_COMMANDS = {
    "rm",
    "del",
    "erase",
    "remove-item",
    "ri",
    "rmdir",
    "rd",
}

DELETE_PATH_OPTIONS = {
    "-path",
    "-literalpath",
}

SHELL_BOUNDARY_TOKENS = {
    "&&",
    "||",
    ";",
    "|",
}

PATH_ARGUMENTS_BY_TOOL = {
    "read_file": ("path",),
    "write_file": ("path",),
    "edit_file": ("path",),
    "make_dir": ("path",),
    "move_file": ("source", "destination"),
    "delete_file": ("path",),
    "list_dir": ("path",),
    "file_info": ("path",),
}
