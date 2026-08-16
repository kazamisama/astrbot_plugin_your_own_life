"""Per-persona busy state and conversation window for anthropomorphic chat."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Optional


class LifePresence:
    """Tracks whether a persona is busy with a life task and whether a chat
    reply window is open. The scheduler pauses per-persona events while a
    conversation is waiting for the user to continue."""

    def __init__(self, logger: Optional[logging.Logger] = None):
        self.log = logger or logging.getLogger("your_own_life.presence")
        self._busy: dict[str, dict[str, Any]] = {}
        self._free_events: dict[str, asyncio.Event] = {}
        self._last_busy: dict[str, dict[str, Any]] = {}
        self._conversation_until: dict[str, datetime] = {}
        self._conversation_closed: set[str] = set()

    def mark_busy(self, persona_id: str, kind: str = "") -> None:
        """Mark a persona as busy with a life task."""
        self._busy[persona_id] = {
            "kind": kind or "",
            "started_at": datetime.now().isoformat(),
        }
        self._free_events.setdefault(persona_id, asyncio.Event()).clear()
        self._last_busy.pop(persona_id, None)

    def clear_busy(self, persona_id: str) -> dict[str, Any]:
        """Clear busy state and wake any waiting chat request."""
        info = self._busy.pop(persona_id, None) or {"kind": ""}
        event = self._free_events.get(persona_id)
        if event is not None:
            event.set()
        self._last_busy[persona_id] = info
        return info

    def is_busy(self, persona_id: str) -> Optional[dict[str, Any]]:
        return self._busy.get(persona_id)

    def take_last_busy(self, persona_id: str) -> Optional[dict[str, Any]]:
        return self._last_busy.pop(persona_id, None)

    async def wait_until_free(
        self, persona_id: str, max_wait_seconds: float = 1800.0
    ) -> bool:
        """Wait until the persona is free or the timeout elapses."""
        event = self._free_events.setdefault(persona_id, asyncio.Event())
        if not self.is_busy(persona_id):
            return True
        try:
            await asyncio.wait_for(
                event.wait(), timeout=max(0.0, float(max_wait_seconds))
            )
        except asyncio.TimeoutError:
            return not self.is_busy(persona_id)
        return not self.is_busy(persona_id)

    def set_conversation_window(
        self, persona_id: str, until: datetime
    ) -> None:
        self._conversation_until[persona_id] = until
        self._conversation_closed.discard(persona_id)

    def conversation_until(self, persona_id: str) -> Optional[datetime]:
        return self._conversation_until.get(persona_id)

    def conversation_active(
        self, persona_id: str, now: Optional[datetime] = None
    ) -> bool:
        until = self._conversation_until.get(persona_id)
        if until is None:
            return False
        return (now or datetime.now()) < until

    def close_expired_conversations(
        self,
        personas: list[str],
        db: Any = None,
        now: Optional[datetime] = None,
    ) -> list[dict[str, Any]]:
        """Close expired conversation windows and write conversation_end events."""
        now = now or datetime.now()
        closed: list[dict[str, Any]] = []
        for persona_id in personas:
            until = self._conversation_until.get(persona_id)
            if (
                until is None
                or now < until
                or persona_id in self._conversation_closed
            ):
                continue
            self._conversation_until.pop(persona_id, None)
            self._conversation_closed.add(persona_id)
            closed.append({
                "persona_id": persona_id,
                "reason": "timeout",
                "window_end": until.isoformat(),
            })
            if db is not None:
                db.append_event(
                    persona_id,
                    "conversation_end",
                    {"reason": "timeout", "window_end": until.isoformat()},
                    [],
                    f"chat/{persona_id}/conversation_end/"
                    f"{int(until.timestamp())}",
                    ts=now.strftime("%Y-%m-%d %H:%M:%S"),
                )
        return closed

    def _conversation_wait_seconds(
        self, personas: list[str], now: datetime
    ) -> Optional[float]:
        candidates = [
            (until - now).total_seconds()
            for persona_id in personas
            for until in [self._conversation_until.get(persona_id)]
            if until is not None and until > now
        ]
        return min(candidates) if candidates else None
