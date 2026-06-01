from __future__ import annotations

import json

from drift_agent.proactive.agent_tick import ProactiveAgentTick
from drift_agent.proactive.sources import ProactiveSourceLoader
from drift_agent.proactive.types import ProactiveConfig
from drift_agent.drift.types import DriftResult


class FakeClient:
    def __init__(self, content: str) -> None:
        self.content = content
        self.requests = []

    def chat(self, messages, tools):
        self.requests.append({"messages": messages, "tools": tools})
        return {"content": self.content}


class FakeMemoryManager:
    def load_prompt_context(self, task):
        assert task == "proactive tick"

        class Context:
            def to_prompt(self):
                return "Long-term memory says user likes concise notices."

        return Context()


def write_sources(path, events) -> None:
    path.write_text(
        json.dumps({"sources": [{"type": "static", "channel": "alert", "events": events}]}),
        encoding="utf-8",
    )


def test_alert_reply_uses_llm_decision(tmp_path) -> None:
    sources = tmp_path / "sources.json"
    context = tmp_path / "PROACTIVE_CONTEXT.md"
    write_sources(sources, [{"event_id": "a1", "title": "CI failed", "content": "main failed"}])
    client = FakeClient(
        json.dumps(
            {
                "decision": "reply",
                "message": "CI failed on main.",
                "evidence": ["a1"],
                "reason": "alert",
            }
        )
    )
    tick = ProactiveAgentTick(
        config=ProactiveConfig(
            enabled=True,
            sources_path=sources,
            context_path=context,
            context_prob=1.0,
        ),
        client=client,
        memory_manager=FakeMemoryManager(),
    )

    decision = tick.run_once()
    prompt = client.requests[0]["messages"][1]["content"]

    assert decision.should_send is True
    assert decision.message == "CI failed on main."
    assert "PROACTIVE_CONTEXT.md" in prompt
    assert "Long-term memory" in prompt


def test_content_skip_does_not_send(tmp_path) -> None:
    sources = tmp_path / "sources.json"
    sources.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "type": "static",
                        "channel": "content",
                        "events": [{"event_id": "c1", "title": "Minor article"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    tick = ProactiveAgentTick(
        config=ProactiveConfig(enabled=True, sources_path=sources),
        client=FakeClient(json.dumps({"decision": "skip", "reason": "not useful"})),
    )

    decision = tick.run_once()

    assert decision.should_send is False
    assert decision.reason == "not useful"


def test_context_fallback_respects_probability(tmp_path) -> None:
    sources = tmp_path / "sources.json"
    sources.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "type": "static",
                        "channel": "context",
                        "events": [{"event_id": "ctx1", "title": "Sleep context"}],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    skipped = ProactiveAgentTick(
        config=ProactiveConfig(enabled=True, sources_path=sources, context_prob=0.0),
        source_loader=ProactiveSourceLoader(sources),
    ).run_once()
    visible = ProactiveAgentTick(
        config=ProactiveConfig(enabled=True, sources_path=sources, context_prob=1.0),
        client=FakeClient(json.dumps({"decision": "reply", "message": "Sleep context."})),
    ).run_once()

    assert skipped.should_send is False
    assert visible.should_send is True


def test_proactive_empty_events_triggers_drift(tmp_path) -> None:
    class FakeDrift:
        def __init__(self) -> None:
            self.called = False

        def maybe_run(self):
            self.called = True
            return DriftResult(
                completed=True,
                message_result="sent",
                message="drift says hello",
                one_line="curiosity: asked",
            )

    drift = FakeDrift()
    tick = ProactiveAgentTick(
        config=ProactiveConfig(enabled=True, sources_path=tmp_path / "missing.json"),
        drift_runner=drift,
    )

    decision = tick.run_once()

    assert drift.called is True
    assert decision.should_send is True
    assert decision.message == "drift says hello"


def test_proactive_events_do_not_trigger_drift(tmp_path) -> None:
    class FakeDrift:
        called = False

        def maybe_run(self):
            self.called = True
            return DriftResult(completed=False)

    sources = tmp_path / "sources.json"
    write_sources(sources, [{"event_id": "a1", "title": "Alert"}])
    drift = FakeDrift()
    tick = ProactiveAgentTick(
        config=ProactiveConfig(enabled=True, sources_path=sources),
        client=FakeClient(json.dumps({"decision": "skip", "reason": "handled"})),
        drift_runner=drift,
    )

    decision = tick.run_once()

    assert drift.called is False
    assert decision.reason == "handled"
