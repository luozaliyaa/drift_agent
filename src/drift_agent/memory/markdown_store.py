"""Markdown-backed long-term memory store."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path

from drift_agent.memory.types import MemoryItem


ALLOWED_TYPES = {"user", "feedback", "project", "reference"}


class MarkdownMemoryStore:
    def __init__(self, memory_dir: str | Path = ".memory") -> None:
        self.memory_dir = Path(memory_dir)
        self.items_dir = self.memory_dir / "items"
        self.index_path = self.memory_dir / "MEMORY.md"
        self.readme_path = self.memory_dir / "README.md"
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_readme()
        if not self.index_path.exists():
            self.rebuild_index()

    def read_index(self) -> str:
        if not self.index_path.exists():
            return ""
        return self.index_path.read_text(encoding="utf-8").strip()

    def list_items(self) -> list[MemoryItem]:
        items = []
        for path in sorted(self.items_dir.glob("*.md")):
            items.append(self.read_item(path))
        return items

    def read_item(self, path: str | Path) -> MemoryItem:
        item_path = Path(path)
        if not item_path.is_absolute():
            item_path = self.items_dir / item_path
        raw = item_path.read_text(encoding="utf-8")
        meta, body = parse_frontmatter(raw)
        return MemoryItem(
            name=meta.get("name", item_path.stem),
            type=meta.get("type", "user"),
            description=meta.get("description", body.splitlines()[0][:80] if body else ""),
            body=body,
            path=item_path,
        )

    def write_item(self, item: MemoryItem) -> Path:
        name = slugify(item.name)
        mem_type = item.type if item.type in ALLOWED_TYPES else "user"
        path = self.items_dir / f"{name}.md"
        now = datetime.now(UTC).isoformat(timespec="seconds")
        previous_created_at = now
        if path.exists():
            meta, _ = parse_frontmatter(path.read_text(encoding="utf-8"))
            previous_created_at = meta.get("created_at", now)

        content = (
            "---\n"
            f"name: {name}\n"
            f"type: {mem_type}\n"
            f"description: {sanitize_frontmatter_value(item.description)}\n"
            f"created_at: {previous_created_at}\n"
            f"updated_at: {now}\n"
            "---\n\n"
            f"{item.body.strip()}\n"
        )
        path.write_text(content, encoding="utf-8")
        self.rebuild_index()
        return path

    def rebuild_index(self) -> None:
        lines = ["# Memory Index", ""]
        for item in self.list_items() if self.items_dir.exists() else []:
            filename = item.path.name if item.path else f"{slugify(item.name)}.md"
            lines.append(f"- [{item.name}](items/{filename}) - {item.description}")
        if len(lines) == 2:
            lines.append("_No memories yet._")
        self.index_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _ensure_readme(self) -> None:
        if self.readme_path.exists():
            return
        self.readme_path.write_text(
            "# drift-agent memory\n\n"
            "- `MEMORY.md`: index injected into the model prompt.\n"
            "- `items/*.md`: long-term Markdown memories.\n"
            "- `context.sqlite3`: SQLite session context.\n",
            encoding="utf-8",
        )


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text.strip()
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text.strip()
    meta: dict[str, str] = {}
    for line in parts[1].strip().splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip('"').strip("'")
    return meta, parts[2].strip()


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "-", value.strip().lower())
    slug = slug.strip("-")
    return slug or "memory"


def sanitize_frontmatter_value(value: str) -> str:
    return value.replace("\n", " ").replace("\r", " ").strip()
