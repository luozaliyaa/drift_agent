from __future__ import annotations

import json

from drift_agent.proactive.sources import ProactiveSourceLoader


class FakeMCPClient:
    def __init__(self, server) -> None:
        self.server = server

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass

    def call_tool(self, name, arguments):
        assert self.server.name == "github"
        assert name == "list_notifications"
        assert arguments == {"filter": "participating"}
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "notifications": [
                                {
                                    "id": "n1",
                                    "reason": "review_requested",
                                    "subject": {
                                        "title": "Review API change",
                                        "type": "PullRequest",
                                    },
                                    "repository": {"full_name": "owner/repo"},
                                    "updated_at": "2026-06-01T00:00:00Z",
                                }
                            ]
                        }
                    ),
                }
            ]
        }


def test_static_source_loads_events(tmp_path) -> None:
    path = tmp_path / "proactive_sources.json"
    path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "type": "static",
                        "channel": "alert",
                        "name": "test",
                        "events": [
                            {
                                "event_id": "a1",
                                "title": "Build finished",
                                "content": "The build is ready.",
                            }
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    events = ProactiveSourceLoader(path).load_events()

    assert len(events) == 1
    assert events[0].event_id == "a1"
    assert events[0].kind == "alert"
    assert events[0].source_name == "test"


def test_file_source_loads_events_and_bad_sources_do_not_block(tmp_path) -> None:
    events_path = tmp_path / "events.json"
    events_path.write_text(
        json.dumps([{"id": "c1", "title": "Interesting article"}]),
        encoding="utf-8",
    )
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(
        json.dumps(
            {
                "sources": [
                    {"type": "file", "channel": "content", "path": str(events_path)},
                    {"type": "file", "channel": "content", "path": str(tmp_path / "missing.json")},
                    {"type": "static", "channel": "bad", "events": [{"title": "bad"}]},
                ]
            }
        ),
        encoding="utf-8",
    )

    events = ProactiveSourceLoader(sources_path).load_events()

    assert [event.event_id for event in events] == ["c1"]
    assert events[0].kind == "content"


def test_github_mcp_source_loads_notifications(tmp_path) -> None:
    mcp_config = tmp_path / "mcp_servers.json"
    mcp_config.write_text(
        json.dumps({"servers": {"github": {"command": "fake-github-mcp"}}}),
        encoding="utf-8",
    )
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "type": "github_mcp",
                        "channel": "content",
                        "server": "github",
                        "tool": "list_notifications",
                        "arguments": {"filter": "participating"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    events = ProactiveSourceLoader(
        sources_path,
        mcp_config_path=mcp_config,
        mcp_client_factory=FakeMCPClient,
    ).load_events()

    assert len(events) == 1
    assert events[0].event_id == "github:n1"
    assert events[0].kind == "alert"
    assert events[0].title == "Review API change"
    assert "owner/repo" in events[0].content


def test_github_mcp_source_can_use_persistent_registry(tmp_path) -> None:
    from drift_agent.mcp import MCPServerRegistry

    starts = []

    class CountingMCPClient(FakeMCPClient):
        def __enter__(self):
            starts.append(self.server.name)
            return self

    mcp_config = tmp_path / "mcp_servers.json"
    mcp_config.write_text(
        json.dumps({"servers": {"github": {"command": "fake-github-mcp"}}}),
        encoding="utf-8",
    )
    sources_path = tmp_path / "sources.json"
    sources_path.write_text(
        json.dumps(
            {
                "sources": [
                    {
                        "type": "github_mcp",
                        "channel": "content",
                        "server": "github",
                        "tool": "list_notifications",
                        "arguments": {"filter": "participating"},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    registry = MCPServerRegistry(mcp_config, client_factory=CountingMCPClient)

    try:
        loader = ProactiveSourceLoader(
            sources_path,
            mcp_config_path=mcp_config,
            mcp_registry=registry,
        )
        first = loader.load_events()
        second = loader.load_events()
    finally:
        registry.close_all()

    assert len(first) == 1
    assert len(second) == 1
    assert starts == ["github"]
