from __future__ import annotations

import json
from copy import deepcopy

from drift_agent.agent import AgentTurnLoop
from drift_agent.agent.phases import TURN_PHASES
from drift_agent.loop import AgentStatus, StepResult
from drift_agent.memory import MemoryContext
from drift_agent.runtime.events import RuntimeEvent, RuntimeEventType
from drift_agent.tools import ToolRegistry
from drift_agent.tools.base import ToolCallResult, ToolSpec


class FakeClient:
    def __init__(self, *messages):
        self.messages = list(messages)
        self.requests = []

    def chat(self, messages, tools):
        self.requests.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        return self.messages.pop(0)

    def stream_chat(self, messages, tools):
        self.requests.append({"messages": deepcopy(messages), "tools": deepcopy(tools)})
        yield from ()


def test_agent_turn_loop_runs_phases_in_order() -> None:
    loop = AgentTurnLoop(
        client=FakeClient({"content": "ok"}),
        tools=ToolRegistry(),
    )

    result, context = loop.run_turn("hello")
    started = [
        event.payload["phase"]
        for event in context.events
        if event.type is RuntimeEventType.PHASE_STARTED
    ]
    finished = [
        event.payload["phase"]
        for event in context.events
        if event.type is RuntimeEventType.PHASE_FINISHED
    ]

    assert result.status is AgentStatus.SUCCESS
    assert result.output == "ok"
    assert started == [phase.value for phase in TURN_PHASES]
    assert finished == [phase.value for phase in TURN_PHASES]


def test_agent_turn_loop_loads_and_records_memory() -> None:
    class FakeMemoryManager:
        def __init__(self):
            self.recorded = None

        def load_prompt_context(self, task):
            assert task == "remember this"
            return MemoryContext(index="project memory", sources=["MEMORY.md index"])

        def record_turn(self, **kwargs):
            self.recorded = kwargs
            return ["preference"]

    memory = FakeMemoryManager()
    client = FakeClient({"content": "done"})
    loop = AgentTurnLoop(
        client=client,
        tools=ToolRegistry(),
        memory_manager=memory,
        show_memory=True,
    )

    result, _context = loop.run_turn("remember this")

    assert result.status is AgentStatus.SUCCESS
    assert "MEMORY.md index" in result.observation
    assert "<memory_index>" in client.requests[0]["messages"][0]["content"]
    assert memory.recorded["user_prompt"] == "remember this"
    assert memory.recorded["assistant_answer"] == "done"


def test_agent_turn_loop_dispatches_tool_and_continues_reasoning() -> None:
    class FakeProvider:
        namespace = "workspace"

        def list_tools(self):
            return [
                ToolSpec(
                    canonical_id="workspace.read_file",
                    description="Read a file",
                    parameters={"type": "object", "properties": {}},
                    provider="workspace",
                    aliases=("read_file",),
                )
            ]

        def call_tool(self, canonical_id, arguments):
            assert canonical_id == "workspace.read_file"
            assert arguments == {"path": "note.txt"}
            return ToolCallResult(canonical_id, "tool text")

    registry = ToolRegistry()
    registry.register_provider(FakeProvider())
    client = FakeClient(
        {
            "content": "",
            "tool_calls": [
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": "workspace__read_file",
                        "arguments": json.dumps({"path": "note.txt"}),
                    },
                }
            ],
        },
        {"content": "final answer"},
    )
    loop = AgentTurnLoop(client=client, tools=registry)

    result, context = loop.run_turn("read it")

    assert result.status is AgentStatus.SUCCESS
    assert result.output == "final answer"
    assert context.tool_records[0]["name"] == "workspace.read_file"
    assert client.requests[1]["messages"][-1]["role"] == "tool"


def test_agent_turn_loop_streams_model_delta_events() -> None:
    class StreamingClient:
        def chat(self, messages, tools):
            raise AssertionError("stream path should be used")

        def stream_chat(self, messages, tools):
            yield {"choices": [{"delta": {"content": "he"}}]}
            yield {"choices": [{"delta": {"content": "llo"}}]}

    loop = AgentTurnLoop(client=StreamingClient(), tools=ToolRegistry(), stream=True)

    items = list(loop.stream_turn("hello"))
    deltas = [
        item.message
        for item in items
        if isinstance(item, RuntimeEvent) and item.type is RuntimeEventType.MODEL_DELTA
    ]
    result = [item for item in items if isinstance(item, StepResult)][-1]

    assert deltas == ["he", "llo"]
    assert result.output == "hello"
