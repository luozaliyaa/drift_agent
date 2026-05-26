"""DeepSeek-backed stepper using an OpenAI-compatible chat endpoint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from drift_agent.config import DeepSeekConfig
from drift_agent.loop import AgentState, AgentStatus, StepResult
from drift_agent.permissions import PermissionPolicy
from drift_agent.tools import WorkspaceTools


@dataclass
class DeepSeekPlanner:
    config: DeepSeekConfig
    timeout_seconds: float = 60.0
    workdir: str | Path | None = None
    max_tool_rounds: int = 8
    permission_policy: PermissionPolicy | None = None

    def __post_init__(self) -> None:
        if not self.config.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for live model mode")
        self.tools = WorkspaceTools(
            self.workdir,
            permission_policy=self.permission_policy,
        )

    def __call__(self, state: AgentState) -> StepResult:
        try:
            answer, tool_trace = self._complete(state.task)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            message = _format_request_error(exc)
            return StepResult(
                action="call-deepseek",
                observation=f"DeepSeek request failed: {message}",
                status=AgentStatus.FAILURE,
                output=message,
            )

        observation = "DeepSeek returned a final answer."
        if tool_trace:
            observation += "\nTools:\n" + "\n".join(tool_trace)
        return StepResult(
            action="call-deepseek",
            observation=observation,
            status=AgentStatus.SUCCESS,
            output=answer,
        )

    def _complete(self, task: str) -> tuple[str, list[str]]:
        messages: list[dict[str, Any]] = [
            {
                "role": "system",
                "content": (
                    "You are a coding agent in the current workspace. "
                    "Use tools when you need to inspect files, run commands, "
                    "or make requested file changes. Act directly and keep the "
                    "final answer concise."
                ),
            },
            {"role": "user", "content": task},
        ]
        tool_trace: list[str] = []

        for _ in range(self.max_tool_rounds):
            message = self._chat(messages)
            tool_calls = message.get("tool_calls") or []
            messages.append(_assistant_message(message))

            if not tool_calls:
                return str(message.get("content") or ""), tool_trace

            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                tool_name = str(function.get("name") or "")
                arguments = function.get("arguments")
                output = self.tools.dispatch_json(tool_name, arguments)
                tool_trace.append(f"- {tool_name}: {output[:200]}")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "name": tool_name,
                        "content": output,
                    }
                )

        raise ValueError(f"Exceeded max tool rounds: {self.max_tool_rounds}")

    def _chat(self, messages: list[dict[str, Any]]) -> dict[str, Any]:
        payload = {
            "model": self.config.model,
            "messages": messages,
            "tools": self.tools.as_openai_tools(),
            "tool_choice": "auto",
        }
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        endpoint = self.config.base_url.rstrip("/") + "/chat/completions"
        request = Request(
            endpoint,
            data=body,
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )

        with urlopen(request, timeout=self.timeout_seconds) as response:
            raw = response.read().decode("utf-8")
        data = json.loads(raw)
        return data["choices"][0]["message"]


def _assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    assistant = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("reasoning_content"):
        assistant["reasoning_content"] = message["reasoning_content"]
    if message.get("tool_calls"):
        assistant["tool_calls"] = message["tool_calls"]
    return assistant


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
