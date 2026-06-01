"""Base tool types and helpers."""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol


MAX_TOOL_OUTPUT_CHARS = 50000


@dataclass(frozen=True)
class ToolSpec:
    canonical_id: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., str] | None = None
    provider: str = ""
    aliases: tuple[str, ...] = ()
    enabled: bool = True
    always_on: bool = True
    risk: str = "read-only"
    search_hint: str = ""
    category: str = ""

    @property
    def encoded_name(self) -> str:
        return encode_tool_name(self.canonical_id)

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.encoded_name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass(frozen=True)
class ToolCallResult:
    canonical_id: str
    output: str
    error: bool = False


class ToolProvider(Protocol):
    namespace: str

    def list_tools(self) -> list[ToolSpec]:
        ...

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        ...


def encode_tool_name(canonical_id: str) -> str:
    return canonical_id.replace(".", "__")


def decode_tool_name(encoded_name: str) -> str:
    return encoded_name.replace("__", ".")


def parse_arguments(raw_arguments: str | dict[str, Any] | None) -> dict[str, Any]:
    if raw_arguments is None:
        return {}
    if isinstance(raw_arguments, dict):
        return raw_arguments
    parsed = json.loads(raw_arguments or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Tool arguments must decode to an object")
    return parsed


def truncate_output(output: str) -> str:
    if len(output) <= MAX_TOOL_OUTPUT_CHARS:
        return output
    return output[:MAX_TOOL_OUTPUT_CHARS] + "\n... (truncated)"
