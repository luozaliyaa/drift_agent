"""Shared Drift runner data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


MessageResult = Literal["sent", "silent"]


@dataclass(frozen=True)
class DriftConfig:
    enabled: bool = True
    drift_dir: Path = Path("drift")
    min_interval_hours: float = 1.0
    max_steps: int = 30
    permission_mode: str = "deny"


@dataclass(frozen=True)
class DriftSkill:
    name: str
    description: str
    path: Path
    body: str
    requires_mcp: list[str] = field(default_factory=list)
    enabled: bool = True


@dataclass(frozen=True)
class DriftRunRecord:
    skill: str
    run_at: str
    one_line: str
    message_result: MessageResult


@dataclass(frozen=True)
class DriftResult:
    completed: bool
    message_result: MessageResult = "silent"
    message: str = ""
    one_line: str = ""
    skill: str = ""
    reason: str = ""

    @property
    def should_send(self) -> bool:
        return self.completed and self.message_result == "sent" and bool(self.message)
