"""DeepSeek-backed stepper using an OpenAI-compatible chat endpoint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from drift_agent.config import DeepSeekConfig
from drift_agent.loop import AgentState, AgentStatus, StepResult


@dataclass
class DeepSeekPlanner:
    config: DeepSeekConfig
    timeout_seconds: float = 60.0

    def __post_init__(self) -> None:
        if not self.config.api_key:
            raise ValueError("DEEPSEEK_API_KEY is required for live model mode")

    def __call__(self, state: AgentState) -> StepResult:
        try:
            answer = self._complete(state.task)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
            return StepResult(
                action="call-deepseek",
                observation=f"DeepSeek request failed: {exc}",
                status=AgentStatus.FAILURE,
                output=str(exc),
            )

        return StepResult(
            action="call-deepseek",
            observation="DeepSeek returned a final answer.",
            status=AgentStatus.SUCCESS,
            output=answer,
        )

    def _complete(self, task: str) -> str:
        payload = {
            "model": self.config.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are the first drift-agent loop implementation. "
                        "Answer the user's task directly and concisely."
                    ),
                },
                {"role": "user", "content": task},
            ],
        }
        body = json.dumps(payload).encode("utf-8")
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
        return data["choices"][0]["message"]["content"]
