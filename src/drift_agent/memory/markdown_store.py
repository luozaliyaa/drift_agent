"""Markdown-backed long-term memory store."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from drift_agent.memory.types import HistoryEntry, MemoryItem, PendingItem, RecentContext


ALLOWED_TYPES = {"user", "feedback", "project", "reference"}
DEFAULT_SELF = (
    "# Drift Agent Self Model\n\n"
    "- Drift Agent is a concise coding agent working in the current workspace.\n"
)
DEFAULT_MEMORY = "# Long-term Memory\n\n_No long-term memories yet._\n"
DEFAULT_RECENT_CONTEXT = (
    "# Recent Context\n\n"
    "## Compression\n\n"
    "## Ongoing Threads\n\n"
    "## Recent Turns\n"
)


class MarkdownMemoryStore:
    def __init__(self, memory_dir: str | Path = ".memory") -> None:
        self.memory_dir = Path(memory_dir)
        self.items_dir = self.memory_dir / "items"
        self.index_path = self.memory_dir / "MEMORY.md"
        self.self_path = self.memory_dir / "SELF.md"
        self.history_path = self.memory_dir / "HISTORY.md"
        self.recent_context_path = self.memory_dir / "RECENT_CONTEXT.md"
        self.pending_path = self.memory_dir / "PENDING.md"
        self.pending_snapshot_path = self.memory_dir / "PENDING.snapshot.md"
        self.journal_dir = self.memory_dir / "journal"
        self.readme_path = self.memory_dir / "README.md"
        self.items_dir.mkdir(parents=True, exist_ok=True)
        self.journal_dir.mkdir(parents=True, exist_ok=True)
        self._ensure_readme()
        self._ensure_akashic_files()
        if not self.index_path.exists():
            self.write_index(DEFAULT_MEMORY)

    def read_index(self) -> str:
        if not self.index_path.exists():
            return ""
        return self.index_path.read_text(encoding="utf-8").strip()

    def write_index(self, content: str) -> None:
        self._atomic_write(self.index_path, content.strip() + "\n")

    def read_self(self) -> str:
        if not self.self_path.exists():
            return ""
        return self.self_path.read_text(encoding="utf-8").strip()

    def write_self(self, content: str) -> None:
        self._atomic_write(self.self_path, content.strip() + "\n")

    def read_recent_context(self) -> RecentContext:
        if not self.recent_context_path.exists():
            return RecentContext()
        text = self.recent_context_path.read_text(encoding="utf-8")
        return parse_recent_context(text)

    def write_recent_context(self, recent: RecentContext) -> None:
        lines = ["# Recent Context", "", "## Compression"]
        if recent.until:
            lines.append(f"until: {recent.until}")
        lines.extend(f"- {line}" for line in recent.compression)
        lines.extend(["", "## Ongoing Threads"])
        lines.extend(f"- {line}" for line in recent.ongoing_threads)
        lines.extend(["", "## Recent Turns"])
        for user_prompt, assistant_answer in recent.recent_turns:
            lines.append(f"[user] {compact_line(user_prompt, 500)}")
            lines.append(f"[assistant] {compact_line(assistant_answer, 500)}")
        self._atomic_write(self.recent_context_path, "\n".join(lines).rstrip() + "\n")

    def refresh_recent_turns(self, recent_turns: list[tuple[str, str]]) -> None:
        current = self.read_recent_context()
        self.write_recent_context(
            RecentContext(
                compression=current.compression,
                ongoing_threads=current.ongoing_threads,
                recent_turns=recent_turns,
                until=current.until,
            )
        )

    def append_history_entries(
        self,
        entries: list[HistoryEntry],
        source_ref: tuple[str, ...],
    ) -> list[str]:
        written: list[str] = []
        existing = self._read_text(self.history_path)
        marker = consolidation_marker(source_ref, "history_entry")
        if marker in existing:
            return written

        now = datetime.now(UTC)
        date_key = now.date().isoformat()
        journal_path = self.journal_dir / f"{date_key}.md"
        history_lines: list[str] = []
        for entry in entries:
            occurred_at = entry.occurred_at or now.isoformat(timespec="minutes")
            line = f"{marker} [{occurred_at}] {entry.summary.strip()}"
            history_lines.append(line)
            written.append(entry.summary.strip())
        if history_lines:
            self._append_lines(self.history_path, history_lines)
            self._append_lines(journal_path, history_lines)
        return written

    def append_pending_items(
        self,
        items: list[PendingItem],
        source_ref: tuple[str, ...],
    ) -> list[str]:
        written: list[str] = []
        existing = self._read_text(self.pending_path)
        marker = consolidation_marker(source_ref, "pending_item")
        if marker in existing:
            return written

        lines: list[str] = []
        for item in items:
            tag = item.normalized_tag()
            content = item.content.strip()
            if not content:
                continue
            lines.append(f"{marker} - [{tag}] {content}")
            written.append(f"{tag}:{content}")
        if lines:
            self._append_lines(self.pending_path, lines)
        return written

    def read_pending_text(self) -> str:
        return self._read_text(self.pending_path).strip()

    def read_pending_items(self) -> list[PendingItem]:
        pending: list[PendingItem] = []
        for line in self._read_text(self.pending_path).splitlines():
            cleaned = strip_consolidation_marker(line).strip()
            match = re.match(r"- \[([^\]]+)\]\s*(.+)", cleaned)
            if not match:
                continue
            pending.append(PendingItem(tag=match.group(1), content=match.group(2)))
        return pending

    def clear_pending(self) -> None:
        self._atomic_write(self.pending_path, "# Pending Memory\n")

    def snapshot_pending(self) -> None:
        self._atomic_write(self.pending_snapshot_path, self._read_text(self.pending_path))

    def commit_pending_snapshot(self) -> None:
        self.clear_pending()
        if self.pending_snapshot_path.exists():
            self.pending_snapshot_path.unlink()

    def rollback_pending_snapshot(self) -> None:
        if not self.pending_snapshot_path.exists():
            return
        snapshot = self.pending_snapshot_path.read_text(encoding="utf-8")
        current = self._read_text(self.pending_path)
        if snapshot and snapshot not in current:
            merged = snapshot.rstrip() + "\n" + current
            self._atomic_write(self.pending_path, merged)
        self.pending_snapshot_path.unlink()

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
        self._atomic_write(path, content)
        self.rebuild_index()
        return path

    def rebuild_index(self) -> None:
        lines = ["# Long-term Memory", ""]
        for item in self.list_items() if self.items_dir.exists() else []:
            filename = item.path.name if item.path else f"{slugify(item.name)}.md"
            lines.append(f"- [{item.name}](items/{filename}) - {item.description}")
        if len(lines) == 2:
            lines.append("_No memories yet._")
        self._atomic_write(self.index_path, "\n".join(lines) + "\n")

    def _ensure_readme(self) -> None:
        if self.readme_path.exists():
            return
        self._atomic_write(
            self.readme_path,
            "# drift-agent memory\n\n"
            "- `SELF.md`: compact agent self model injected into the prompt.\n"
            "- `MEMORY.md`: compact long-term memory injected into the prompt.\n"
            "- `RECENT_CONTEXT.md`: compressed recent context and recent turns.\n"
            "- `HISTORY.md`: append-only timeline events.\n"
            "- `PENDING.md`: buffered facts waiting for optimizer archival.\n"
            "- `journal/YYYY-MM-DD.md`: daily timeline mirror.\n"
            "- `context.sqlite3`: session context and consolidation metadata.\n"
            "- `memory2.sqlite3`: semantic memory records and embeddings.\n",
        )

    def _ensure_akashic_files(self) -> None:
        defaults = {
            self.self_path: DEFAULT_SELF,
            self.index_path: DEFAULT_MEMORY,
            self.history_path: "# History\n",
            self.pending_path: "# Pending Memory\n",
            self.recent_context_path: DEFAULT_RECENT_CONTEXT,
        }
        for path, content in defaults.items():
            if not path.exists():
                self._atomic_write(path, content)
        self.rollback_pending_snapshot()

    def _append_lines(self, path: Path, lines: list[str]) -> None:
        if not lines:
            return
        existing = self._read_text(path)
        prefix = "" if not existing or existing.endswith("\n") else "\n"
        self._atomic_write(path, existing + prefix + "\n".join(lines) + "\n")

    def _read_text(self, path: Path) -> str:
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)


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


def consolidation_marker(source_ref: tuple[str, ...], kind: str) -> str:
    encoded = json.dumps(list(source_ref), ensure_ascii=False, sort_keys=True)
    return f"<!-- consolidation:{encoded}:{kind} -->"


def strip_consolidation_marker(line: str) -> str:
    return re.sub(r"^<!-- consolidation:.*? -->\s*", "", line)


def parse_recent_context(text: str) -> RecentContext:
    section = ""
    until = ""
    compression: list[str] = []
    ongoing: list[str] = []
    recent_turns: list[tuple[str, str]] = []
    pending_user: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("## "):
            section = line.removeprefix("## ").strip()
            continue
        if not line:
            continue
        if section == "Compression":
            if line.startswith("until:"):
                until = line.split(":", 1)[1].strip()
            elif line.startswith("- "):
                compression.append(line[2:].strip())
        elif section == "Ongoing Threads" and line.startswith("- "):
            ongoing.append(line[2:].strip())
        elif section == "Recent Turns":
            if line.startswith("[user]"):
                pending_user = line.removeprefix("[user]").strip()
            elif line.startswith("[assistant]") and pending_user is not None:
                recent_turns.append(
                    (pending_user, line.removeprefix("[assistant]").strip())
                )
                pending_user = None
    return RecentContext(
        compression=compression,
        ongoing_threads=ongoing,
        recent_turns=recent_turns,
        until=until,
    )


def compact_line(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    return cleaned[:max_chars] + "... (truncated)"
