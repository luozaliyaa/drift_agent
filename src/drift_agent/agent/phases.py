"""Agent turn phase definitions."""

from __future__ import annotations

from enum import Enum


class TurnPhase(str, Enum):
    BEFORE_TURN = "BeforeTurn"
    BEFORE_REASONING = "BeforeReasoning"
    PROMPT_RENDER = "PromptRender"
    REASONER = "Reasoner"
    AFTER_REASONING = "AfterReasoning"
    AFTER_TURN = "AfterTurn"


TURN_PHASES: tuple[TurnPhase, ...] = (
    TurnPhase.BEFORE_TURN,
    TurnPhase.BEFORE_REASONING,
    TurnPhase.PROMPT_RENDER,
    TurnPhase.REASONER,
    TurnPhase.AFTER_REASONING,
    TurnPhase.AFTER_TURN,
)
