"""Runtime events emitted by the async CLI loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from drift_agent.loop import AgentState


class RuntimeEventType(str, Enum):
    USER_MESSAGE = "user_message"
    AGENT_STARTED = "agent_started"
    AGENT_FINISHED = "agent_finished"
    AGENT_FAILED = "agent_failed"
    AGENT_CANCELLED = "agent_cancelled"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    PERMISSION_REQUIRED = "permission_required"
    MEMORY_LOADED = "memory_loaded"
    SYSTEM_NOTICE = "system_notice"


@dataclass(frozen=True)
class RuntimeEvent:
    type: RuntimeEventType
    message: str = ""
    state: AgentState | None = None
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def user_message(cls, text: str) -> "RuntimeEvent":
        return cls(RuntimeEventType.USER_MESSAGE, text)

    @classmethod
    def agent_started(cls, text: str) -> "RuntimeEvent":
        return cls(RuntimeEventType.AGENT_STARTED, text)

    @classmethod
    def agent_finished(cls, state: AgentState) -> "RuntimeEvent":
        return cls(RuntimeEventType.AGENT_FINISHED, state=state)

    @classmethod
    def agent_failed(cls, message: str) -> "RuntimeEvent":
        return cls(RuntimeEventType.AGENT_FAILED, message)

    @classmethod
    def agent_cancelled(cls) -> "RuntimeEvent":
        return cls(RuntimeEventType.AGENT_CANCELLED, "Agent run cancelled.")
