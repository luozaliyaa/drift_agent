from __future__ import annotations

from drift_agent.drift.skills import DriftSkillScanner


def test_drift_skill_scanner_loads_enabled_skills(tmp_path) -> None:
    skill_dir = tmp_path / "drift" / "skills" / "curiosity"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: curiosity
description: Ask one light question
---

## Goal
Ask one small question.
""",
        encoding="utf-8",
    )

    skills = DriftSkillScanner(tmp_path / "drift").scan()

    assert len(skills) == 1
    assert skills[0].name == "curiosity"
    assert skills[0].description == "Ask one light question"


def test_drift_skill_scanner_skips_disabled_and_missing_mcp(tmp_path) -> None:
    disabled = tmp_path / "drift" / "skills" / "disabled"
    disabled.mkdir(parents=True)
    (disabled / "SKILL.md").write_text(
        """---
name: disabled
enabled: false
---

Body.
""",
        encoding="utf-8",
    )
    needs_mcp = tmp_path / "drift" / "skills" / "needs-mcp"
    needs_mcp.mkdir(parents=True)
    (needs_mcp / "SKILL.md").write_text(
        """---
name: needs-mcp
requires_mcp: [fitbit]
---

Body.
""",
        encoding="utf-8",
    )

    skills = DriftSkillScanner(tmp_path / "drift").scan()

    assert skills == []


def test_drift_skill_scanner_allows_available_mcp(tmp_path) -> None:
    skill_dir = tmp_path / "drift" / "skills" / "fitbit"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
name: fitbit
requires_mcp: [fitbit]
---

Body.
""",
        encoding="utf-8",
    )

    skills = DriftSkillScanner(
        tmp_path / "drift",
        available_mcp_servers={"fitbit"},
    ).scan()

    assert [skill.name for skill in skills] == ["fitbit"]
