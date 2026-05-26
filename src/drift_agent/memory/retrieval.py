"""Relevant memory retrieval."""

from __future__ import annotations

import re

from drift_agent.memory.types import MemoryItem


def select_relevant_memories(
    query: str,
    items: list[MemoryItem],
    max_items: int = 5,
    max_chars_per_item: int = 4096,
) -> list[MemoryItem]:
    scored = []
    for item in items:
        score = score_memory(query, item)
        if score > 0:
            scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1].name))
    return [truncate_item(item, max_chars_per_item) for _, item in scored[:max_items]]


def score_memory(query: str, item: MemoryItem) -> int:
    haystack = f"{item.name} {item.description} {item.body}".lower()
    query_lower = query.lower()
    score = 0
    for token in tokens(query_lower):
        if token in haystack:
            score += 3 if token in f"{item.name} {item.description}".lower() else 1
    if query_lower.strip() and query_lower.strip() in haystack:
        score += 5
    return score


def tokens(text: str) -> list[str]:
    ascii_tokens = re.findall(r"[a-zA-Z0-9_]{3,}", text)
    cjk_tokens = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    return ascii_tokens + cjk_tokens


def truncate_item(item: MemoryItem, max_chars: int) -> MemoryItem:
    body = item.body
    lines = body.splitlines()
    if len(lines) > 200:
        body = "\n".join(lines[:200]) + f"\n... ({len(lines) - 200} more lines)"
    if len(body) > max_chars:
        body = body[:max_chars] + "\n... (memory truncated)"
    return MemoryItem(
        name=item.name,
        type=item.type,
        description=item.description,
        body=body,
        path=item.path,
    )
