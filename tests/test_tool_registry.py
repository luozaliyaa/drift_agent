from __future__ import annotations

import json

from drift_agent.memory import MemoryManager
from drift_agent.permissions import PermissionPolicy
from drift_agent.tools import (
    MCPToolProvider,
    ToolRegistry,
    WebToolProvider,
    WorkspaceToolProvider,
    create_default_tool_registry,
)


class FakeMCPClient:
    def __init__(self, server) -> None:
        self.server = server

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        pass

    def list_tools(self):
        return [
            {
                "name": "list_notifications",
                "description": "List GitHub notifications",
                "inputSchema": {
                    "type": "object",
                    "properties": {"filter": {"type": "string"}},
                },
            }
        ]

    def call_tool(self, name, arguments):
        return {
            "tool": name,
            "arguments": arguments,
            "server": self.server.name,
        }


def test_registry_exports_namespaced_openai_tools(tmp_path) -> None:
    registry = create_default_tool_registry(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    tools = registry.as_openai_tools()
    names = {tool["function"]["name"] for tool in tools}

    assert "workspace__read_file" in names
    assert "workspace__list_dir" in names
    assert "workspace__file_info" in names
    assert "workspace__search_text" in names
    assert "workspace__make_dir" in names
    assert "workspace__move_file" in names
    assert "workspace__delete_file" in names
    assert "read_file" not in names


def test_registry_dispatch_supports_encoded_canonical_and_short_alias(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    registry = create_default_tool_registry(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    assert registry.dispatch_json("workspace__read_file", {"path": "note.txt"}) == "hello"
    assert registry.dispatch_json("workspace.read_file", {"path": "note.txt"}) == "hello"
    assert registry.dispatch_json("read_file", {"path": "note.txt"}) == "hello"


def test_registry_records_last_canonical_id(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    registry = create_default_tool_registry(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    result = registry.dispatch("workspace__read_file", json.dumps({"path": "note.txt"}))

    assert result.canonical_id == "workspace.read_file"
    assert registry.last_canonical_id == "workspace.read_file"


def test_registry_rejects_duplicate_canonical_ids(tmp_path) -> None:
    registry = ToolRegistry()
    provider_a = WorkspaceToolProvider(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )
    provider_b = WorkspaceToolProvider(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    registry.register_provider(provider_a)

    try:
        registry.register_provider(provider_b)
    except ValueError as exc:
        assert "Duplicate tool id" in str(exc)
    else:
        raise AssertionError("Expected duplicate tool id failure")


def test_web_provider_is_not_exposed_by_default() -> None:
    registry = create_default_tool_registry()

    names = {tool["function"]["name"] for tool in registry.as_openai_tools()}

    assert "web__fetch" not in names


def test_memory_provider_is_exposed_when_memory_enabled(tmp_path) -> None:
    memory = MemoryManager(tmp_path / ".memory")
    registry = create_default_tool_registry(memory_manager=memory)

    names = {tool["function"]["name"] for tool in registry.as_openai_tools()}
    result = registry.dispatch(
        "memory__remember",
        {"content": "User prefers concise updates.", "memory_type": "preference"},
    )

    assert "memory__remember" in names
    assert "memory__recall" in names
    assert "memory__forget" in names
    assert json.loads(result.output)["memory_type"] == "preference"


def test_web_fetch_is_exposed_when_enabled() -> None:
    registry = create_default_tool_registry(enable_web_tools=True)

    names = {tool["function"]["name"] for tool in registry.as_openai_tools()}

    assert "web__fetch" in names
    assert "web__search" not in names


def test_mcp_provider_exposes_configured_server_tools(tmp_path, monkeypatch) -> None:
    from drift_agent.tools import mcp as mcp_module

    config_path = tmp_path / "mcp_servers.json"
    config_path.write_text(
        json.dumps({"servers": {"github": {"command": "fake-github-mcp"}}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(mcp_module, "SyncMCPClient", FakeMCPClient)
    registry = create_default_tool_registry(
        enable_mcp_tools=True,
        mcp_config_path=config_path,
        mcp_server="github",
    )

    names = {tool["function"]["name"] for tool in registry.as_openai_tools()}
    result = registry.dispatch_json(
        "mcp__github__list_notifications",
        {"filter": "participating"},
    )

    assert "mcp__github__list_notifications" in names
    assert json.loads(result)["tool"] == "list_notifications"
    assert json.loads(result)["arguments"] == {"filter": "participating"}


def test_disabled_stub_providers_return_recoverable_errors() -> None:
    web = WebToolProvider(enabled=False)
    mcp = MCPToolProvider(enabled=False)

    assert web.call_tool("web.fetch", {"url": "https://example.com"}).output == (
        "Tool disabled: web.fetch"
    )
    assert mcp.call_tool("mcp.default.search", {}).output == (
        "Tool disabled: mcp.default.search"
    )
