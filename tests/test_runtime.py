from __future__ import annotations

import asyncio
import threading

import pytest

from drift_agent.loop import AgentState, AgentStatus, StepResult
from drift_agent.runtime import AsyncAgentRuntime
from drift_agent.runtime.events import RuntimeEvent, RuntimeEventType
from drift_agent.runtime.renderer import TerminalRenderer
from drift_agent.runtime.scheduler import IdlePushScheduler
from drift_agent.proactive.types import ProactiveDecision


def test_async_runtime_emits_started_and_finished_events() -> None:
    asyncio.run(_assert_async_runtime_emits_started_and_finished_events())


async def _assert_async_runtime_emits_started_and_finished_events() -> None:
    def succeed(state: AgentState) -> StepResult:
        return StepResult(
            action="finish",
            observation="done",
            status=AgentStatus.SUCCESS,
            output="ok",
        )

    runtime = AsyncAgentRuntime(stepper=succeed)

    state = await runtime.run_once("hello")
    events = [await runtime.events.get() for _ in range(3)]

    assert state.status is AgentStatus.SUCCESS
    assert [event.type for event in events] == [
        RuntimeEventType.USER_MESSAGE,
        RuntimeEventType.AGENT_STARTED,
        RuntimeEventType.AGENT_FINISHED,
    ]


def test_async_runtime_emits_failed_event() -> None:
    asyncio.run(_assert_async_runtime_emits_failed_event())


async def _assert_async_runtime_emits_failed_event() -> None:
    def fail(state: AgentState) -> StepResult:
        raise RuntimeError("boom")

    runtime = AsyncAgentRuntime(stepper=fail)

    with pytest.raises(RuntimeError, match="boom"):
        await runtime.run_once("hello")
    events = [await runtime.events.get() for _ in range(3)]

    assert events[-1].type is RuntimeEventType.AGENT_FAILED
    assert events[-1].message == "boom"


def test_async_runtime_forwards_streaming_step_events() -> None:
    asyncio.run(_assert_async_runtime_forwards_streaming_step_events())


async def _assert_async_runtime_forwards_streaming_step_events() -> None:
    class StreamingStepper:
        def stream_step(self, state: AgentState):
            yield RuntimeEvent.model_delta("hi")
            yield StepResult(
                action="finish",
                observation="streamed",
                status=AgentStatus.SUCCESS,
                output="hi",
            )

    runtime = AsyncAgentRuntime(stepper=StreamingStepper())

    state = await runtime.run_once("hello")
    events = [await runtime.events.get() for _ in range(4)]

    assert state.status is AgentStatus.SUCCESS
    assert [event.type for event in events] == [
        RuntimeEventType.USER_MESSAGE,
        RuntimeEventType.AGENT_STARTED,
        RuntimeEventType.MODEL_DELTA,
        RuntimeEventType.AGENT_FINISHED,
    ]


def test_async_runtime_cancel_current_emits_cancelled_event() -> None:
    asyncio.run(_assert_async_runtime_cancel_current_emits_cancelled_event())


async def _assert_async_runtime_cancel_current_emits_cancelled_event() -> None:
    started = threading.Event()

    def slow(state: AgentState) -> StepResult:
        started.set()
        import time

        time.sleep(0.2)
        return StepResult(
            action="finish",
            observation="done",
            status=AgentStatus.SUCCESS,
        )

    runtime = AsyncAgentRuntime(stepper=slow)
    task = await runtime.submit("hello")
    await asyncio.to_thread(started.wait)
    await runtime.cancel_current()
    events = []
    while not runtime.events.empty():
        events.append(await runtime.events.get())

    assert task.cancelled()
    assert any(event.type is RuntimeEventType.AGENT_CANCELLED for event in events)


def test_idle_scheduler_emits_system_notice() -> None:
    asyncio.run(_assert_idle_scheduler_emits_system_notice())


async def _assert_idle_scheduler_emits_system_notice() -> None:
    def succeed(state: AgentState) -> StepResult:
        return StepResult(
            action="finish",
            observation="done",
            status=AgentStatus.SUCCESS,
        )

    scheduler = IdlePushScheduler(
        runtime=None,
        tick=lambda: ProactiveDecision("reply", message="time to look"),
        enabled=True,
        interval_seconds=0.01,
    )
    runtime = AsyncAgentRuntime(stepper=succeed, scheduler=scheduler)

    await scheduler.run_once()
    event = await runtime.events.get()

    assert event.type is RuntimeEventType.SYSTEM_NOTICE
    assert event.message == "time to look"


def test_idle_scheduler_skips_while_runtime_busy() -> None:
    asyncio.run(_assert_idle_scheduler_skips_while_runtime_busy())


async def _assert_idle_scheduler_skips_while_runtime_busy() -> None:
    calls = 0

    def tick() -> ProactiveDecision:
        nonlocal calls
        calls += 1
        return ProactiveDecision("reply", message="busy notice")

    def succeed(state: AgentState) -> StepResult:
        return StepResult(
            action="finish",
            observation="done",
            status=AgentStatus.SUCCESS,
        )

    scheduler = IdlePushScheduler(runtime=None, tick=tick, enabled=True)
    runtime = AsyncAgentRuntime(stepper=succeed, scheduler=scheduler)
    scheduler.on_agent_busy()

    await scheduler.run_once()

    assert calls == 0
    assert runtime.events.empty()


def test_async_runtime_notifies_scheduler_of_user_activity() -> None:
    asyncio.run(_assert_async_runtime_notifies_scheduler_of_user_activity())


async def _assert_async_runtime_notifies_scheduler_of_user_activity() -> None:
    class TrackingScheduler:
        runtime = None

        def __init__(self) -> None:
            self.calls = []

        def on_user_activity(self) -> None:
            self.calls.append("user")

        def on_agent_busy(self) -> None:
            self.calls.append("busy")

        def on_agent_idle(self) -> None:
            self.calls.append("idle")

    def succeed(state: AgentState) -> StepResult:
        return StepResult(
            action="finish",
            observation="done",
            status=AgentStatus.SUCCESS,
        )

    scheduler = TrackingScheduler()
    runtime = AsyncAgentRuntime(stepper=succeed, scheduler=scheduler)

    await runtime.run_once("hello")

    assert scheduler.calls == ["user", "busy", "idle"]


def test_renderer_prints_final_answer(capsys) -> None:
    state = AgentState(task="hello", max_steps=1)
    state.status = AgentStatus.SUCCESS
    state.final_output = "ok"

    renderer = TerminalRenderer()
    exit_code = renderer.render(RuntimeEvent.agent_finished(state))

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "final: ok" in captured.out
