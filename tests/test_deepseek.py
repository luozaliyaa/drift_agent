from __future__ import annotations

import json

from drift_agent.config import DeepSeekConfig
from drift_agent.deepseek import DeepSeekPlanner
from drift_agent.loop import AgentState, AgentStatus


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self) -> bytes:
        return json.dumps(
            {"choices": [{"message": {"content": "model answer"}}]}
        ).encode("utf-8")


def test_deepseek_planner_posts_expected_request(monkeypatch) -> None:
    captured = {}

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["headers"] = dict(request.header_items())
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("drift_agent.deepseek.urlopen", fake_urlopen)
    planner = DeepSeekPlanner(
        DeepSeekConfig(
            api_key="sk-test",
            model="deepseek-v4-pro",
            base_url="https://api.deepseek.com",
        ),
        timeout_seconds=5,
    )

    result = planner(AgentState(task="hello", max_steps=3, step_count=1))

    assert result.status is AgentStatus.SUCCESS
    assert result.output == "model answer"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["body"]["model"] == "deepseek-v4-pro"
    assert captured["body"]["messages"][-1]["content"] == "hello"
    assert captured["timeout"] == 5
