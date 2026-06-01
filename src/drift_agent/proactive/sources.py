"""Local proactive source loading."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from drift_agent.mcp import MCPClientError, MCPServerConfig, SyncMCPClient, load_mcp_config
from drift_agent.proactive.types import ProactiveEvent, ProactiveSource

if TYPE_CHECKING:
    from drift_agent.plugins import PluginManager


class ProactiveSourceLoader:
    def __init__(
        self,
        sources_path: str | Path = "proactive_sources.json",
        *,
        mcp_config_path: str | Path = "mcp_servers.json",
        mcp_client_factory: Any | None = None,
        plugin_manager: "PluginManager | None" = None,
    ) -> None:
        self.sources_path = Path(sources_path)
        self.mcp_config_path = Path(mcp_config_path)
        self.mcp_client_factory = mcp_client_factory or SyncMCPClient
        self.plugin_manager = plugin_manager

    def load_sources(self) -> list[ProactiveSource]:
        plugin_sources = self.plugin_manager.proactive_sources() if self.plugin_manager else []
        if not self.sources_path.exists():
            return plugin_sources
        try:
            raw = json.loads(self.sources_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return plugin_sources
        raw_sources = raw.get("sources", raw) if isinstance(raw, dict) else raw
        if not isinstance(raw_sources, list):
            return plugin_sources
        file_sources = [source for item in raw_sources if (source := parse_source(item))]
        return [*file_sources, *plugin_sources]

    def load_events(self) -> list[ProactiveEvent]:
        events: list[ProactiveEvent] = []
        for source in self.load_sources():
            if not source.enabled:
                continue
            if source.type == "static":
                events.extend(parse_event(item, source.channel, source.name) for item in source.events)
            elif source.type == "file" and source.path is not None:
                events.extend(self._load_file_events(source))
            elif source.type in {"github_mcp", "mcp"}:
                events.extend(self._load_mcp_events(source))
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

    def _load_mcp_events(self, source: ProactiveSource) -> list[ProactiveEvent]:
        server = self._load_mcp_server(source.server or "github")
        if server is None:
            return []
        tool = source.tool or "list_notifications"
        try:
            with self.mcp_client_factory(server) as client:
                result = client.call_tool(tool, source.arguments)
        except (MCPClientError, OSError, ValueError):
            return []
        payloads = extract_mcp_payloads(result)
        events: list[ProactiveEvent] = []
        for payload in payloads:
            events.extend(parse_github_mcp_payload(payload, source))
        return events

    def _load_mcp_server(self, server_name: str) -> MCPServerConfig | None:
        return load_mcp_config(self.mcp_config_path).get(server_name)


def parse_source(raw: object) -> ProactiveSource | None:
    if not isinstance(raw, dict):
        return None
    channel = str(raw.get("channel") or "content")
    if channel not in {"alert", "content", "context"}:
        return None
    source_type = str(raw.get("type") or raw.get("kind") or "static")
    path = raw.get("path")
    arguments = raw.get("arguments") or raw.get("params") or {}
    if not isinstance(arguments, dict):
        arguments = {}
    return ProactiveSource(
        type=source_type,
        channel=channel,  # type: ignore[arg-type]
        enabled=bool(raw.get("enabled", True)),
        path=Path(str(path)) if path else None,
        server=str(raw.get("server") or "github"),
        tool=str(raw.get("tool") or raw.get("mcp_tool") or ""),
        arguments=dict(arguments),
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


def extract_mcp_payloads(result: object) -> list[object]:
    if isinstance(result, dict):
        structured = result.get("structuredContent")
        if structured is not None:
            return [structured]
        content = result.get("content")
        if isinstance(content, list):
            payloads: list[object] = []
            for item in content:
                if not isinstance(item, dict):
                    continue
                if item.get("type") == "text":
                    payloads.append(parse_json_or_text(str(item.get("text") or "")))
                elif "json" in item:
                    payloads.append(item["json"])
            return payloads
    return [result]


def parse_json_or_text(text: str) -> object:
    stripped = text.strip()
    if not stripped:
        return {}
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        return {"title": stripped, "content": stripped}


def parse_github_mcp_payload(payload: object, source: ProactiveSource) -> list[ProactiveEvent]:
    items = github_payload_items(payload)
    return [github_item_to_event(item, source) for item in items]


def github_payload_items(payload: object) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in (
        "notifications",
        "items",
        "issues",
        "pull_requests",
        "pullRequests",
        "check_runs",
        "runs",
        "events",
        "data",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return [payload]


def github_item_to_event(item: dict[str, Any], source: ProactiveSource) -> ProactiveEvent:
    subject = item.get("subject") if isinstance(item.get("subject"), dict) else {}
    repository = item.get("repository") if isinstance(item.get("repository"), dict) else {}
    title = first_text(
        item.get("title"),
        subject.get("title"),
        item.get("name"),
        item.get("summary"),
        item.get("html_url"),
        item.get("url"),
    )
    repo_name = first_text(repository.get("full_name"), item.get("repo"), item.get("repository"))
    content = github_item_content(item, subject, repo_name)
    url = first_text(
        item.get("html_url"),
        item.get("web_url"),
        item.get("url"),
        subject.get("url"),
    )
    kind = github_item_kind(item, source.channel)
    event_id = first_text(
        item.get("event_id"),
        item.get("id"),
        item.get("node_id"),
        f"{repo_name}#{item.get('number')}" if item.get("number") else "",
        f"{url}:{item.get('updated_at')}" if url else "",
        stable_event_id(kind, title),
    )
    return ProactiveEvent(
        event_id=f"github:{event_id}",
        kind=kind,
        title=title,
        content=content,
        source_name=source.name or source.server or "github",
        url=url,
        published_at=first_text(item.get("updated_at"), item.get("created_at")),
        severity=github_item_severity(item),
        display_text=content,
        raw=dict(item),
    )


def github_item_content(
    item: dict[str, Any],
    subject: dict[str, Any],
    repo_name: str,
) -> str:
    parts = [
        f"repo={repo_name}" if repo_name else "",
        f"type={first_text(item.get('type'), subject.get('type'))}"
        if first_text(item.get("type"), subject.get("type"))
        else "",
        f"reason={item.get('reason')}" if item.get("reason") else "",
        f"state={item.get('state')}" if item.get("state") else "",
        first_text(item.get("body"), item.get("summary"), item.get("message")),
    ]
    return " | ".join(part for part in parts if part)


def github_item_kind(item: dict[str, Any], default: str) -> str:
    reason = str(item.get("reason") or "").lower()
    conclusion = str(item.get("conclusion") or item.get("status") or "").lower()
    state = str(item.get("state") or "").lower()
    if reason in {"mention", "review_requested", "assign", "author"}:
        return "alert"
    if conclusion in {"failure", "failed", "cancelled", "timed_out"}:
        return "alert"
    if state in {"failure", "failed"}:
        return "alert"
    return default if default in {"alert", "content", "context"} else "content"


def github_item_severity(item: dict[str, Any]) -> str:
    conclusion = str(item.get("conclusion") or item.get("status") or "").lower()
    if conclusion in {"failure", "failed", "cancelled", "timed_out"}:
        return "high"
    return str(item.get("severity") or "")


def first_text(*values: object) -> str:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""
