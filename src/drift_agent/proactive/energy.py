"""Adaptive proactive tick timing."""

from __future__ import annotations

from datetime import UTC, datetime


PROFILE_INTERVALS: dict[str, tuple[float, float, float, float]] = {
    "daily": (480.0, 240.0, 120.0, 60.0),
    "quiet": (1800.0, 900.0, 480.0, 240.0),
    "dev_verify": (60.0, 30.0, 15.0, 10.0),
}


def compute_energy(last_user_at: datetime | None, now: datetime | None = None) -> float:
    if last_user_at is None:
        return 0.0
    now = now or datetime.now(UTC)
    if last_user_at.tzinfo is None:
        last_user_at = last_user_at.replace(tzinfo=UTC)
    elapsed_seconds = max(0.0, (now - last_user_at).total_seconds())
    short = decay(elapsed_seconds, half_life_seconds=30 * 60)
    medium = decay(elapsed_seconds, half_life_seconds=4 * 60 * 60)
    long = decay(elapsed_seconds, half_life_seconds=48 * 60 * 60)
    return clamp((0.5 * short) + (0.35 * medium) + (0.15 * long))


def proactive_score(
    *,
    last_user_at: datetime | None,
    new_content_count: int = 0,
    recent_chat_richness: float = 0.0,
    now: datetime | None = None,
) -> float:
    energy = compute_energy(last_user_at, now)
    d_energy = 1.0 - energy
    content_score = min(max(new_content_count, 0), 5) / 5.0
    richness = clamp(recent_chat_richness)
    return clamp((0.75 * d_energy) + (0.20 * content_score) + (0.05 * richness))


def next_tick_interval(
    *,
    profile: str = "daily",
    last_user_at: datetime | None = None,
    new_content_count: int = 0,
    recent_chat_richness: float = 0.0,
    now: datetime | None = None,
) -> float:
    intervals = PROFILE_INTERVALS.get(profile, PROFILE_INTERVALS["daily"])
    score = proactive_score(
        last_user_at=last_user_at,
        new_content_count=new_content_count,
        recent_chat_richness=recent_chat_richness,
        now=now,
    )
    if score > 0.70:
        return intervals[3]
    if score > 0.40:
        return intervals[2]
    if score > 0.20:
        return intervals[1]
    return intervals[0]


def decay(elapsed_seconds: float, half_life_seconds: float) -> float:
    return 0.5 ** (elapsed_seconds / half_life_seconds)


def clamp(value: float) -> float:
    return max(0.0, min(1.0, value))
