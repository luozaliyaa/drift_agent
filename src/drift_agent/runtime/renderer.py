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
    _saw_model_delta: bool = False

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
            saw_model_delta = self._saw_model_delta
            self._saw_model_delta = False
            if saw_model_delta:
                print(file=stream)
            print(f"status: {state.status.value}", file=stream)
            if state.final_output and (self.trace or not saw_model_delta):
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

        if event.type is RuntimeEventType.MODEL_DELTA:
            if self.trace:
                print(f"{event.type.value}: {event.message}", file=stream)
            else:
                print(event.message, end="", flush=True, file=stream)
                self._saw_model_delta = True
            return 0

        if event.type is RuntimeEventType.TOOL_STARTED:
            self._finish_stream_line_if_needed(stream)
            name = event.payload.get("name", event.message)
            arguments = event.payload.get("arguments", "")
            print(f"tool: {name} {preview_text(arguments)}", file=stream)
            return 0

        if event.type is RuntimeEventType.TOOL_FINISHED:
            self._finish_stream_line_if_needed(stream)
            name = event.payload.get("name", event.message)
            status = "error" if event.payload.get("error") else "ok"
            output = event.payload.get("output", "")
            print(f"tool result: {name} {status} {preview_text(output)}", file=stream)
            return 0

        if self.trace:
            print(f"{event.type.value}: {event.message}", file=stream)
        return 0

    def _finish_stream_line_if_needed(self, stream: TextIO) -> None:
        if self._saw_model_delta:
            print(file=stream)
            self._saw_model_delta = False


def preview_text(value: object, limit: int = 240) -> str:
    text = " ".join(str(value).split())
    if not text:
        return ""
    if len(text) > limit:
        return text[:limit] + "..."
    return text
