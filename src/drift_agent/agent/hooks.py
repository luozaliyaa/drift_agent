"""Phase hook protocol for future runtime extensions."""

from __future__ import annotations

from typing import Protocol

from drift_agent.agent.context import TurnContext
from drift_agent.agent.phases import TurnPhase


class PhaseHook(Protocol):
    def before_phase(self, phase: TurnPhase, context: TurnContext) -> None:
        ...

    def after_phase(self, phase: TurnPhase, context: TurnContext) -> None:
        ...


class NoopPhaseHook:
    def before_phase(self, phase: TurnPhase, context: TurnContext) -> None:
        return None

    def after_phase(self, phase: TurnPhase, context: TurnContext) -> None:
        return None
