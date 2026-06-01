"""Proactive context file handling."""

from __future__ import annotations

from pathlib import Path


DEFAULT_PROACTIVE_CONTEXT = (
    "# Proactive Context\n\n"
    "## Rules\n\n"
    "- Only send proactive notices when the message is clearly useful now.\n"
)


def read_proactive_context(path: str | Path) -> str:
    context_path = Path(path)
    if not context_path.exists():
        context_path.write_text(DEFAULT_PROACTIVE_CONTEXT, encoding="utf-8")
    return context_path.read_text(encoding="utf-8").strip()
