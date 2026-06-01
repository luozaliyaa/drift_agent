# Plugin System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight Akashic-style plugin system to drift-agent so features can be installed under `plugins/*/plugin.py` without editing core agent code.

**Architecture:** Implement a `PluginManager` that discovers local plugin modules and exposes prompt sections, tools, tool hooks, after-turn hooks, and proactive sources. Wire the manager into `AgentTurnLoop`, `ToolRegistry`, `ProactiveSourceLoader`, and the CLI.

**Tech Stack:** Python 3.11 stdlib importlib/pathlib, existing ToolSpec/ToolRegistry, pytest.

---

### Task 1: Core Plugin API

**Files:**
- Create: `src/drift_agent/plugins/__init__.py`
- Create: `src/drift_agent/plugins/api.py`
- Create: `src/drift_agent/plugins/manager.py`
- Test: `tests/test_plugins.py`

- [ ] Define `Plugin`, `ToolHookContext`, `ToolHookResult`, and `PluginToolProvider`.
- [ ] Discover `plugins/*/plugin.py` modules.
- [ ] Instantiate exported `Plugin` subclasses or `plugin` instances.
- [ ] Isolate failed plugin imports/initialization.

### Task 2: Agent Loop Integration

**Files:**
- Modify: `src/drift_agent/agent/loop.py`
- Modify: `src/drift_agent/deepseek.py`
- Modify: `src/drift_agent/tools/registry.py`
- Test: `tests/test_agent_turn_loop.py`
- Test: `tests/test_tool_registry.py`

- [ ] Inject plugin prompt sections into the system prompt.
- [ ] Run `before_tool_call` hooks before dispatch.
- [ ] Run `after_tool_call` hooks after dispatch.
- [ ] Run `after_turn` hooks after memory recording.
- [ ] Register plugin tools in the default registry.

### Task 3: CLI And Proactive Integration

**Files:**
- Modify: `src/drift_agent/cli.py`
- Modify: `src/drift_agent/proactive/sources.py`
- Test: `tests/test_cli.py`
- Test: `tests/test_proactive_sources.py`

- [ ] Add `--plugins on|off` and `--plugins-dir`.
- [ ] Load plugins once in live/stub CLI paths.
- [ ] Allow plugins to contribute proactive sources.

### Task 4: Docs And Verification

**Files:**
- Modify: `README.md`

- [ ] Document minimal plugin examples.
- [ ] Run `pytest` and `git diff --check`.
