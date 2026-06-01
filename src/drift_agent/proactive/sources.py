"""Local proactive source loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from drift_agent.proactive.types import ProactiveEvent, ProactiveSource


class ProactiveSourceLoader:
    def __init__(self, sources_path: str | Path = "proactive_sources.json") -> None:
        self.sources_path = Path(sources_path)

    def load_sources(self) -> list[ProactiveSource]:
        if not self.sources_path.exists():
            return []
        try:
            raw = json.loads(self.sources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_sources = raw.get("sources", raw) if isinstance(raw, dict) else raw
        if not isinstance(raw_sources, list):
            return []
        return [source for item in raw_sources if (source := parse_source(item))]

    def load_events(self) -> list[ProactiveEvent]:
        events: list[ProactiveEvent] = []
        for source in self.load_sources():
            if not source.enabled:
                continue
            if source.type == "static":
                events.extend(parse_event(item, source.channel, source.name) for item in source.events)
            elif source.type == "file" and source.path is not None:
                events.extend(self._load_file_events(source))
        return [event for event in events if event.event_id and event.title]

    def _load_file_events(self, source: ProactiveSource) -> list[ProactiveEvent]:
        try:
            raw = json.loads(source.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        raw_events = raw.get("events", raw) if isinstance(raw, dict) else raw
        if not isinstance(raw_events, list):
            return []
        return [parse_event(item, source.channel, source.name) for item in raw_events]


def parse_source(raw: object) -> ProactiveSource | None:
    if not isinstance(raw, dict):
        return None
    channel = str(raw.get("channel") or "content")
    if channel not in {"alert", "content", "context"}:
        return None
    source_type = str(raw.get("type") or raw.get("kind") or "static")
    path = raw.get("path")
    return ProactiveSource(
        type=source_type,
        channel=channel,  # type: ignore[arg-type]
        enabled=bool(raw.get("enabled", True)),
        path=Path(str(path)) if path else None,
        events=list(raw.get("events") or []),
        name=str(raw.get("name") or raw.get("server") or source_type),
    )


def parse_event(raw: object, default_channel: str, default_source: str) -> ProactiveEvent:
    if not isinstance(raw, dict):
        raw = {"title": str(raw)}
    kind = str(raw.get("kind") or default_channel)
    if kind not in {"alert", "content", "context"}:
        kind = default_channel
    title = str(raw.get("title") or raw.get("summary") or raw.get("content") or "")
    event_id = str(raw.get("event_id") or raw.get("id") or stable_event_id(kind, title))
    return ProactiveEvent(
        event_id=event_id,
        kind=kind,  # type: ignore[arg-type]
        title=title,
        content=str(raw.get("content") or raw.get("summary") or ""),
        source_name=str(raw.get("source_name") or default_source),
        url=str(raw.get("url") or ""),
        published_at=str(raw.get("published_at") or ""),
        severity=str(raw.get("severity") or ""),
        display_text=str(raw.get("display_text") or ""),
        raw=dict(raw),
    )


def stable_event_id(kind: str, title: str) -> str:
    safe = "".join(ch if ch.isalnum() else "-" for ch in title.lower()).strip("-")
    return f"{kind}:{safe[:80] or 'event'}"
