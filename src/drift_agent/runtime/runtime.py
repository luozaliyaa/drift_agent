"""Async runtime wrapper around the existing synchronous agent loop."""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from drift_agent.loop import AgentLoop, AgentState, StepFunction
from drift_agent.runtime.events import RuntimeEvent


class AsyncAgentRuntime:
    def __init__(
        self,
        stepper: StepFunction,
        max_steps: int = 1,
        loop_factory: Callable[..., AgentLoop] = AgentLoop,
    ) -> None:
        self.stepper = stepper
        self.max_steps = max_steps
        self.loop_factory = loop_factory
        self.events: asyncio.Queue[RuntimeEvent] = asyncio.Queue()
        self._current_task: asyncio.Task[AgentState] | None = None

    @property
    def busy(self) -> bool:
        return self._current_task is not None and not self._current_task.done()

    async def submit(self, message: str) -> asyncio.Task[AgentState]:
        if self.busy:
            raise RuntimeError("Agent is already running")
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

    def _run_sync(self, message: str) -> AgentState:
        loop = self.loop_factory(stepper=self.stepper, max_steps=self.max_steps)
        return loop.run(message)
