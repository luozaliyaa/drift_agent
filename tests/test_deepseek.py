from __future__ import annotations

import json

from drift_agent.config import DeepSeekConfig
from drift_agent.deepseek import DeepSeekPlanner
from drift_agent.loop import AgentState, AgentStatus
from drift_agent.permissions import PermissionPolicy


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
        permission_policy=PermissionPolicy(mode="allow"),
    )

    result = planner(AgentState(task="hello", max_steps=3, step_count=1))

    assert result.status is AgentStatus.SUCCESS
    assert result.output == "model answer"
    assert captured["url"] == "https://api.deepseek.com/chat/completions"
    assert captured["headers"]["Authorization"] == "Bearer sk-test"
    assert captured["body"]["model"] == "deepseek-v4-pro"
    assert captured["body"]["tools"][0]["type"] == "function"
    assert captured["body"]["messages"][-1]["content"] == "hello"
    assert captured["timeout"] == 5


def test_deepseek_planner_executes_tool_calls(monkeypatch, tmp_path) -> None:
    (tmp_path / "note.txt").write_text("tool result text", encoding="utf-8")
    requests = []
    responses = [
        {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "need to read the file",
                        "tool_calls": [
                            {
                                "id": "call-1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": json.dumps({"path": "note.txt"}),
                                },
                            }
                        ],
                    }
                }
            ]
        },
        {"choices": [{"message": {"content": "final with tool result"}}]},
    ]

    class SequencedResponse:
        def __init__(self, payload):
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def fake_urlopen(request, timeout):
        requests.append(json.loads(request.data.decode("utf-8")))
        return SequencedResponse(responses.pop(0))

    monkeypatch.setattr("drift_agent.deepseek.urlopen", fake_urlopen)
    planner = DeepSeekPlanner(
        DeepSeekConfig(api_key="sk-test"),
        workdir=tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    result = planner(AgentState(task="read note", max_steps=1, step_count=1))

    assert result.status is AgentStatus.SUCCESS
    assert result.output == "final with tool result"
    assert "read_file" in result.observation
    assert requests[1]["messages"][-2]["reasoning_content"] == "need to read the file"
    assert requests[1]["messages"][-1]["role"] == "tool"
    assert requests[1]["messages"][-1]["content"] == "tool result text"
