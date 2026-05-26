from __future__ import annotations

import json

from drift_agent.permissions import PermissionPolicy
from drift_agent.tools import (
    MCPToolProvider,
    ToolRegistry,
    WebToolProvider,
    WorkspaceToolProvider,
    create_default_tool_registry,
)


def test_registry_exports_namespaced_openai_tools(tmp_path) -> None:
    registry = create_default_tool_registry(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
    )

    tools = registry.as_openai_tools()
    names = {tool["function"]["name"] for tool in tools}

    assert "workspace__read_file" in names
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


def test_disabled_web_provider_is_not_exposed_by_default() -> None:
    registry = create_default_tool_registry(enable_web_tools=True)

    names = {tool["function"]["name"] for tool in registry.as_openai_tools()}

    assert "web__fetch" not in names


def test_disabled_stub_providers_return_recoverable_errors() -> None:
    web = WebToolProvider(enabled=False)
    mcp = MCPToolProvider(enabled=False)

    assert web.call_tool("web.fetch", {"url": "https://example.com"}).output == (
        "Tool disabled: web.fetch"
    )
    assert mcp.call_tool("mcp.default.search", {}).output == (
        "Tool disabled: mcp.default.search"
    )
