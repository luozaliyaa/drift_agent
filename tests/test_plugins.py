from __future__ import annotations

from drift_agent.agent import AgentTurnLoop
from drift_agent.loop import AgentStatus
from drift_agent.permissions import PermissionPolicy
from drift_agent.plugins import Plugin, PluginManager, ToolHookResult
from drift_agent.proactive.sources import ProactiveSourceLoader
from drift_agent.tools import create_default_tool_registry
from drift_agent.tools.base import ToolCallResult, ToolSpec


def test_plugin_manager_discovers_plugins(tmp_path) -> None:
    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "plugin.py").write_text(
        """
from drift_agent.plugins import Plugin

class DemoPlugin(Plugin):
    name = "demo"

    def prompt_sections(self):
        return ["PLUGIN PROMPT"]
""",
        encoding="utf-8",
    )

    manager = PluginManager.discover(tmp_path / "plugins")

    assert [plugin.name for plugin in manager.plugins] == ["demo"]
    assert manager.prompt_sections() == ["PLUGIN PROMPT"]


def test_plugin_tools_register_and_dispatch(tmp_path) -> None:
    class EchoPlugin(Plugin):
        name = "echo"

        def tools(self):
            return [
                ToolSpec(
                    canonical_id="plugin.echo",
                    aliases=("echo_plugin",),
                    description="Echo plugin input.",
                    parameters={
                        "type": "object",
                        "properties": {"text": {"type": "string"}},
                        "required": ["text"],
                    },
                )
            ]

        def call_tool(self, canonical_id, arguments):
            return ToolCallResult(canonical_id, "echo:" + str(arguments["text"]))

    manager = PluginManager([EchoPlugin()])
    registry = create_default_tool_registry(tmp_path, plugin_manager=manager)

    assert registry.dispatch_json("plugin__echo", {"text": "hi"}) == "echo:hi"
    assert registry.dispatch_json("echo_plugin", {"text": "hi"}) == "echo:hi"


def test_agent_turn_loop_runs_plugin_prompt_tool_hooks_and_after_turn(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello from file", encoding="utf-8")
    calls = []

    class HookPlugin(Plugin):
        name = "hook"

        def prompt_sections(self):
            return ["PLUGIN PROMPT"]

        def before_tool_call(self, context):
            calls.append(("before", context.canonical_id, dict(context.arguments)))
            return {"path": "note.txt"}

        def after_tool_call(self, context, result):
            calls.append(("after", result.canonical_id, result.output))
            return result

        def after_turn(self, context):
            calls.append(("turn", context.final_answer))

    class FakeClient:
        def __init__(self):
            self.requests = []

        def chat(self, messages, tools):
            self.requests.append({"messages": messages, "tools": tools})
            if len(self.requests) == 1:
                assert "PLUGIN PROMPT" in messages[0]["content"]
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call-1",
                            "type": "function",
                            "function": {
                                "name": "workspace__read_file",
                                "arguments": '{"path":"wrong.txt"}',
                            },
                        }
                    ],
                }
            assert messages[-1]["content"] == "hello from file"
            return {"content": "done"}

    manager = PluginManager([HookPlugin()])
    registry = create_default_tool_registry(
        tmp_path,
        permission_policy=PermissionPolicy(tmp_path, mode="allow"),
        plugin_manager=manager,
    )
    loop = AgentTurnLoop(client=FakeClient(), tools=registry, plugin_manager=manager)

    result, _context = loop.run_turn("read the note")

    assert result.status is AgentStatus.SUCCESS
    assert ("before", "workspace.read_file", {"path": "wrong.txt"}) in calls
    assert ("after", "workspace.read_file", "hello from file") in calls
    assert ("turn", "done") in calls


def test_plugin_sources_feed_proactive_loader(tmp_path) -> None:
    class SourcePlugin(Plugin):
        name = "source"

        def proactive_sources(self):
            return [
                {
                    "type": "static",
                    "channel": "alert",
                    "name": "plugin-source",
                    "events": [{"event_id": "p1", "title": "Plugin event"}],
                }
            ]

    loader = ProactiveSourceLoader(
        tmp_path / "missing.json",
        plugin_manager=PluginManager([SourcePlugin()]),
    )

    events = loader.load_events()

    assert len(events) == 1
    assert events[0].event_id == "p1"
    assert events[0].source_name == "plugin-source"
