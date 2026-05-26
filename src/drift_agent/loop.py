"""Deterministic s01 agent loop."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum


class AgentStatus(str, Enum):
    """Lifecycle status for an agent loop run."""

    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    HALTED = "halted"
    MAX_STEPS = "max_steps"

    @property
    def is_terminal(self) -> bool:
        return self is not AgentStatus.RUNNING

    @property
    def is_success(self) -> bool:
        return self is AgentStatus.SUCCESS


@dataclass(frozen=True)
class AgentEvent:
    """A visible event in the loop trace."""

    step: int
    kind: str
    message: str


@dataclass(frozen=True)
class StepResult:
    """Result produced by one loop iteration."""

    action: str
    observation: str
    status: AgentStatus = AgentStatus.RUNNING
    output: str | None = None


@dataclass
class AgentState:
    """Mutable state for one agent loop run."""

    task: str
    max_steps: int
    step_count: int = 0
    status: AgentStatus = AgentStatus.RUNNING
    events: list[AgentEvent] = field(default_factory=list)
    final_output: str | None = None

    def record(self, kind: str, message: str) -> None:
        self.events.append(AgentEvent(step=self.step_count, kind=kind, message=message))


StepFunction = Callable[[AgentState], StepResult]


class StubPlanner:
    """Deterministic stepper used until real model and tool adapters exist."""

    def __call__(self, state: AgentState) -> StepResult:
        normalized_task = state.task.strip().lower()
        if not normalized_task:
            return StepResult(
                action="validate-task",
                observation="No task was provided.",
                status=AgentStatus.FAILURE,
                output="Task cannot be empty.",
            )
        if "halt" in normalized_task:
            return StepResult(
                action="halt",
                observation="Task requested an explicit halt.",
                status=AgentStatus.HALTED,
                output="Loop halted by request.",
            )
        if "fail" in normalized_task:
            return StepResult(
                action="fail",
                observation="Task requested a deterministic failure.",
                status=AgentStatus.FAILURE,
                output="Loop failed by request.",
            )
        return StepResult(
            action="complete-stub-task",
            observation=f"Stub completed task: {state.task}",
            status=AgentStatus.SUCCESS,
            output=f"Completed: {state.task}",
        )


class AgentLoop:
    """Owns the initial agent loop lifecycle."""

    def __init__(self, stepper: StepFunction | None = None, max_steps: int = 3) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self._stepper = stepper or StubPlanner()
        self._max_steps = max_steps

    def run(self, task: str) -> AgentState:
        state = AgentState(task=task, max_steps=self._max_steps)
        state.record("start", f"Starting task: {task}")

        while not state.status.is_terminal:
            if state.step_count >= state.max_steps:
                state.status = AgentStatus.MAX_STEPS
                state.final_output = "Loop stopped after reaching max steps."
                state.record("stop", state.final_output)
                break

            state.step_count += 1
            result = self._stepper(state)
            self._apply_step_result(state, result)

        state.record("final", f"Finished with status: {state.status.value}")
        return state

    @staticmethod
    def _apply_step_result(state: AgentState, result: StepResult) -> None:
        state.record("action", result.action)
        state.record("observation", result.observation)

        if result.output is not None:
            state.final_output = result.output
        state.status = result.status
