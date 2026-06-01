"""Shared proactive push data types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


ProactiveChannel = Literal["alert", "content", "context"]
ProactiveDecisionKind = Literal["reply", "skip"]


@dataclass(frozen=True)
class ProactiveConfig:
    enabled: bool = False
    profile: str = "daily"
    context_path: Path = Path("PROACTIVE_CONTEXT.md")
    sources_path: Path = Path("proactive_sources.json")
    context_prob: float = 0.03
    delivery_cooldown_seconds: float = 0.0


@dataclass(frozen=True)
class ProactiveSource:
    type: str
    channel: ProactiveChannel
    enabled: bool = True
    path: Path | None = None
    events: list[dict[str, Any]] = field(default_factory=list)
    name: str = ""


@dataclass(frozen=True)
class ProactiveEvent:
    event_id: str
    kind: ProactiveChannel
    title: str
    content: str = ""
    source_name: str = ""
    url: str = ""
    published_at: str = ""
    severity: str = ""
    display_text: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    def compact(self) -> str:
        source = f"{self.source_name}: " if self.source_name else ""
        body = self.display_text or self.content
        if body:
            return f"[{self.kind}] {source}{self.title} - {body}"
        return f"[{self.kind}] {source}{self.title}"


@dataclass(frozen=True)
class ProactiveDecision:
    decision: ProactiveDecisionKind
    message: str = ""
    evidence: list[str] = field(default_factory=list)
    reason: str = ""

    @property
    def should_send(self) -> bool:
        return self.decision == "reply" and bool(self.message.strip())


@dataclass(frozen=True)
class DeliveryResult:
    sent: bool
    message: str = ""
    reason: str = ""
