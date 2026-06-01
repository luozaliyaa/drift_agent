"""Plugin discovery and dispatch."""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from drift_agent.plugins.api import Plugin, ToolHookContext, ToolHookResult
from drift_agent.proactive.sources import parse_source
from drift_agent.proactive.types import ProactiveSource
from drift_agent.tools.base import ToolCallResult, ToolProvider, ToolSpec


class PluginManager:
    def __init__(self, plugins: list[Plugin] | None = None) -> None:
        self.plugins = plugins or []
        self.errors: list[str] = []

    @classmethod
    def discover(cls, plugins_dir: str | Path = "plugins", enabled: bool = True) -> "PluginManager":
        manager = cls()
        if not enabled:
            return manager
        root = Path(plugins_dir)
        if not root.exists():
            return manager
        for plugin_file in sorted(root.glob("*/plugin.py")):
            manager._load_plugin_file(plugin_file)
        return manager

    @property
    def enabled(self) -> bool:
        return bool(self.plugins)

    def prompt_sections(self) -> list[str]:
        sections: list[str] = []
        for plugin in self.plugins:
            try:
                sections.extend(str(section) for section in plugin.prompt_sections() if section)
            except Exception as exc:
                self.errors.append(f"{plugin_name(plugin)} prompt_sections failed: {exc}")
        return sections

    def before_tool_call(self, context: ToolHookContext) -> ToolHookResult | None:
        for plugin in self.plugins:
            try:
                outcome = plugin.before_tool_call(context)
            except Exception as exc:
                self.errors.append(f"{plugin_name(plugin)} before_tool_call failed: {exc}")
                continue
            normalized = normalize_hook_result(outcome)
            if normalized is None:
                continue
            if normalized.arguments is not None:
                context.arguments = normalized.arguments
            if normalized.decision in {"deny", "replace"}:
                return normalized
        return None

    def after_tool_call(
        self,
        context: ToolHookContext,
        result: ToolCallResult,
    ) -> ToolCallResult:
        current = result
        for plugin in self.plugins:
            try:
                replacement = plugin.after_tool_call(context, current)
            except Exception as exc:
                self.errors.append(f"{plugin_name(plugin)} after_tool_call failed: {exc}")
                continue
            if replacement is not None:
                current = replacement
        return current

    def after_turn(self, context: object) -> None:
        for plugin in self.plugins:
            try:
                plugin.after_turn(context)
            except Exception as exc:
                self.errors.append(f"{plugin_name(plugin)} after_turn failed: {exc}")

    def proactive_sources(self) -> list[ProactiveSource]:
        sources: list[ProactiveSource] = []
        for plugin in self.plugins:
            try:
                raw_sources = plugin.proactive_sources()
            except Exception as exc:
                self.errors.append(f"{plugin_name(plugin)} proactive_sources failed: {exc}")
                continue
            for raw in raw_sources:
                if isinstance(raw, ProactiveSource):
                    sources.append(raw)
                elif (source := parse_source(raw)) is not None:
                    sources.append(source)
        return sources

    def _load_plugin_file(self, plugin_file: Path) -> None:
        module_name = "drift_agent_local_plugin_" + safe_module_suffix(plugin_file.parent.name)
        try:
            module = import_plugin_module(module_name, plugin_file)
            plugins = instantiate_plugins(module)
            for plugin in plugins:
                if not getattr(plugin, "enabled", True):
                    continue
                plugin.initialize(plugin_file.parent)
                self.plugins.append(plugin)
        except Exception as exc:
            self.errors.append(f"{plugin_file}: {exc}")


class PluginToolProvider(ToolProvider):
    namespace = "plugin"

    def __init__(self, manager: PluginManager) -> None:
        self.manager = manager
        self._tool_plugins: dict[str, Plugin] = {}

    def list_tools(self) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        for plugin in self.manager.plugins:
            try:
                plugin_specs = plugin.tools()
            except Exception as exc:
                self.manager.errors.append(f"{plugin_name(plugin)} tools failed: {exc}")
                continue
            for spec in plugin_specs:
                normalized = ToolSpec(
                    canonical_id=spec.canonical_id,
                    provider=spec.provider or self.namespace,
                    aliases=spec.aliases,
                    description=spec.description,
                    parameters=spec.parameters,
                    handler=spec.handler,
                    enabled=spec.enabled,
                    always_on=False,
                    risk=spec.risk if spec.risk != "read-only" else "unknown",
                    search_hint=spec.search_hint,
                    category=spec.category or "plugin",
                )
                self._tool_plugins[normalized.canonical_id] = plugin
                specs.append(normalized)
        return specs

    def call_tool(self, canonical_id: str, arguments: dict[str, Any]) -> ToolCallResult:
        plugin = self._tool_plugins.get(canonical_id)
        if plugin is None:
            return ToolCallResult(canonical_id, f"Error: Unknown plugin tool: {canonical_id}", True)
        try:
            return plugin.call_tool(canonical_id, arguments)
        except Exception as exc:
            return ToolCallResult(canonical_id, f"Error: {exc}", True)


def import_plugin_module(module_name: str, plugin_file: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, plugin_file)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot import plugin file: {plugin_file}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def instantiate_plugins(module: ModuleType) -> list[Plugin]:
    explicit = getattr(module, "plugin", None)
    if isinstance(explicit, Plugin):
        return [explicit]
    plugins: list[Plugin] = []
    for value in vars(module).values():
        if isinstance(value, type) and issubclass(value, Plugin) and value is not Plugin:
            plugins.append(value())
    return plugins


def normalize_hook_result(outcome: ToolHookResult | dict[str, Any] | None) -> ToolHookResult | None:
    if outcome is None:
        return None
    if isinstance(outcome, ToolHookResult):
        return outcome
    if isinstance(outcome, dict):
        if "decision" in outcome:
            return ToolHookResult(
                decision=str(outcome.get("decision") or "allow"),
                reason=str(outcome.get("reason") or ""),
                arguments=outcome.get("arguments") if isinstance(outcome.get("arguments"), dict) else None,
                output=str(outcome.get("output") or ""),
            )
        return ToolHookResult.allow(dict(outcome))
    return None


def plugin_name(plugin: Plugin) -> str:
    return plugin.name or plugin.__class__.__name__


def safe_module_suffix(name: str) -> str:
    suffix = re.sub(r"\W+", "_", name).strip("_")
    return suffix or "plugin"
