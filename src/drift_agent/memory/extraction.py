"""Conservative memory extraction heuristics."""

from __future__ import annotations

import re

from drift_agent.memory.markdown_store import slugify
from drift_agent.memory.types import MemoryItem


EXPLICIT_MARKERS = [
    "remember",
    "记住",
    "记忆",
    "以后都",
    "以后请",
    "always",
]

PREFERENCE_MARKERS = [
    "i prefer",
    "我喜欢",
    "我偏好",
    "prefer",
    "不要",
    "别",
]


def extract_memory_items(user_prompt: str, assistant_answer: str = "") -> list[MemoryItem]:
    prompt = user_prompt.strip()
    if not prompt:
        return []

    lowered = prompt.lower()
    explicit = any(marker in lowered or marker in prompt for marker in EXPLICIT_MARKERS)
    preference = any(marker in lowered or marker in prompt for marker in PREFERENCE_MARKERS)
    if not explicit and not preference:
        return []

    mem_type = "user" if preference or explicit else "project"
    description = summarize_description(prompt)
    name = slugify(description)
    body = prompt
    if assistant_answer:
        body += "\n\nObserved response context:\n" + assistant_answer[:1000]
    return [
        MemoryItem(
            name=name,
            type=mem_type,
            description=description,
            body=body,
        )
    ]


def summarize_description(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = cleaned.strip("。.!?？")
    if len(cleaned) <= 80:
        return cleaned
    return cleaned[:77] + "..."
