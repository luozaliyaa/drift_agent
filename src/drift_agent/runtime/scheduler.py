"""Idle proactive push scheduler."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Awaitable, Callable

from drift_agent.proactive.delivery import TerminalDelivery
from drift_agent.proactive.energy import next_tick_interval
from drift_agent.proactive.types import ProactiveDecision


TickCallable = Callable[[], ProactiveDecision | Awaitable[ProactiveDecision]]


@dataclass
class IdlePushScheduler:
    runtime: object
    tick: TickCallable | None = None
    profile: str = "daily"
    enabled: bool = False
    interval_seconds: float | None = None
    delivery: TerminalDelivery | None = None

    def __post_init__(self) -> None:
        self.delivery = self.delivery or TerminalDelivery()
        self._task: asyncio.Task[None] | None = None
        self._last_user_at: datetime | None = None
        self._busy = False

    async def start(self) -> None:
        if not self.enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def run_once(self) -> None:
        if not self.enabled or self.tick is None or self._is_runtime_busy():
            return
        decision = self.tick()
        if asyncio.iscoroutine(decision):
            decision = await decision
        if self.delivery is None:
            return
        _result, event = self.delivery.deliver(decision)
        if event is not None:
            await self.runtime.events.put(event)  # type: ignore[attr-defined]

    def on_user_activity(self) -> None:
        self._last_user_at = datetime.now(UTC)

    def on_agent_busy(self) -> None:
        self._busy = True

    def on_agent_idle(self) -> None:
        self._busy = False

    async def _run_loop(self) -> None:
        while True:
            await asyncio.sleep(self._next_interval())
            await self.run_once()

    def _next_interval(self) -> float:
        if self.interval_seconds is not None:
            return self.interval_seconds
        return next_tick_interval(
            profile=self.profile,
            last_user_at=self._last_user_at,
        )

    def _is_runtime_busy(self) -> bool:
        return self._busy or bool(getattr(self.runtime, "busy", False))
