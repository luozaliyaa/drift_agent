"""One proactive decision tick."""

from __future__ import annotations

import json
from typing import Any, Protocol

from drift_agent.memory import MemoryManager
from drift_agent.proactive.context import read_proactive_context
from drift_agent.proactive.sources import ProactiveSourceLoader
from drift_agent.proactive.types import ProactiveConfig, ProactiveDecision, ProactiveEvent


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...


class ProactiveAgentTick:
    def __init__(
        self,
        *,
        config: ProactiveConfig,
        client: ChatClient | None = None,
        memory_manager: MemoryManager | None = None,
        source_loader: ProactiveSourceLoader | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.memory_manager = memory_manager
        self.source_loader = source_loader or ProactiveSourceLoader(config.sources_path)

    def run_once(self) -> ProactiveDecision:
        events = self.source_loader.load_events()
        visible_events = select_visible_events(events, self.config.context_prob)
        if not visible_events:
            return ProactiveDecision("skip", reason="no proactive events")
        if self.client is None:
            return fallback_decision(visible_events)
        prompt = self.build_prompt(visible_events)
        message = self.client.chat(
            [
                {"role": "system", "content": PROACTIVE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            [],
        )
        return parse_decision(str(message.get("content") or ""))

    def build_prompt(self, events: list[ProactiveEvent]) -> str:
        proactive_context = read_proactive_context(self.config.context_path)
        memory_prompt = ""
        if self.memory_manager is not None:
            memory_prompt = self.memory_manager.load_prompt_context("proactive tick").to_prompt()
        event_payload = [
            {
                "event_id": event.event_id,
                "kind": event.kind,
                "source_name": event.source_name,
                "title": event.title,
                "content": event.content,
                "url": event.url,
                "severity": event.severity,
                "display_text": event.display_text,
            }
            for event in events
        ]
        return (
            "PROACTIVE_CONTEXT.md:\n"
            + proactive_context
            + "\n\nMEMORY_CONTEXT:\n"
            + (memory_prompt or "(none)")
            + "\n\nEVENTS:\n"
            + json.dumps(event_payload, ensure_ascii=False, indent=2)
        )


PROACTIVE_SYSTEM_PROMPT = """You are Drift Agent's proactive decision loop.
Return JSON only:
{"decision":"reply|skip","message":"...","evidence":["event_id"],"reason":"..."}

Send only if the notice is clearly useful now. Alerts may be sent directly.
Content should be filtered by the proactive context and memory. Context-only
items are fallback material and should usually be skipped unless very timely.
"""


def select_visible_events(
    events: list[ProactiveEvent],
    context_prob: float,
) -> list[ProactiveEvent]:
    alerts_or_content = [event for event in events if event.kind in {"alert", "content"}]
    if alerts_or_content:
        return sorted(alerts_or_content, key=event_priority)
    if context_prob >= 1.0:
        return [event for event in events if event.kind == "context"]
    return []


def event_priority(event: ProactiveEvent) -> tuple[int, str]:
    if event.kind == "alert":
        return (0, event.event_id)
    return (1, event.event_id)


def fallback_decision(events: list[ProactiveEvent]) -> ProactiveDecision:
    alerts = [event for event in events if event.kind == "alert"]
    if not alerts:
        return ProactiveDecision("skip", reason="no LLM client and no alert")
    message = "\n".join(event.compact() for event in alerts)
    return ProactiveDecision(
        decision="reply",
        message=message,
        evidence=[event.event_id for event in alerts],
        reason="alert fallback",
    )


def parse_decision(content: str) -> ProactiveDecision:
    data = parse_json_object(content)
    decision = str(data.get("decision") or "skip")
    if decision not in {"reply", "skip"}:
        decision = "skip"
    evidence = data.get("evidence") or []
    if not isinstance(evidence, list):
        evidence = []
    return ProactiveDecision(
        decision=decision,  # type: ignore[arg-type]
        message=str(data.get("message") or "").strip(),
        evidence=[str(item) for item in evidence],
        reason=str(data.get("reason") or "").strip(),
    )


def parse_json_object(content: str) -> dict[str, Any]:
    cleaned = content.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end >= start:
        cleaned = cleaned[start : end + 1]
    data = json.loads(cleaned or "{}")
    if not isinstance(data, dict):
        raise ValueError("Proactive response must be a JSON object")
    return data
