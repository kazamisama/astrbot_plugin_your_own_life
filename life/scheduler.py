"""Per-persona asyncio scheduler with deterministic time jitter."""
from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime, time, timedelta
from typing import Any, Callable, Optional, Sequence

from life.config import LifeConfig
from life.timeutil import local_now


def _parse_hhmm(raw: str) -> Optional[time]:
    text = (raw or "").strip()
    try:
        hour_str, minute_str = text.split(":", 1)
        return time(int(hour_str), int(minute_str))
    except (ValueError, AttributeError):
        return None


def deterministic_offset(seed_key: str, minutes: int) -> timedelta:
    """Stable pseudo-random offset in [-minutes, +minutes] for one seed key."""
    if int(minutes) <= 0:
        return timedelta(0)
    digest = hashlib.sha256(seed_key.encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big")
    span = max(1, int(minutes) * 2)
    offset = (value % (span + 1)) - int(minutes)
    return timedelta(minutes=offset)


class LifeScheduler:
    def __init__(
        self,
        service: Any,
        config: LifeConfig,
        logger: Optional[logging.Logger] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.service = service
        self.config = config
        self.log = logger or logging.getLogger("your_own_life.scheduler")
        self.now_fn = now_fn or datetime.now
        self.db = getattr(service, "db", None) if service is not None else None
        self._instance_id = uuid.uuid4().hex
        self._task: Optional[asyncio.Task] = None
        self._stop = asyncio.Event()
        self._lock = asyncio.Lock()
        self._done_keys: set[str] = set()

    def start(self) -> bool:
        if self._task is not None and not self._task.done():
            return True
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.log.warning("no running asyncio loop; scheduler disabled")
            return False
        self._stop.clear()
        self._task = loop.create_task(self._run())
        return True

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=5)
            except (asyncio.TimeoutError, Exception):
                self._task.cancel()
            self._task = None

    def _jittered_slot(self, persona_id: str, base_dt: datetime, kind: str) -> datetime:
        if kind == "peek":
            return base_dt
        minutes = (
            self.config.browse_jitter_minutes
            if kind == "browse"
            else self.config.diary_jitter_minutes
        )
        seed_key = (
            f"{persona_id}|{base_dt.strftime('%Y-%m-%d')}|{base_dt.strftime('%H:%M')}|{kind}"
        )
        slot = base_dt + deterministic_offset(seed_key, minutes)
        if kind == "browse" and self.config.sleep_window.contains(slot):
            end = self.config.sleep_window.end
            candidate = datetime.combine(slot.date(), end)
            if candidate <= slot:
                candidate += timedelta(days=1)
            return candidate
        return slot

    def _slot_datetimes(self, persona_id: str, day: Any) -> list[tuple[datetime, str]]:
        slots: list[tuple[datetime, str]] = []
        for raw in self.config.browse_times:
            slot_time = _parse_hhmm(raw)
            if slot_time:
                base = datetime.combine(day, slot_time)
                slots.append((self._jittered_slot(persona_id, base, "browse"), "browse"))
        diary_time = _parse_hhmm(self.config.diary_time)
        if diary_time:
            base = datetime.combine(day, diary_time)
            slots.append((self._jittered_slot(persona_id, base, "diary"), "diary"))
        for raw in self.config.peek_times:
            peek_time = _parse_hhmm(raw)
            if peek_time:
                base = datetime.combine(day, peek_time)
                slots.append((self._jittered_slot(persona_id, base, "peek"), "peek"))
        return slots

    def next_target(
        self, now: datetime, personas: Sequence[str]
    ) -> Optional[tuple[datetime, str, str]]:
        best: Optional[tuple[datetime, str, str]] = None
        for offset in (0, 1):
            day = now.date() + timedelta(days=offset)
            for persona_id in personas:
                for slot, kind in self._slot_datetimes(persona_id, day):
                    if slot > now and (best is None or slot < best[0]):
                        best = (slot, persona_id, kind)
        return best

    def _current_target(
        self, personas: Sequence[str]
    ) -> Optional[tuple[datetime, str, str]]:
        now_local = local_now(self.config.timezone, self.now_fn())
        return self.next_target(now_local, personas)

    async def _run(self) -> None:
        personas = list(self.config.life_personas or [])
        while not self._stop.is_set():
            if not personas:
                await self._stop.wait()
                break
            target = self._current_target(personas)
            if target is None:
                await self._stop.wait()
                break
            slot, persona_id, kind = target
            now_local = local_now(self.config.timezone, self.now_fn())
            wait = max(1.0, (slot - now_local).total_seconds())
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                break
            key = f"{slot.strftime('%Y-%m-%d %H:%M')}:{persona_id}:{kind}"
            if key in self._done_keys:
                continue
            if self.db is not None and not self.db.acquire_lease(
                persona_id, key, self._instance_id, self.config.lease_ttl_seconds
            ):
                self.log.warning(
                    "lease for %s %s held by another instance, skipping", persona_id, key
                )
                self.service.record_skipped_duplicate(persona_id, kind, slot)
                self._done_keys.add(key)
                continue
            async with self._lock:
                try:
                    if kind == "browse":
                        await self.service.run_browse_session(persona_id, "scheduled")
                    elif kind == "peek":
                        await self.service.run_peek(persona_id)
                    else:
                        await self.service.run_nightly_diary(persona_id)
                except Exception as exc:
                    self.log.exception("scheduled %s for %s failed: %s", kind, persona_id, exc)
                finally:
                    self._done_keys.add(key)
                    if self.db is not None:
                        self.db.release_lease(persona_id, key, self._instance_id)