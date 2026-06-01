"""Bounded Drift agent runner."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from drift_agent.drift.skills import DriftSkillScanner
from drift_agent.drift.state import DriftStateStore, utc_now
from drift_agent.drift.tools import DriftToolSet
from drift_agent.drift.types import DriftConfig, DriftResult, DriftRunRecord, DriftSkill
from drift_agent.memory import MemoryManager


class ChatClient(Protocol):
    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> dict[str, Any]:
        ...


class DriftRunner:
    def __init__(
        self,
        *,
        config: DriftConfig,
        client: ChatClient | None = None,
        memory_manager: MemoryManager | None = None,
        workdir: str | Path | None = None,
        scanner: DriftSkillScanner | None = None,
        state: DriftStateStore | None = None,
    ) -> None:
        self.config = config
        self.client = client
        self.memory_manager = memory_manager
        self.workdir = Path(workdir or Path.cwd()).resolve()
        self.scanner = scanner or DriftSkillScanner(config.drift_dir)
        self.state = state or DriftStateStore(config.drift_dir)

    def maybe_run(self) -> DriftResult:
        if not self.config.enabled:
            return DriftResult(False, reason="drift disabled")
        if self.client is None:
            return DriftResult(False, reason="no drift LLM client")
        if not self.state.can_run(self.config.min_interval_hours):
            return DriftResult(False, reason="drift interval not elapsed")
        skills = self.scanner.scan()
        if not skills:
            return DriftResult(False, reason="no drift skills")
        return self.run(skills)

    def run(self, skills: list[DriftSkill]) -> DriftResult:
        toolset = DriftToolSet(
            workdir=self.workdir,
            drift_dir=self.config.drift_dir,
            permission_mode=self.config.permission_mode,
            memory_manager=self.memory_manager,
            enable_web_tools=True,
        )
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": DRIFT_SYSTEM_PROMPT},
            {"role": "user", "content": self._build_context(skills)},
        ]
        for _ in range(self.config.max_steps):
            message = self.client.chat(messages, toolset.as_openai_tools())
            messages.append(assistant_message(message))
            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                break
            for tool_call in tool_calls:
                function = tool_call.get("function") or {}
                tool_name = str(function.get("name") or "")
                arguments = function.get("arguments")
                result = toolset.dispatch(tool_name, arguments)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id"),
                        "name": tool_name,
                        "content": result.output,
                    }
                )
                if toolset.finished:
                    return self._finish(toolset)
        return DriftResult(False, reason="drift did not call finish_drift")

    def _finish(self, toolset: DriftToolSet) -> DriftResult:
        payload = toolset.finish_payload or {}
        message_result = str(payload.get("message_result") or "silent")
        if message_result not in {"sent", "silent"}:
            return DriftResult(False, reason="invalid finish payload")
        one_line = str(payload.get("one_line") or "").strip()
        skill = str(payload.get("skill") or "").strip() or infer_skill_from_summary(one_line)
        record = DriftRunRecord(
            skill=skill,
            run_at=utc_now(),
            one_line=one_line or "Drift run completed.",
            message_result=message_result,  # type: ignore[arg-type]
        )
        self.state.record_run(record)
        return DriftResult(
            completed=True,
            message_result=message_result,  # type: ignore[arg-type]
            message=toolset.message,
            one_line=record.one_line,
            skill=record.skill,
        )

    def _build_context(self, skills: list[DriftSkill]) -> str:
        recent_runs = self.state.recent_runs(limit=10)
        note = self.state.read_note()
        memory_prompt = ""
        if self.memory_manager is not None:
            memory_prompt = self.memory_manager.load_prompt_context("drift background run").to_prompt()
        skill_text = "\n\n".join(
            format_skill(skill, self.state.skill_state_path(skill.name))
            for skill in skills
        )
        return (
            "Available Drift skills:\n"
            + skill_text
            + "\n\nRecent Drift runs:\n"
            + json.dumps(recent_runs, ensure_ascii=False, indent=2)
            + "\n\nDrift note:\n"
            + (note or "(none)")
            + "\n\nMemory context:\n"
            + (memory_prompt or "(none)")
        )


DRIFT_SYSTEM_PROMPT = """You are Drift Agent's background task runner.
Pick one available Drift skill and execute it by following its SKILL.md.

Rules:
- Reconsider all skills every run; do not automatically continue the last one.
- You may call message_push at most once.
- After message_push, only write_file, edit_file, and finish_drift are allowed.
- You must finish by calling finish_drift with the chosen skill name and
  message_result="sent" if you called message_push, otherwise "silent".
- Keep file writes inside the drift directory.
- If no useful background task exists, call finish_drift with silent.
"""


def format_skill(skill: DriftSkill, state_path: Path) -> str:
    return (
        f"## {skill.name}\n"
        f"description: {skill.description}\n"
        f"path: {skill.path}\n\n"
        f"state_path: {state_path}\n\n"
        f"{skill.body}"
    )


def assistant_message(message: dict[str, Any]) -> dict[str, Any]:
    assistant = {"role": "assistant", "content": message.get("content") or ""}
    if message.get("tool_calls"):
        assistant["tool_calls"] = message["tool_calls"]
    return assistant


def infer_skill_from_summary(summary: str) -> str:
    if ":" in summary:
        return summary.split(":", 1)[0].strip() or "unknown"
    return "unknown"
