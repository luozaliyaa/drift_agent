"""Async runtime wrapper around the existing synchronous agent loop."""

from __future__ import annotations

import asyncio
import queue
from collections.abc import Callable
from typing import Any

from drift_agent.loop import AgentLoop, AgentState, AgentStatus, StepFunction, StepResult
from drift_agent.runtime.events import RuntimeEvent
from drift_agent.runtime.scheduler import IdlePushScheduler

_SENTINEL = object()


class AsyncAgentRuntime:
    def __init__(
        self,
        stepper: StepFunction,
        max_steps: int = 1,
        loop_factory: Callable[..., AgentLoop] = AgentLoop,
        scheduler: IdlePushScheduler | None = None,
    ) -> None:
        self.stepper = stepper
        self.max_steps = max_steps
        self.loop_factory = loop_factory
        self.events: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._current_task: asyncio.Task[AgentState] | None = None
        self.scheduler = scheduler
        if self.scheduler is not None:
            self.scheduler.runtime = self

    @property
    def busy(self) -> bool:
        return self._current_task is not None and not self._current_task.done()

    async def submit(self, message: str) -> asyncio.Task[AgentState]:
        if self.busy:
            raise RuntimeError("Agent is already running")
        if self.scheduler is not None:
            self.scheduler.on_user_activity()
            self.scheduler.on_agent_busy()
        await self.events.put(RuntimeEvent.user_message(message))
        await self.events.put(RuntimeEvent.agent_started(message))
        task = asyncio.create_task(self._run(message))
        self._current_task = task
        return task

    async def run_once(self, message: str) -> AgentState:
        task = await self.submit(message)
        return await task

    async def cancel_current(self) -> None:
        if not self.busy or self._current_task is None:
            return
        self._current_task.cancel()
        try:
            await self._current_task
        except asyncio.CancelledError:
            pass

    async def _run(self, message: str) -> AgentState:
        try:
            if callable(getattr(self.stepper, "stream_step", None)):
                state = await self._run_streaming(message)
            else:
                state = await asyncio.to_thread(self._run_sync, message)
        except asyncio.CancelledError:
            await self.events.put(RuntimeEvent.agent_cancelled())
            raise
        except Exception as exc:
            await self.events.put(RuntimeEvent.agent_failed(str(exc)))
            raise
        else:
            await self.events.put(RuntimeEvent.agent_finished(state))
            return state
        finally:
            self._current_task = None
            if self.scheduler is not None:
                self.scheduler.on_agent_idle()

    def _run_sync(self, message: str) -> AgentState:
        loop = self.loop_factory(stepper=self.stepper, max_steps=self.max_steps)
        return loop.run(message)

    async def _run_streaming(self, message: str) -> AgentState:
        thread_items: queue.Queue[Any] = queue.Queue()

        def worker() -> None:
            state = AgentState(task=message, max_steps=self.max_steps)
            state.record("start", f"Starting task: {message}")
            try:
                if state.step_count >= state.max_steps:
                    state.status = AgentStatus.MAX_STEPS
                    state.final_output = "Loop stopped after reaching max steps."
                    state.record("stop", state.final_output)
                else:
                    state.step_count += 1
                    for item in self.stepper.stream_step(state):  # type: ignore[attr-defined]
                        thread_items.put(item)
                        if isinstance(item, StepResult):
                            AgentLoop._apply_step_result(state, item)
                            break
                    if not state.status.is_terminal:
                        state.status = AgentStatus.FAILURE
                        state.final_output = "Agent stream ended without a result."
                        state.record("stop", state.final_output)
                state.record("final", f"Finished with status: {state.status.value}")
                thread_items.put(state)
            except BaseException as exc:
                thread_items.put(exc)
            finally:
                thread_items.put(_SENTINEL)

        worker_task = asyncio.create_task(asyncio.to_thread(worker))
        final_state: AgentState | None = None
        try:
            while True:
                item = await asyncio.to_thread(thread_items.get)
                if item is _SENTINEL:
                    break
                if isinstance(item, RuntimeEvent):
                    await self.events.put(item)
                elif isinstance(item, AgentState):
                    final_state = item
                elif isinstance(item, BaseException):
                    raise item
            await worker_task
        except BaseException:
            worker_task.cancel()
            raise

        if final_state is None:
            raise RuntimeError("Agent stream ended without final state")
        return final_state
