from __future__ import annotations

from datetime import UTC, datetime, timedelta

from drift_agent.proactive.energy import next_tick_interval


def test_profile_interval_mapping() -> None:
    old = datetime.now(UTC) - timedelta(days=3)

    assert next_tick_interval(profile="daily", last_user_at=old) == 60.0
    assert next_tick_interval(profile="quiet", last_user_at=old) == 240.0
    assert next_tick_interval(profile="dev_verify", last_user_at=old) == 10.0


def test_recent_user_activity_slows_tick() -> None:
    now = datetime.now(UTC)
    recent = now
    old = now - timedelta(days=3)

    recent_interval = next_tick_interval(
        profile="daily",
        last_user_at=recent,
        now=now,
    )
    old_interval = next_tick_interval(
        profile="daily",
        last_user_at=old,
        now=now,
    )

    assert recent_interval > old_interval
