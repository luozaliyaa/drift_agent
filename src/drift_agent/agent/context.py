"""Mutable state for one six-phase agent turn."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from drift_agent.loop import AgentStatus, StepResult
from drift_agent.memory import MemoryContext
from drift_agent.runtime.events import RuntimeEvent


@dataclass
class TurnContext:
    user_message: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    tool_schemas: list[dict[str, Any]] = field(default_factory=list)
    visible_tool_names: set[str] | None = None
    memory_context: MemoryContext = field(default_factory=MemoryContext)
    tool_trace: list[str] = field(default_factory=list)
    tool_records: list[dict[str, object]] = field(default_factory=list)
    memory_writes: list[str] = field(default_factory=list)
    final_answer: str = ""
    status: AgentStatus = AgentStatus.RUNNING
    error_message: str = ""
    events: list[RuntimeEvent] = field(default_factory=list)
    streamed_text: bool = False

    def add_event(self, event: RuntimeEvent) -> RuntimeEvent:
        self.events.append(event)
        return event

    def to_step_result(self, show_memory: bool = False) -> StepResult:
        if self.status is AgentStatus.SUCCESS:
            observation = "DeepSeek returned a final answer."
        else:
            observation = self.error_message or "Agent turn failed."

        if show_memory and self.memory_context.sources:
            observation += "\nMemory:\n" + self.memory_context.describe_sources()
        if self.memory_writes:
            observation += "\nMemory writes:\n" + "\n".join(
                f"- {name}" for name in self.memory_writes
            )
        if self.tool_trace:
            observation += "\nTools:\n" + "\n".join(self.tool_trace)

        return StepResult(
            action="six-phase-turn",
            observation=observation,
            status=self.status,
            output=self.final_answer or self.error_message or None,
        )
