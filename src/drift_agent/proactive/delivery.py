"""Proactive delivery helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from drift_agent.proactive.types import DeliveryResult, ProactiveDecision
from drift_agent.runtime.events import RuntimeEvent


class TerminalDelivery:
    def __init__(self, cooldown_seconds: float = 0.0) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._last_message = ""
        self._last_sent_at: datetime | None = None

    def deliver(self, decision: ProactiveDecision) -> tuple[DeliveryResult, RuntimeEvent | None]:
        if not decision.should_send:
            return DeliveryResult(False, reason=decision.reason or "skip"), None
        message = decision.message.strip()
        if self._last_message == normalize_message(message):
            return DeliveryResult(False, message=message, reason="duplicate"), None
        now = datetime.now(UTC)
        if self._last_sent_at is not None:
            elapsed = (now - self._last_sent_at).total_seconds()
            if elapsed < self.cooldown_seconds:
                return DeliveryResult(False, message=message, reason="cooldown"), None
        self._last_message = normalize_message(message)
        self._last_sent_at = now
        return DeliveryResult(True, message=message), RuntimeEvent.system_notice(message)


def normalize_message(message: str) -> str:
    return " ".join(message.lower().split())
