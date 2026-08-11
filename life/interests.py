"""Per-persona interest weighting and topic picking."""
from __future__ import annotations

import random
from datetime import datetime
from typing import Optional, Sequence

from life.db import LifeDB


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def next_weight(old: float, interest_level: float) -> float:
    """Decay the old weight a little, then move toward the observed level."""
    old = clamp(old)
    level = clamp(interest_level)
    delta = (level - 0.5) * 0.5
    return clamp(old * 0.9 + delta)


class InterestStore:
    def __init__(
        self,
        db: LifeDB,
        initial: Optional[Sequence[tuple[str, str]]] = None,
        decay: float = 0.98,
    ):
        self.db = db
        self.decay = float(decay)
        self.initial = list(initial or [])

    def seed(self, persona_id: str, initial: Optional[Sequence[tuple[str, str]]] = None) -> None:
        existing = {row["key"] for row in self.db.get_interests(persona_id)}
        for key, name in initial or self.initial:
            if key and key not in existing:
                self.db.upsert_interest(persona_id, key, name, 0.5, seen_count=0)

    def pick_topics(
        self,
        persona_id: str,
        count: int = 3,
        explore_probability: float = 0.2,
        rng: Optional[random.Random] = None,
    ) -> list[str]:
        rng = rng or random.Random()
        items = self.db.get_interests(persona_id)
        names = [row["name"] or row["key"] for row in items]
        picked = names[: max(1, count)]
        if items and rng.random() < explore_probability:
            pool = [name for name in names if name not in picked]
            if pool:
                picked.append(rng.choice(pool))
        return picked[:count]

    def apply_note(
        self,
        persona_id: str,
        key: str,
        name: str,
        interest_level: float,
        now: Optional[datetime] = None,
    ) -> None:
        if not key:
            return
        current = self.db.get_interests(persona_id)
        old = next((row["weight"] for row in current if row["key"] == key), 0.5)
        self.db.upsert_interest(
            persona_id,
            key,
            name or key,
            next_weight(old, interest_level),
            last_seen_at=now.strftime("%Y-%m-%d %H:%M:%S") if now else None,
        )

    def apply_updates(
        self,
        persona_id: str,
        updates: dict,
        now: Optional[datetime] = None,
    ) -> None:
        if not isinstance(updates, dict):
            return
        for key, spec in updates.items():
            if not isinstance(spec, dict):
                continue
            name = str(spec.get("name") or key)
            try:
                delta = float(spec.get("delta", 0.0))
            except (TypeError, ValueError):
                delta = 0.0
            current = self.db.get_interests(persona_id)
            old = next((row["weight"] for row in current if row["key"] == key), 0.5)
            self.db.upsert_interest(
                persona_id,
                key,
                name,
                clamp(old + delta),
                last_seen_at=now.strftime("%Y-%m-%d %H:%M:%S") if now else None,
            )

    def daily_decay(self, persona_id: str) -> int:
        return self.db.decay_interests(persona_id, self.decay)