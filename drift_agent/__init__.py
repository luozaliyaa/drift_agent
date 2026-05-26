"""Development import shim for running from the repository root.

The installable package lives under src/drift_agent. This shim lets
`python -m drift_agent.cli` work before an editable install is performed.
"""

from __future__ import annotations

from pathlib import Path

_SRC_PACKAGE = Path(__file__).resolve().parent.parent / "src" / "drift_agent"
if _SRC_PACKAGE.exists():
    __path__.append(str(_SRC_PACKAGE))

from drift_agent.loop import (  # noqa: E402
    AgentEvent,
    AgentLoop,
    AgentState,
    AgentStatus,
    StepResult,
    StubPlanner,
)

__all__ = [
    "AgentEvent",
    "AgentLoop",
    "AgentState",
    "AgentStatus",
    "StepResult",
    "StubPlanner",
]
