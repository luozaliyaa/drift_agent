"""Business event bus for post-turn workers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class TurnCommitted:
    session_id: str
    user_prompt: str
    assistant_answer: str
    status: str
    tool_calls: list[dict[str, object]] = field(default_factory=list)
    memory_writes: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())


EventHandler = Callable[[Any], None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type[Any], list[EventHandler]] = {}
        self.errors: list[str] = []

    def on(self, event_type: type[Any], handler: EventHandler) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    def emit(self, event: Any) -> None:
        for event_type, handlers in self._handlers.items():
            if not isinstance(event, event_type):
                continue
            for handler in list(handlers):
                try:
                    handler(event)
                except Exception as exc:
                    self.errors.append(f"{handler_name(handler)} failed: {exc}")


def handler_name(handler: EventHandler) -> str:
    return getattr(handler, "__name__", handler.__class__.__name__)
