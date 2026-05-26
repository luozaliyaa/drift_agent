"""Terminal renderer for runtime events."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TextIO

from drift_agent.runtime.events import RuntimeEvent, RuntimeEventType


@dataclass
class TerminalRenderer:
    trace: bool = False
    stdout: TextIO | None = None

    async def render_until_done(self, events: asyncio.Queue[RuntimeEvent]) -> int:
        exit_code = 1
        while True:
            event = await events.get()
            exit_code = self.render(event)
            if event.type in {
                RuntimeEventType.AGENT_FINISHED,
                RuntimeEventType.AGENT_FAILED,
                RuntimeEventType.AGENT_CANCELLED,
            }:
                return exit_code

    def render(self, event: RuntimeEvent) -> int:
        stream = self.stdout
        if stream is None:
            import sys

            stream = sys.stdout

        if event.type is RuntimeEventType.AGENT_STARTED:
            if self.trace:
                print(f"started: {event.message}", file=stream)
            return 0

        if event.type is RuntimeEventType.AGENT_FINISHED and event.state is not None:
            state = event.state
            print(f"status: {state.status.value}", file=stream)
            if state.final_output:
                print(f"final: {state.final_output}", file=stream)
            if self.trace:
                print("trace:", file=stream)
                for agent_event in state.events:
                    print(
                        f"- step {agent_event.step}: "
                        f"{agent_event.kind}: {agent_event.message}",
                        file=stream,
                    )
            return 0 if state.status.is_success else 1

        if event.type is RuntimeEventType.AGENT_FAILED:
            print(f"error: {event.message}", file=stream)
            return 1

        if event.type is RuntimeEventType.AGENT_CANCELLED:
            print(event.message, file=stream)
            return 130

        if event.type is RuntimeEventType.SYSTEM_NOTICE:
            print(event.message, file=stream)
            return 0

        if self.trace:
            print(f"{event.type.value}: {event.message}", file=stream)
        return 0
