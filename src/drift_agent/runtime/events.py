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
    PHASE_STARTED = "phase_started"
    PHASE_FINISHED = "phase_finished"
    MODEL_DELTA = "model_delta"
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

    @classmethod
    def phase_started(cls, phase: str) -> "RuntimeEvent":
        return cls(RuntimeEventType.PHASE_STARTED, phase, payload={"phase": phase})

    @classmethod
    def phase_finished(cls, phase: str) -> "RuntimeEvent":
        return cls(RuntimeEventType.PHASE_FINISHED, phase, payload={"phase": phase})

    @classmethod
    def model_delta(cls, text: str) -> "RuntimeEvent":
        return cls(RuntimeEventType.MODEL_DELTA, text, payload={"delta": text})

    @classmethod
    def tool_started(cls, name: str, arguments: object = "") -> "RuntimeEvent":
        return cls(
            RuntimeEventType.TOOL_STARTED,
            name,
            payload={"name": name, "arguments": arguments},
        )

    @classmethod
    def tool_finished(cls, name: str, output: str, error: bool = False) -> "RuntimeEvent":
        return cls(
            RuntimeEventType.TOOL_FINISHED,
            name,
            payload={"name": name, "output": output, "error": error},
        )

    @classmethod
    def memory_loaded(cls, sources: list[str]) -> "RuntimeEvent":
        return cls(
            RuntimeEventType.MEMORY_LOADED,
            ", ".join(sources),
            payload={"sources": sources},
        )
