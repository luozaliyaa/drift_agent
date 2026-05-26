"""Future proactive push scheduler hooks."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class IdlePushScheduler:
    interval_seconds: float
    runtime: object
    enabled: bool = False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    def on_user_activity(self) -> None:
        return None

    def on_agent_busy(self) -> None:
        return None

    def on_agent_idle(self) -> None:
        return None
