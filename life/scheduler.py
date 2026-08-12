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
        self._seeded_dates: set[str] = set()

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

    def _review_due(self, day: Any, period: str) -> bool:
        if period == "quarterly":
            return bool(self.config.quarterly_review_enabled) and day.day == 1 and day.month % 3 == 1
        schedule = self.config.review_schedule or {}
        raw = schedule.get(period)
        if not raw:
            return False
        if period == "yearly":
            return raw == f"{day.month:02d}-{day.day:02d}"
        try:
            return int(raw) == day.day
        except (TypeError, ValueError):
            return False

    def _slot_datetimes(
        self, persona_id: str, day: Any
    ) -> list[tuple[datetime, str, str]]:
        slots: list[tuple[datetime, str, str]] = []
        for raw in self.config.browse_times:
            slot_time = _parse_hhmm(raw)
            if slot_time:
                base = datetime.combine(day, slot_time)
                slot = self._jittered_slot(persona_id, base, "browse")
                slots.append((slot, "browse", f"browse-{slot.strftime('%H-%M')}"))
        diary_time = _parse_hhmm(self.config.diary_time)
        if diary_time:
            base = datetime.combine(day, diary_time)
            slot = self._jittered_slot(persona_id, base, "diary")
            slots.append((slot, "diary", f"diary-{slot.strftime('%H-%M')}"))
        for raw in self.config.peek_times:
            peek_time = _parse_hhmm(raw)
            if peek_time:
                base = datetime.combine(day, peek_time)
                slot = self._jittered_slot(persona_id, base, "peek")
                slots.append((slot, "peek", f"peek-{slot.strftime('%H-%M')}"))
        if self._review_due(day, "monthly"):
            slots.append((datetime.combine(day, time(9, 0)), "review", "review-monthly"))
        if self._review_due(day, "yearly"):
            slots.append((datetime.combine(day, time(9, 30)), "review", "review-yearly"))
        if self._review_due(day, "quarterly"):
            slots.append((datetime.combine(day, time(9, 15)), "review", "review-quarterly"))
        return slots

    def _plan_datetime(self, row: dict) -> Optional[datetime]:
        raw = (row.get("scheduled_at") or "").strip()
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def next_target(
        self, now: datetime, personas: Sequence[str]
    ) -> Optional[tuple[datetime, str, str, str]]:
        best: Optional[tuple[datetime, str, str, str]] = None
        seen: set[tuple[datetime, str, str]] = set()

        def consider(slot: datetime, persona_id: str, kind: str, task_id: str) -> None:
            nonlocal best
            key = (slot, persona_id, kind)
            if key in seen:
                return
            seen.add(key)
            if slot > now and (best is None or slot < best[0]):
                best = (slot, persona_id, kind, task_id)

        if self.db is not None:
            day_str = now.date().strftime("%Y-%m-%d")
            for persona_id in personas:
                for row in self.db.list_plans(persona_id, day_str, status="pending"):
                    slot = self._plan_datetime(row)
                    if slot is not None:
                        consider(slot, persona_id, str(row.get("kind") or ""),
                                 str(row.get("task_id") or ""))
        for offset in (0, 1):
            day = now.date() + timedelta(days=offset)
            for persona_id in personas:
                for slot, kind, task_id in self._slot_datetimes(persona_id, day):
                    consider(slot, persona_id, kind, task_id)
        return best

    def _current_target(
        self, personas: Sequence[str]
    ) -> Optional[tuple[datetime, str, str, str]]:
        now_local = local_now(self.config.timezone, self.now_fn())
        return self.next_target(now_local, personas)

    def seed_plans(self, personas: Sequence[str], day: Any) -> int:
        """Create pending plan rows for every configured slot of one day."""
        if self.db is None:
            return 0
        plan_date = day.strftime("%Y-%m-%d")
        count = 0
        for persona_id in personas:
            for slot, kind, task_id in self._slot_datetimes(persona_id, day):
                self.db.ensure_plan(
                    persona_id, plan_date, task_id, kind,
                    scheduled_at=slot.strftime("%Y-%m-%d %H:%M:%S"),
                    fixed=True,
                )
                count += 1
        return count

    def _plan_status_browse(self, result: Any) -> tuple[str, str]:
        status = getattr(result, "status", "completed")
        reason = str(getattr(result, "reason", "") or getattr(result, "error", "") or "")
        if status == "completed":
            return "done", reason
        if status == "error":
            return "failed", reason or str(getattr(result, "error", ""))
        return "skipped", reason or str(status)

    def _plan_status_diary(self, result: Any) -> tuple[str, str]:
        if isinstance(result, dict) and result.get("error"):
            return "failed", str(result["error"])
        if isinstance(result, dict) and result.get("skipped"):
            return "skipped", str(result["skipped"])
        return "done", ""

    def _plan_status_review(self, result: Any) -> tuple[str, str]:
        if isinstance(result, dict) and result.get("error"):
            return "failed", str(result["error"])
        if isinstance(result, dict) and result.get("skipped"):
            return "skipped", str(result["skipped"])
        return "done", ""

    def _budget_delta(self, before: Optional[dict], after: Optional[dict]) -> float:
        def _tokens(row: Optional[dict]) -> int:
            return int(row["tokens"] or 0) if row else 0

        return float(max(0, _tokens(after) - _tokens(before)))

    def _acquire_lease(self, persona_id: str, task_key: str, kind: str) -> bool:
        memory = getattr(self.service, "memory", None) if self.service else None
        if memory is not None and getattr(self.config, "memory_host", ""):
            try:
                return bool(memory.claim_task(
                    persona_id, task_key, holder=self._instance_id,
                    ttl_seconds=self.config.memory_lease_ttl_seconds,
                ))
            except Exception as exc:
                self.log.warning(
                    "memory lease claim failed for %s %s: %s",
                    persona_id, task_key, exc,
                )
                return False
        if self.db is not None:
            return self.db.acquire_lease(
                persona_id, task_key, self._instance_id,
                self.config.lease_ttl_seconds,
            )
        return True

    def _release_lease(self, persona_id: str, task_key: str) -> None:
        memory = getattr(self.service, "memory", None) if self.service else None
        if memory is not None and getattr(self.config, "memory_host", ""):
            try:
                memory.release_task(persona_id, task_key, holder=self._instance_id)
            except Exception as exc:
                self.log.warning(
                    "memory lease release failed for %s %s: %s",
                    persona_id, task_key, exc,
                )
            return
        if self.db is not None:
            self.db.release_lease(persona_id, task_key, self._instance_id)

    async def _run(self) -> None:
        personas = list(self.config.life_personas or [])
        while not self._stop.is_set():
            if not personas:
                await self._stop.wait()
                break
            today_local = local_now(self.config.timezone, self.now_fn()).date()
            today_key = today_local.isoformat()
            if today_key not in self._seeded_dates:
                self.seed_plans(personas, today_local)
                self._seeded_dates.add(today_key)
            target = self._current_target(personas)
            if target is None:
                await self._stop.wait()
                break
            slot, persona_id, kind, task_id = target
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
            plan_date = slot.strftime("%Y-%m-%d")
            if not self._acquire_lease(persona_id, key, kind):
                self.log.warning(
                    "lease for %s %s held by another instance, skipping", persona_id, key
                )
                self.service.record_skipped_duplicate(persona_id, kind, slot)
                if self.db is not None:
                    self.db.ensure_plan(
                        persona_id, plan_date, task_id, kind,
                        scheduled_at=slot.strftime("%Y-%m-%d %H:%M:%S"),
                    )
                    self.db.update_plan(
                        persona_id, plan_date, task_id, "skipped",
                        reason="skipped_duplicate",
                        finished_at=local_now(
                            self.config.timezone, self.now_fn()
                        ).strftime("%Y-%m-%d %H:%M:%S"),
                    )
                self._done_keys.add(key)
                continue
            usage_before = (
                self.db.get_daily_usage(persona_id, plan_date)
                if self.db is not None else None
            )
            async with self._lock:
                status = "failed"
                reason = ""
                try:
                    if kind == "browse":
                        result = await self.service.run_browse_session(persona_id, "scheduled")
                        status, reason = self._plan_status_browse(result)
                    elif kind == "peek":
                        result = await self.service.run_peek(persona_id)
                        status, reason = self._plan_status_browse(result)
                    elif kind == "review":
                        if task_id == "review-yearly":
                            result = await self.service.run_review(persona_id, "yearly")
                        elif task_id == "review-quarterly":
                            result = await self.service.run_quarterly_review(persona_id)
                        else:
                            result = await self.service.run_review(persona_id, "monthly")
                        status, reason = self._plan_status_review(result)
                    else:
                        result = await self.service.run_nightly_diary(persona_id)
                        status, reason = self._plan_status_diary(result)
                except Exception as exc:
                    self.log.exception(
                        "scheduled %s for %s failed: %s", kind, persona_id, exc
                    )
                    status, reason = "failed", repr(exc)
                finally:
                    self._done_keys.add(key)
                    self._release_lease(persona_id, key)
                    if self.db is not None:
                        usage_after = self.db.get_daily_usage(persona_id, plan_date)
                        self.db.update_plan(
                            persona_id, plan_date, task_id, status,
                            reason=reason,
                            budget_used=self._budget_delta(usage_before, usage_after),
                            finished_at=local_now(
                                self.config.timezone, self.now_fn()
                            ).strftime("%Y-%m-%d %H:%M:%S"),
                        )