from __future__ import annotations

import json

from drift_agent.drift.runner import DriftRunner
from drift_agent.drift.state import DriftStateStore
from drift_agent.drift.types import DriftConfig, DriftRunRecord


class FakeClient:
    def __init__(self, *messages) -> None:
        self.messages = list(messages)
        self.requests = []

    def chat(self, messages, tools):
        self.requests.append({"messages": messages, "tools": tools})
        return self.messages.pop(0)


def tool_message(name: str, arguments: dict[str, object], call_id: str = "call") -> dict:
    return {
        "content": "",
        "tool_calls": [
            {
                "id": call_id,
                "type": "function",
                "function": {
                    "name": name,
                    "arguments": json.dumps(arguments),
                },
            }
        ],
    }


def write_skill(tmp_path, name: str = "curiosity") -> None:
    skill_dir = tmp_path / "drift" / "skills" / name
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        f"""---
name: {name}
description: Test skill
---

## Goal
Run {name}.
""",
        encoding="utf-8",
    )


def test_drift_runner_records_sent_run(tmp_path) -> None:
    write_skill(tmp_path)
    client = FakeClient(
        tool_message("drift__message_push", {"message": "small question"}, "push"),
        tool_message(
            "drift__finish_drift",
            {
                "message_result": "sent",
                "skill": "curiosity",
                "one_line": "curiosity: asked one question",
            },
            "finish",
        ),
    )
    runner = DriftRunner(
        config=DriftConfig(drift_dir=tmp_path / "drift", min_interval_hours=0),
        client=client,
        workdir=tmp_path,
    )

    result = runner.maybe_run()

    assert result.completed is True
    assert result.should_send is True
    assert result.message == "small question"
    data = json.loads((tmp_path / "drift" / "drift.json").read_text(encoding="utf-8"))
    assert data["recent_runs"][0]["skill"] == "curiosity"


def test_drift_runner_records_silent_run_without_message(tmp_path) -> None:
    write_skill(tmp_path, "review")
    client = FakeClient(
        tool_message(
            "drift__finish_drift",
            {
                "message_result": "silent",
                "skill": "review",
                "one_line": "review: updated backlog",
            },
        )
    )
    runner = DriftRunner(
        config=DriftConfig(drift_dir=tmp_path / "drift", min_interval_hours=0),
        client=client,
        workdir=tmp_path,
    )

    result = runner.maybe_run()

    assert result.completed is True
    assert result.should_send is False
    assert result.message_result == "silent"


def test_drift_runner_does_not_record_unfinished_run(tmp_path) -> None:
    write_skill(tmp_path)
    runner = DriftRunner(
        config=DriftConfig(drift_dir=tmp_path / "drift", max_steps=1, min_interval_hours=0),
        client=FakeClient({"content": "I forgot to finish."}),
        workdir=tmp_path,
    )

    result = runner.maybe_run()

    assert result.completed is False
    assert not (tmp_path / "drift" / "drift.json").exists()


def test_drift_runner_respects_min_interval(tmp_path) -> None:
    write_skill(tmp_path)
    state = DriftStateStore(tmp_path / "drift")
    state.record_run(
        DriftRunRecord(
            skill="curiosity",
            run_at="2999-01-01T00:00:00Z",
            one_line="future run",
            message_result="silent",
        )
    )
    runner = DriftRunner(
        config=DriftConfig(drift_dir=tmp_path / "drift", min_interval_hours=1),
        client=FakeClient(tool_message("drift__finish_drift", {"message_result": "silent", "one_line": "x"})),
        workdir=tmp_path,
        state=state,
    )

    result = runner.maybe_run()

    assert result.completed is False
    assert result.reason == "drift interval not elapsed"
