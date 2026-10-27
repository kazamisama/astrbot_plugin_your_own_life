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
        presence: Optional[Any] = None,
    ):
        self.service = service
        self.config = config
        self.log = logger or logging.getLogger("your_own_life.scheduler")
        self.now_fn = now_fn or datetime.now
        self.db = getattr(service, "db", None) if service is not None else None
        self.presence = presence or getattr(service, "presence", None)
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

    def _window_shifted(self, slot: datetime) -> datetime:
        """Postpone any slot inside the sleep window to just after it ends."""
        if not self.config.sleep_window.contains(slot):
            return slot
        end = self.config.sleep_window.end
        candidate = datetime.combine(slot.date(), end)
        if candidate <= slot:
            candidate += timedelta(days=1)
        return candidate

    def _jittered_slot(self, persona_id: str, base_dt: datetime, kind: str) -> datetime:
        if kind == "peek":
            slot = base_dt
        else:
            minutes = (
                self.config.browse_jitter_minutes
                if kind == "browse"
                else self.config.diary_jitter_minutes
            )
            seed_key = (
                f"{persona_id}|{base_dt.strftime('%Y-%m-%d')}|{base_dt.strftime('%H:%M')}|{kind}"
            )
            slot = base_dt + deterministic_offset(seed_key, minutes)
        return self._window_shifted(slot)

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
    ) -> list[tuple[datetime, str, str, str]]:
        """Return (jittered slot, kind, anchored task_id, anchored plan_date)."""
        plan_date = day.strftime("%Y-%m-%d")
        slots: list[tuple[datetime, str, str, str]] = []
        for raw in self.config.browse_times:
            slot_time = _parse_hhmm(raw)
            if slot_time:
                base = datetime.combine(day, slot_time)
                slot = self._jittered_slot(persona_id, base, "browse")
                slots.append((slot, "browse", f"browse-{base.strftime('%H-%M')}", plan_date))
        diary_time = _parse_hhmm(self.config.diary_time)
        if diary_time:
            base = datetime.combine(day, diary_time)
            slot = self._jittered_slot(persona_id, base, "diary")
            slots.append((slot, "diary", f"diary-{base.strftime('%H-%M')}", plan_date))
        for raw in self.config.peek_times:
            peek_time = _parse_hhmm(raw)
            if peek_time:
                base = datetime.combine(day, peek_time)
                slot = self._jittered_slot(persona_id, base, "peek")
                slots.append((slot, "peek", f"peek-{base.strftime('%H-%M')}", plan_date))
        if self._review_due(day, "monthly"):
            slots.append((self._window_shifted(datetime.combine(day, time(9, 0))),
                          "review", "review-monthly", plan_date))
        if self._review_due(day, "yearly"):
            slots.append((self._window_shifted(datetime.combine(day, time(9, 30))),
                          "review", "review-yearly", plan_date))
        if self._review_due(day, "quarterly"):
            slots.append((self._window_shifted(datetime.combine(day, time(9, 15))),
                          "review", "review-quarterly", plan_date))
        return slots

    def _plan_datetime(self, row: dict) -> Optional[datetime]:
        raw = (row.get("scheduled_at") or "").strip()
        try:
            return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return None

    def next_target(
        self, now: datetime, personas: Sequence[str]
    ) -> Optional[tuple[datetime, str, str, str, str]]:
        best: Optional[tuple[datetime, str, str, str, str]] = None
        overdue: Optional[tuple[datetime, str, str, str, str]] = None
        seen: set[tuple[datetime, str, str]] = set()

        def consider(
            slot: datetime, persona_id: str, kind: str, task_id: str, plan_date: str
        ) -> None:
            nonlocal best
            key = (slot, persona_id, kind)
            if key in seen:
                return
            seen.add(key)
            if slot > now and (best is None or slot < best[0]):
                best = (slot, persona_id, kind, task_id, plan_date)

        if self.db is not None:
            day_str = now.date().strftime("%Y-%m-%d")
            for persona_id in personas:
                for row in self.db.list_plans(persona_id, day_str, status="pending"):
                    slot = self._plan_datetime(row)
                    if slot is None:
                        continue
                    kind = str(row.get("kind") or "")
                    task_id = str(row.get("task_id") or "")
                    plan_date = str(row.get("plan_date") or day_str)
                    if slot <= now:
                        # 当日错过槽位（对话等待/长任务/停机）：立即补做，睡眠窗内顺延。
                        due_at = self._window_shifted(now)
                        if overdue is None or due_at < overdue[0]:
                            overdue = (due_at, persona_id, kind, task_id, plan_date)
                    else:
                        consider(slot, persona_id, kind, task_id, plan_date)
        if overdue is not None:
            return overdue
        for offset in (0, 1):
            day = now.date() + timedelta(days=offset)
            for persona_id in personas:
                for slot, kind, task_id, plan_date in self._slot_datetimes(persona_id, day):
                    consider(slot, persona_id, kind, task_id, plan_date)
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
        count = 0
        for persona_id in personas:
            for slot, kind, task_id, plan_date in self._slot_datetimes(persona_id, day):
                self.db.ensure_plan(
                    persona_id, plan_date, task_id, kind,
                    scheduled_at=slot.strftime("%Y-%m-%d %H:%M:%S"),
                    fixed=True,
                )
                count += 1
        return count

    def _ensure_target_plan(
        self,
        slot: datetime,
        persona_id: str,
        kind: str,
        task_id: str,
        plan_date: str,
    ) -> None:
        if self.db is None:
            return
        self.db.ensure_plan(
            persona_id, plan_date, task_id, kind,
            scheduled_at=slot.strftime("%Y-%m-%d %H:%M:%S"),
            fixed=True,
        )

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

    def _budget_delta(self, before: Optional[dict], after: Optional[dict]) -> float:
        def _tokens(row: Optional[dict]) -> int:
            return int(row["tokens"] or 0) if row else 0

        return float(max(0, _tokens(after) - _tokens(before)))

    def _acquire_lease(self, persona_id: str, task_key: str) -> bool:
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

    def _lease_ttl(self) -> int:
        memory = getattr(self.service, "memory", None) if self.service else None
        if memory is not None and getattr(self.config, "memory_host", ""):
            return int(self.config.memory_lease_ttl_seconds or 300)
        return int(self.config.lease_ttl_seconds or 300)

    def _renew_interval(self) -> float:
        return max(1.0, float(self._lease_ttl()) / 2.0)

    def _renew_lease(self, persona_id: str, task_key: str) -> bool:
        memory = getattr(self.service, "memory", None) if self.service else None
        ttl = self._lease_ttl()
        if memory is not None and getattr(self.config, "memory_host", ""):
            try:
                return bool(memory.renew_task(
                    persona_id, task_key, holder=self._instance_id,
                    ttl_seconds=ttl,
                ))
            except Exception as exc:
                self.log.warning(
                    "memory lease renew failed for %s %s: %s",
                    persona_id, task_key, exc,
                )
                return False
        if self.db is not None:
            return self.db.renew_lease(
                persona_id, task_key, self._instance_id, ttl
            )
        return True

    def _available_personas(
        self, personas: Sequence[str], now: datetime
    ) -> list[str]:
        """Personas not paused by an open conversation wait window."""
        if self.presence is None:
            return list(personas)
        self.presence.close_expired_conversations(personas, self.db, now)
        return [
            p for p in personas
            if not self.presence.conversation_active(p, now)
        ]

    def _plan_row(
        self, persona_id: str, plan_date: str, task_id: str
    ) -> Optional[dict]:
        if self.db is None:
            return None
        for row in self.db.list_plans(persona_id, plan_date):
            if str(row.get("task_id") or "") == task_id:
                return row
        return None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                await self._run_loop()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.log.exception("scheduler loop crashed; restarting in 5s")
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=5)
                except asyncio.TimeoutError:
                    pass
                continue
            break

    async def _run_loop(self) -> None:
        personas = list(self.config.life_personas or [])
        while not self._stop.is_set():
            if not self.config.enabled:
                await self._stop.wait()
                break
            if not personas:
                await self._stop.wait()
                break
            if self.db is not None:
                try:
                    self.db.cleanup_expired_leases()
                except Exception as exc:
                    self.log.warning("lease cleanup failed: %s", exc)
            today_local = local_now(self.config.timezone, self.now_fn()).date()
            today_key = today_local.isoformat()
            if today_key not in self._seeded_dates:
                self.seed_plans(personas, today_local)
                self._seeded_dates.add(today_key)
            now_local = local_now(self.config.timezone, self.now_fn())
            personas_ready = self._available_personas(personas, now_local)
            if not personas_ready:
                wait_seconds = (
                    self.presence._conversation_wait_seconds(
                        personas, now_local
                    )
                    if self.presence is not None else None
                )
                await asyncio.sleep(
                    max(0.5, min((wait_seconds or 0.0) + 0.5, 60.0))
                )
                continue
            target = self._current_target(personas_ready)
            if target is None:
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=60)
                except asyncio.TimeoutError:
                    pass
                continue
            slot, persona_id, kind, task_id, plan_date = target
            # 目标可能落在次日（尚未播种）；先补齐计划行，finally 才不会落空。
            self._ensure_target_plan(slot, persona_id, kind, task_id, plan_date)
            now_local = local_now(self.config.timezone, self.now_fn())
            wait = max(1.0, (slot - now_local).total_seconds())
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=wait)
            except asyncio.TimeoutError:
                pass
            if self._stop.is_set():
                break
            key = (
                f"{slot.strftime('%Y-%m-%d %H:%M')}:{persona_id}:{kind}:{task_id}"
            )
            if key in self._done_keys:
                continue
            plan_row = self._plan_row(persona_id, plan_date, task_id)
            if plan_row is not None and str(plan_row.get("status") or "") != "pending":
                self.log.info(
                    "plan %s/%s became %s while waiting; skipping",
                    plan_date, task_id, plan_row.get("status"),
                )
                self._done_keys.add(key)
                continue
            if not self._acquire_lease(persona_id, key):
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
                        only_if_status="pending",
                    )
                self._done_keys.add(key)
                continue
            usage_before = (
                self.db.get_daily_usage(persona_id, plan_date)
                if self.db is not None else None
            )
            keepalive: Optional[asyncio.Task] = None

            async def _keepalive(p: str = persona_id, k: str = key) -> None:
                while True:
                    await asyncio.sleep(self._renew_interval())
                    try:
                        renewed = self._renew_lease(p, k)
                    except Exception:
                        self.log.exception(
                            "keepalive renew failed for %s %s", p, k
                        )
                        return
                    if not renewed:
                        self.log.warning(
                            "keepalive renew returned false for %s %s", p, k
                        )

            async with self._lock:
                status = "failed"
                reason = ""
                if self.presence is not None:
                    self.presence.mark_busy(persona_id, kind)
                try:
                    keepalive = asyncio.create_task(_keepalive())
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
                        status, reason = self._plan_status_diary(result)
                    else:
                        result = await self.service.run_nightly_diary(persona_id)
                        status, reason = self._plan_status_diary(result)
                except Exception as exc:
                    self.log.exception(
                        "scheduled %s for %s failed: %s", kind, persona_id, exc
                    )
                    status, reason = "failed", repr(exc)
                finally:
                    if self.presence is not None:
                        self.presence.clear_busy(persona_id)
                    if keepalive is not None:
                        keepalive.cancel()
                        try:
                            await keepalive
                        except asyncio.CancelledError:
                            pass
                        except Exception:
                            self.log.debug(
                                "keepalive ended with error", exc_info=True
                            )
                    self._done_keys.add(key)
                    self._release_lease(persona_id, key)
                    if self.db is not None:
                        try:
                            usage_after = self.db.get_daily_usage(
                                persona_id, plan_date
                            )
                            self.db.update_plan(
                                persona_id, plan_date, task_id, status,
                                reason=reason,
                                budget_used=self._budget_delta(
                                    usage_before, usage_after
                                ),
                                finished_at=local_now(
                                    self.config.timezone, self.now_fn()
                                ).strftime("%Y-%m-%d %H:%M:%S"),
                                only_if_status="pending",
                            )
                        except Exception:
                            self.log.exception(
                                "failed to finalize plan %s/%s",
                                plan_date, task_id,
                            )