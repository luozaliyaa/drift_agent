"""Persistent Drift runner state."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from drift_agent.drift.types import DriftRunRecord


class DriftStateStore:
    def __init__(self, drift_dir: str | Path = "drift") -> None:
        self.drift_dir = Path(drift_dir)
        self.state_path = self.drift_dir / "drift.json"
        self.note_path = self.drift_dir / "drift_note.md"
        self.drift_dir.mkdir(parents=True, exist_ok=True)
        if not self.note_path.exists():
            self.note_path.write_text("# Drift Note\n", encoding="utf-8")

    def load(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"recent_runs": []}
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"recent_runs": []}
        if not isinstance(data, dict):
            return {"recent_runs": []}
        data.setdefault("recent_runs", [])
        return data

    def recent_runs(self, limit: int = 20) -> list[dict[str, Any]]:
        runs = self.load().get("recent_runs", [])
        if not isinstance(runs, list):
            return []
        return [run for run in runs[-limit:] if isinstance(run, dict)]

    def last_run_at(self) -> datetime | None:
        runs = self.recent_runs(limit=1)
        if not runs:
            return None
        raw = str(runs[-1].get("run_at") or "")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=UTC)
        return parsed

    def can_run(self, min_interval_hours: float, now: datetime | None = None) -> bool:
        last = self.last_run_at()
        if last is None:
            return True
        now = now or datetime.now(UTC)
        return (now - last).total_seconds() >= min_interval_hours * 3600

    def record_run(self, record: DriftRunRecord) -> None:
        data = self.load()
        runs = data.setdefault("recent_runs", [])
        if not isinstance(runs, list):
            runs = []
            data["recent_runs"] = runs
        runs.append(
            {
                "skill": record.skill,
                "run_at": record.run_at,
                "one_line": record.one_line,
                "message_result": record.message_result,
            }
        )
        data["recent_runs"] = runs[-100:]
        self._atomic_write(self.state_path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")

    def skill_state_path(self, skill_name: str) -> Path:
        path = self.drift_dir / "skills" / skill_name / "state.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text("{}\n", encoding="utf-8")
        return path

    def read_note(self) -> str:
        if not self.note_path.exists():
            return ""
        return self.note_path.read_text(encoding="utf-8")

    def _atomic_write(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_text(content, encoding="utf-8")
        tmp_path.replace(path)


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
