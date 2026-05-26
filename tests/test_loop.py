from __future__ import annotations

import pytest

from drift_agent.loop import AgentLoop, AgentState, AgentStatus, StepResult


def test_loop_initializes_state_from_task() -> None:
    state = AgentLoop().run("draft plan")

    assert state.task == "draft plan"
    assert state.max_steps == 3
    assert state.step_count == 1
    assert state.status is AgentStatus.SUCCESS
    assert state.events[0].kind == "start"


def test_loop_stops_at_max_steps() -> None:
    def keep_running(state: AgentState) -> StepResult:
        return StepResult(action="think", observation=f"step {state.step_count}")

    state = AgentLoop(stepper=keep_running, max_steps=2).run("continue")

    assert state.step_count == 2
    assert state.status is AgentStatus.MAX_STEPS
    assert state.final_output == "Loop stopped after reaching max steps."


def test_loop_success_from_step_result() -> None:
    def succeed(state: AgentState) -> StepResult:
        return StepResult(
            action="finish",
            observation="done",
            status=AgentStatus.SUCCESS,
            output="ok",
        )

    state = AgentLoop(stepper=succeed).run("finish")

    assert state.status is AgentStatus.SUCCESS
    assert state.final_output == "ok"


def test_loop_failure_from_stub() -> None:
    state = AgentLoop().run("please fail")

    assert state.status is AgentStatus.FAILURE
    assert state.final_output == "Loop failed by request."


def test_loop_halt_from_stub() -> None:
    state = AgentLoop().run("please halt")

    assert state.status is AgentStatus.HALTED
    assert state.final_output == "Loop halted by request."


def test_loop_rejects_invalid_max_steps() -> None:
    with pytest.raises(ValueError, match="max_steps"):
        AgentLoop(max_steps=0)
