"""DeepSeek-backed stepper using an OpenAI-compatible chat endpoint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from drift_agent.agent import AgentTurnLoop
from drift_agent.config import DeepSeekConfig
from drift_agent.loop import AgentState, AgentStatus, StepResult
from drift_agent.memory import MemoryLLM, MemoryManager
from drift_agent.permissions import PermissionPolicy
from drift_agent.plugins import PluginManager
from drift_agent.tools import ToolRegistry, create_default_tool_registry


@dataclass
class DeepSeekClient:
    config: DeepSeekConfig
    timeout_seconds: float = 60.0

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
        }
        data = self._post_json(payload)
        return data["choices"][0]["message"]

    def stream_chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ):
        payload = {
            "model": self.config.model,
            "messages": messages,
            "tools": tools,
            "tool_choice": "auto",
            "stream": True,
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = self._request(body)
        with urlopen(request, timeout=self.timeout_seconds) as response:
            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or line.startswith(":"):
                    continue
                if not line.startswith("data:"):
                    continue
                data = line.removeprefix("data:").strip()
                if data == "[DONE]":
                    break
                yield json.loads(data)

    def _post_json(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        request = self._request(body)
        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        return json.loads(raw)

    def _request(self, body: bytes) -> Request:
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        return Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )


@dataclass
class DeepSeekPlanner:
    config: DeepSeekConfig
    timeout_seconds: float = 60.0
    workdir: str | Path | None = None
    max_tool_rounds: int = 8
    permission_policy: PermissionPolicy | None = None
    memory_manager: MemoryManager | None = None
    show_memory: bool = False
    tool_registry: ToolRegistry | None = None
    plugin_manager: PluginManager | None = None

    def __post_init__(self) -> None:
        if not self.config.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for live model mode")
        self.client = DeepSeekClient(self.config, self.timeout_seconds)
        if self.memory_manager is not None and self.memory_manager.llm is None:
            self.memory_manager.configure_llm(MemoryLLM(self.client))
            if self.memory_manager.optimize_now:
                self.memory_manager.optimize(force=True)
                self.memory_manager.optimize_now = False
        self.tools = self.tool_registry or create_default_tool_registry(
            self.workdir,
            permission_policy=self.permission_policy,
            memory_manager=self.memory_manager,
            plugin_manager=self.plugin_manager,
        )

    def __call__(self, state: AgentState) -> StepResult:
        try:
            result, _context = self._turn_loop(stream=False).run_turn(state.task)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            message = _format_request_error(exc)
            _record_memory_safely(
                self.memory_manager,
                state.task,
                message,
                AgentStatus.FAILURE.value,
                [],
            )
            return StepResult(
                action="call-deepseek",
                observation=f"DeepSeek request failed: {message}",
                status=AgentStatus.FAILURE,
                output=message,
            )
        return result

    def stream_step(self, state: AgentState):
        try:
            yield from self._turn_loop(stream=True).stream_turn(state.task)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            message = _format_request_error(exc)
            _record_memory_safely(
                self.memory_manager,
                state.task,
                message,
                AgentStatus.FAILURE.value,
                [],
            )
            yield StepResult(
                action="six-phase-turn",
                observation=f"DeepSeek request failed: {message}",
                status=AgentStatus.FAILURE,
                output=message,
            )

    def _turn_loop(self, stream: bool) -> AgentTurnLoop:
        return AgentTurnLoop(
            client=self.client,
            tools=self.tools,
            memory_manager=self.memory_manager,
            max_tool_rounds=self.max_tool_rounds,
            show_memory=self.show_memory,
            stream=stream,
            error_formatter=_format_request_error,
            plugin_manager=self.plugin_manager,
        )


def _format_request_error(exc: Exception) -> str:
    if isinstance(exc, HTTPError):
        try:
            body = exc.read().decode("utf-8")
        except OSError:
            body = ""
        if body:
            return f"HTTP {exc.code}: {body}"
        return f"HTTP {exc.code}: {exc.reason}"
    return str(exc)


def _record_memory_safely(
    memory_manager: MemoryManager | None,
    user_prompt: str,
    assistant_answer: str,
    status: str,
    tool_records: list[dict[str, object]],
) -> list[str]:
    if memory_manager is None:
        return []
    try:
        return memory_manager.record_turn(
            user_prompt=user_prompt,
            assistant_answer=assistant_answer,
            status=status,
            tool_calls=tool_records,
        )
    except Exception:
        return []
