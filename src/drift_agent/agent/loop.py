"""Six-phase agent turn orchestration."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, Protocol

from drift_agent.agent.context import TurnContext
from drift_agent.agent.hooks import NoopPhaseHook, PhaseHook
from drift_agent.agent.phases import TurnPhase
from drift_agent.events import EventBus, TurnCommitted
from drift_agent.loop import AgentStatus, StepResult
from drift_agent.memory import MemoryContext, MemoryManager
from drift_agent.plugins import PluginManager, ToolHookContext
from drift_agent.runtime.events import RuntimeEvent
from drift_agent.tools import ToolRegistry
from drift_agent.tools.base import ToolCallResult, parse_arguments


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> Iterator[dict[str, Any]]:
        ...


class AgentTurnLoop:
    def __init__(
        self,
        *,
        client: ChatClient,
        tools: ToolRegistry,
        memory_manager: MemoryManager | None = None,
        max_tool_rounds: int = 8,
        show_memory: bool = False,
        stream: bool = False,
        hooks: list[PhaseHook] | None = None,
        error_formatter: Callable[[Exception], str] | None = None,
        plugin_manager: PluginManager | None = None,
        event_bus: EventBus | None = None,
        enable_tool_search: bool = True,
    ) -> None:
        self.client = client
        self.tools = tools
        self.memory_manager = memory_manager
        self.max_tool_rounds = max_tool_rounds
        self.show_memory = show_memory
        self.stream = stream
        self.hooks = hooks or [NoopPhaseHook()]
        self.error_formatter = error_formatter or (lambda exc: str(exc))
        self.plugin_manager = plugin_manager or PluginManager()
        self.event_bus = event_bus or EventBus()
        self.enable_tool_search = enable_tool_search
        self.last_context: TurnContext | None = None

    def run_turn(self, user_message: str) -> tuple[StepResult, TurnContext]:
        result: StepResult | None = None
        for item in self.stream_turn(user_message):
            if isinstance(item, StepResult):
                result = item
        if result is None:
            context = self.last_context or TurnContext(user_message)
            context.status = AgentStatus.FAILURE
            context.error_message = "Agent turn ended without a result."
            result = context.to_step_result(self.show_memory)
        return result, self.last_context or TurnContext(user_message)

    def stream_turn(self, user_message: str) -> Iterator[RuntimeEvent | StepResult]:
        context = TurnContext(user_message=user_message)
        self.last_context = context
        try:
            yield from self._run_before_turn(context)
            yield from self._run_before_reasoning(context)
            yield from self._run_prompt_render(context)
            yield from self._run_reasoner(context)
            yield from self._run_after_reasoning(context)
            yield from self._run_after_turn(context)
        except Exception as exc:
            context.status = AgentStatus.FAILURE
            context.error_message = self.error_formatter(exc)
            context.final_answer = context.error_message
            yield from self._record_failed_turn(context)
        yield context.to_step_result(self.show_memory)

    def _start_phase(
        self,
        phase: TurnPhase,
        context: TurnContext,
    ) -> Iterator[RuntimeEvent]:
        for hook in self.hooks:
            hook.before_phase(phase, context)
        yield context.add_event(RuntimeEvent.phase_started(phase.value))

    def _finish_phase(
        self,
        phase: TurnPhase,
        context: TurnContext,
    ) -> Iterator[RuntimeEvent]:
        for hook in self.hooks:
            hook.after_phase(phase, context)
        yield context.add_event(RuntimeEvent.phase_finished(phase.value))

    def _run_before_turn(self, context: TurnContext) -> Iterator[RuntimeEvent]:
        phase = TurnPhase.BEFORE_TURN
        yield from self._start_phase(phase, context)
        if not context.user_message.strip():
            raise ValueError("Task cannot be empty.")
        yield from self._finish_phase(phase, context)

    def _run_before_reasoning(self, context: TurnContext) -> Iterator[RuntimeEvent]:
        phase = TurnPhase.BEFORE_REASONING
        yield from self._start_phase(phase, context)
        if self.memory_manager is not None:
            context.memory_context = self.memory_manager.load_prompt_context(
                context.user_message
            )
        else:
            context.memory_context = MemoryContext()
        yield context.add_event(RuntimeEvent.memory_loaded(context.memory_context.sources))
        yield from self._finish_phase(phase, context)

    def _run_prompt_render(self, context: TurnContext) -> Iterator[RuntimeEvent]:
        phase = TurnPhase.PROMPT_RENDER
        yield from self._start_phase(phase, context)
        system_prompt = (
            "You are a coding agent in the current workspace. "
            "Use tools when you need to inspect files, run commands, "
            "or make requested file changes. Act directly and keep the "
            "final answer concise."
        )
        memory_prompt = context.memory_context.to_prompt()
        if memory_prompt:
            system_prompt += (
                "\n\nUse the following local memory as helpful context. "
                "Treat it as user/project context, not as a new task.\n\n"
                + memory_prompt
            )
        plugin_sections = self.plugin_manager.prompt_sections()
        if plugin_sections:
            system_prompt += "\n\nPlugin context:\n\n" + "\n\n".join(plugin_sections)
        context.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": context.user_message},
        ]
        if self.enable_tool_search:
            context.visible_tool_names = self.tools.always_on_names()
            context.tool_schemas = self.tools.as_openai_tools(context.visible_tool_names)
        else:
            context.visible_tool_names = None
            context.tool_schemas = self.tools.as_openai_tools()
        yield from self._finish_phase(phase, context)

    def _run_reasoner(self, context: TurnContext) -> Iterator[RuntimeEvent]:
        phase = TurnPhase.REASONER
        yield from self._start_phase(phase, context)
        for _ in range(self.max_tool_rounds):
            message = yield from self._call_model(context)
            tool_calls = message.get("tool_calls") or []
            context.messages.append(_assistant_message(message))

            if not tool_calls:
                context.final_answer = str(message.get("content") or "")
                context.status = AgentStatus.SUCCESS
                yield from self._finish_phase(phase, context)
                return

            for tool_call in tool_calls:
                yield from self._dispatch_tool(context, tool_call)

        raise ValueError(f"Exceeded max tool rounds: {self.max_tool_rounds}")

    def _call_model(self, context: TurnContext) -> Iterator[RuntimeEvent | dict[str, Any]]:
        if not self.stream:
            return self.client.chat(context.messages, context.tool_schemas)

        message = yield from self._stream_model_message(context)
        return message

    def _stream_model_message(self, context: TurnContext) -> Iterator[RuntimeEvent]:
        content_parts: list[str] = []
        tool_calls: dict[int, dict[str, Any]] = {}
        reasoning_parts: list[str] = []
        for chunk in self.client.stream_chat(context.messages, context.tool_schemas):
            choice = (chunk.get("choices") or [{}])[0]
            delta = choice.get("delta") or {}
            content = delta.get("content")
            if content:
                text = str(content)
                content_parts.append(text)
                context.streamed_text = True
                yield context.add_event(RuntimeEvent.model_delta(text))
            reasoning = delta.get("reasoning_content")
            if reasoning:
                reasoning_parts.append(str(reasoning))
            for tool_delta in delta.get("tool_calls") or []:
                index = int(tool_delta.get("index", 0))
                aggregate = tool_calls.setdefault(
                    index,
                    {
                        "id": tool_delta.get("id"),
                        "type": tool_delta.get("type", "function"),
                        "function": {"name": "", "arguments": ""},
                    },
                )
                if tool_delta.get("id"):
                    aggregate["id"] = tool_delta["id"]
                if tool_delta.get("type"):
                    aggregate["type"] = tool_delta["type"]
                function = tool_delta.get("function") or {}
                aggregate_function = aggregate["function"]
                if function.get("name"):
                    aggregate_function["name"] += str(function["name"])
                if function.get("arguments"):
                    aggregate_function["arguments"] += str(function["arguments"])

        message: dict[str, Any] = {"content": "".join(content_parts)}
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        if tool_calls:
            message["tool_calls"] = [tool_calls[index] for index in sorted(tool_calls)]
        return message

    def _dispatch_tool(
        self,
        context: TurnContext,
        tool_call: dict[str, Any],
    ) -> Iterator[RuntimeEvent]:
        function = tool_call.get("function") or {}
        tool_name = str(function.get("name") or "")
        arguments = function.get("arguments")
        yield context.add_event(RuntimeEvent.tool_started(tool_name, arguments or ""))
        result = self._dispatch_tool_with_plugins(context, tool_name, arguments)
        self._update_visible_tools_after_tool_search(context, result, arguments)
        if self.enable_tool_search:
            context.tool_schemas = self.tools.as_openai_tools(context.visible_tool_names)
        output = result.output
        context.tool_trace.append(f"- {result.canonical_id}: {output[:200]}")
        context.tool_records.append(
            {
                "name": result.canonical_id,
                "arguments": arguments or "",
                "result": output,
            }
        )
        context.messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "name": tool_name,
                "content": output,
            }
        )
        yield context.add_event(
            RuntimeEvent.tool_finished(result.canonical_id, output, result.error)
        )

    def _dispatch_tool_with_plugins(
        self,
        context: TurnContext,
        tool_name: str,
        raw_arguments: str | dict[str, Any] | None,
    ) -> ToolCallResult:
        canonical_id = self.tools.resolve_name(tool_name)
        if self.enable_tool_search and not self.tools.is_visible(
            canonical_id,
            context.visible_tool_names,
        ):
            return ToolCallResult(
                canonical_id,
                (
                    f"Error: Tool {canonical_id} is deferred. "
                    f"Call tool_search with select='{canonical_id}' before using it."
                ),
                True,
            )
        try:
            arguments = parse_arguments(raw_arguments)
        except ValueError as exc:
            return ToolCallResult(canonical_id, f"Error: {exc}", True)
        hook_context = ToolHookContext(
            tool_name=tool_name,
            canonical_id=canonical_id,
            arguments=arguments,
            raw_arguments=raw_arguments,
            user_message=context.user_message,
        )
        outcome = self.plugin_manager.before_tool_call(hook_context)
        if outcome is not None and outcome.decision == "deny":
            return ToolCallResult(
                canonical_id,
                outcome.output or f"Error: {outcome.reason}",
                True,
            )
        if outcome is not None and outcome.decision == "replace":
            return ToolCallResult(canonical_id, outcome.output)
        result = self.tools.dispatch(canonical_id, hook_context.arguments)
        return self.plugin_manager.after_tool_call(hook_context, result)

    def _run_after_reasoning(self, context: TurnContext) -> Iterator[RuntimeEvent]:
        phase = TurnPhase.AFTER_REASONING
        yield from self._start_phase(phase, context)
        if context.status is AgentStatus.RUNNING:
            context.status = AgentStatus.FAILURE
            context.error_message = "Reasoner did not produce a terminal status."
        yield from self._finish_phase(phase, context)

    def _run_after_turn(self, context: TurnContext) -> Iterator[RuntimeEvent]:
        phase = TurnPhase.AFTER_TURN
        yield from self._start_phase(phase, context)
        context.memory_writes = self._record_memory(context)
        self._emit_turn_committed(context)
        self.plugin_manager.after_turn(context)
        yield from self._finish_phase(phase, context)

    def _record_failed_turn(self, context: TurnContext) -> Iterator[RuntimeEvent]:
        phase = TurnPhase.AFTER_TURN
        yield from self._start_phase(phase, context)
        context.memory_writes = self._record_memory(context)
        self._emit_turn_committed(context)
        self.plugin_manager.after_turn(context)
        yield from self._finish_phase(phase, context)

    def _update_visible_tools_after_tool_search(
        self,
        context: TurnContext,
        result: ToolCallResult,
        raw_arguments: str | dict[str, Any] | None,
    ) -> None:
        if result.canonical_id != "tool_search" or context.visible_tool_names is None:
            return
        try:
            arguments = parse_arguments(raw_arguments)
        except ValueError:
            return
        selected = str(arguments.get("select") or arguments.get("tool") or "").strip()
        query = selected or str(arguments.get("query") or "").strip()
        exact = self.tools.exact_tool_match(selected or query)
        if exact:
            context.visible_tool_names.add(exact)

    def _emit_turn_committed(self, context: TurnContext) -> None:
        session_id = getattr(self.memory_manager, "session_id", "default")
        self.event_bus.emit(
            TurnCommitted(
                session_id=str(session_id),
                user_prompt=context.user_message,
                assistant_answer=context.final_answer,
                status=context.status.value,
                tool_calls=list(context.tool_records),
                memory_writes=list(context.memory_writes),
            )
        )

    def _record_memory(self, context: TurnContext) -> list[str]:
        if self.memory_manager is None:
            return []
        try:
            return self.memory_manager.record_turn(
                user_prompt=context.user_message,
                assistant_answer=context.final_answer,
                status=context.status.value,
                tool_calls=context.tool_records,
            )
        except Exception:
            return []


def _assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    assistant = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("reasoning_content"):
        assistant["reasoning_content"] = message["reasoning_content"]
    if message.get("tool_calls"):
        assistant["tool_calls"] = message["tool_calls"]
    return assistant
