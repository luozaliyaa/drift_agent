"""Drift skill discovery."""

from __future__ import annotations

from pathlib import Path

from drift_agent.drift.types import DriftSkill


class DriftSkillScanner:
    def __init__(
        self,
        drift_dir: str | Path = "drift",
        available_mcp_servers: set[str] | None = None,
    ) -> None:
        self.drift_dir = Path(drift_dir)
        self.skills_dir = self.drift_dir / "skills"
        self.available_mcp_servers = available_mcp_servers or set()

    def scan(self) -> list[DriftSkill]:
        if not self.skills_dir.exists():
            return []
        skills: list[DriftSkill] = []
        for path in sorted(self.skills_dir.glob("*/SKILL.md")):
            skill = parse_skill(path)
            if skill is None or not skill.enabled:
                continue
            if any(server not in self.available_mcp_servers for server in skill.requires_mcp):
                continue
            skills.append(skill)
        return skills


def parse_skill(path: Path) -> DriftSkill | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    meta, body = parse_frontmatter(raw)
    name = meta.get("name") or path.parent.name
    description = meta.get("description", "")
    enabled = parse_bool(meta.get("enabled", "true"))
    requires_mcp = parse_list(meta.get("requires_mcp", ""))
    if not name or not body.strip():
        return None
    return DriftSkill(
        name=name,
        description=description,
        path=path,
        body=body.strip(),
        requires_mcp=requires_mcp,
        enabled=enabled,
    )


def parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    meta: dict[str, str] = {}
    for line in parts[1].splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip().strip("\"'")
    return meta, parts[2]


def parse_bool(value: str) -> bool:
    return value.strip().lower() not in {"false", "0", "no", "disabled"}


def parse_list(value: str) -> list[str]:
    cleaned = value.strip()
    if not cleaned:
        return []
    if cleaned.startswith("[") and cleaned.endswith("]"):
        cleaned = cleaned[1:-1]
    return [
        part.strip().strip("\"'")
        for part in cleaned.split(",")
        if part.strip().strip("\"'")
    ]
