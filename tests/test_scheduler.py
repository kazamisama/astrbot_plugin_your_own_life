import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, time, timedelta
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.config import LifeConfig, SleepWindow
from life.db import LifeDB
from life.scheduler import LifeScheduler, _parse_hhmm, deterministic_offset


class SchedulerTest(unittest.TestCase):
    def test_parse_hhmm(self):
        self.assertEqual(_parse_hhmm("10:30"), time(10, 30))
        self.assertIsNone(_parse_hhmm("bad"))

    def test_deterministic_offset(self):
        offset_a = deterministic_offset("shelly|2026-08-10|10:00|browse", 120)
        offset_b = deterministic_offset("shelly|2026-08-10|10:00|browse", 120)
        offset_c = deterministic_offset("shelly|2026-08-11|10:00|browse", 120)
        self.assertEqual(offset_a, offset_b)
        self.assertNotEqual(offset_a, offset_c)
        self.assertLessEqual(abs(offset_a.total_seconds()), 120 * 60)

    def test_next_target_per_persona(self):
        cfg = LifeConfig(browse_times=["10:00", "15:00"], diary_time="23:00",
                         browse_jitter_minutes=0, diary_jitter_minutes=0,
                         life_personas=["shelly", "alice"])
        scheduler = LifeScheduler(service=None, config=cfg)
        target = scheduler.next_target(datetime(2026, 8, 10, 9, 0), ["shelly", "alice"])
        self.assertEqual(target[0], datetime(2026, 8, 10, 10, 0))
        self.assertIn(target[1], ("shelly", "alice"))
        self.assertEqual(target[2], "browse")

    def test_diary_after_all_browse_slots(self):
        cfg = LifeConfig(browse_times=["10:00", "15:00"], diary_time="23:00",
                         browse_jitter_minutes=0, diary_jitter_minutes=0,
                         peek_times=[], life_personas=["shelly"])
        scheduler = LifeScheduler(service=None, config=cfg)
        target = scheduler.next_target(datetime(2026, 8, 10, 16, 0), ["shelly"])
        self.assertEqual(target[0], datetime(2026, 8, 10, 23, 0))
        self.assertEqual(target[2], "diary")

    def test_peek_slots_are_scheduled(self):
        cfg = LifeConfig(browse_times=["10:00"], diary_time="23:00",
                         browse_jitter_minutes=0, diary_jitter_minutes=0,
                         peek_times=["09:00"], life_personas=["shelly"])
        scheduler = LifeScheduler(service=None, config=cfg)
        target = scheduler.next_target(datetime(2026, 8, 10, 8, 0), ["shelly"])
        self.assertEqual(target[0], datetime(2026, 8, 10, 9, 0))
        self.assertEqual(target[2], "peek")

    def test_sleep_window_contains(self):
        window = SleepWindow(time(23, 0), time(7, 0))
        self.assertTrue(window.contains(datetime(2026, 8, 10, 0, 30)))
        self.assertFalse(window.contains(datetime(2026, 8, 10, 12, 0)))

    def test_current_target_uses_configured_timezone(self):
        cfg = LifeConfig(
            browse_times=["10:00", "15:00"], diary_time="23:00",
            browse_jitter_minutes=0, diary_jitter_minutes=0,
            peek_times=[], life_personas=["shelly"], timezone="America/New_York",
        )
        scheduler = LifeScheduler(
            service=None, config=cfg,
            now_fn=lambda: datetime(2026, 8, 12, 23, 30),
        )
        target = scheduler._current_target(["shelly"])
        self.assertEqual(target[0], datetime(2026, 8, 12, 15, 0))
        self.assertEqual(target[2], "browse")


class _FakeService:
    def __init__(self, db):
        self.db = db


class _FakeMemoryLease:
    def __init__(self, claimed=True):
        self.claimed = claimed
        self.claims = []
        self.releases = []

    def claim_task(self, persona_id, task_kind, holder=None, ttl_seconds=300):
        self.claims.append((persona_id, task_kind, holder, ttl_seconds))
        return self.claimed

    def release_task(self, persona_id, task_kind, holder=None):
        self.releases.append((persona_id, task_kind, holder))
        return True


class _FakeServiceWithMemory:
    def __init__(self, db, memory):
        self.db = db
        self.memory = memory


class SchedulerPlansTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")
        cfg = LifeConfig(
            browse_times=["10:00", "15:00"], diary_time="23:00",
            browse_jitter_minutes=0, diary_jitter_minutes=0,
            peek_times=["09:00"], life_personas=["shelly"],
        )
        self.scheduler = LifeScheduler(service=_FakeService(self.db), config=cfg)

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_seed_plans_creates_pending_rows(self):
        count = self.scheduler.seed_plans(["shelly"], datetime(2026, 8, 12))
        self.assertEqual(count, 4)
        items = self.db.list_plans("shelly", "2026-08-12")
        self.assertEqual(len(items), 4)
        self.assertTrue(all(item["status"] == "pending" for item in items))
        self.assertTrue(all(item["fixed"] == 1 for item in items))
        task_ids = {item["task_id"] for item in items}
        self.assertIn("browse-10-00", task_ids)
        self.assertIn("browse-15-00", task_ids)
        self.assertIn("peek-09-00", task_ids)
        self.assertIn("diary-23-00", task_ids)

    def test_review_slots_seed_on_schedule(self):
        cfg = LifeConfig(
            browse_times=["10:00"], diary_time="23:00",
            browse_jitter_minutes=0, diary_jitter_minutes=0,
            peek_times=[], life_personas=["shelly"],
            review_schedule={"monthly": "12", "yearly": "01-01"},
        )
        scheduler = LifeScheduler(service=_FakeService(self.db), config=cfg)
        self.assertTrue(scheduler._review_due(datetime(2026, 8, 12), "monthly"))
        self.assertTrue(scheduler._review_due(datetime(2026, 1, 1), "yearly"))
        count = scheduler.seed_plans(["shelly"], datetime(2026, 8, 12))
        self.assertEqual(count, 3)
        items = self.db.list_plans("shelly", "2026-08-12")
        task_ids = {item["task_id"] for item in items}
        self.assertIn("review-monthly", task_ids)
        self.assertNotIn("review-yearly", task_ids)
        target = scheduler.next_target(datetime(2026, 8, 12, 8, 0), ["shelly"])
        self.assertEqual(target[2], "review")
        self.assertEqual(target[3], "review-monthly")

    def test_quarterly_review_slot_on_quarter_start(self):
        cfg = LifeConfig(
            browse_times=["10:00"], diary_time="23:00",
            browse_jitter_minutes=0, diary_jitter_minutes=0,
            peek_times=[], life_personas=["shelly"],
            review_schedule={"monthly": "12", "yearly": "07-01"},
            quarterly_review_enabled=True,
        )
        scheduler = LifeScheduler(service=_FakeService(self.db), config=cfg)
        self.assertTrue(scheduler._review_due(datetime(2026, 1, 1), "quarterly"))
        self.assertFalse(scheduler._review_due(datetime(2026, 2, 1), "quarterly"))
        count = scheduler.seed_plans(["shelly"], datetime(2026, 1, 1))
        self.assertEqual(count, 3)
        items = self.db.list_plans("shelly", "2026-01-01")
        task_ids = {item["task_id"] for item in items}
        self.assertIn("review-quarterly", task_ids)
        self.assertNotIn("review-monthly", task_ids)
        target = scheduler.next_target(datetime(2026, 1, 1, 8, 0), ["shelly"])
        self.assertEqual(target[2], "review")
        self.assertEqual(target[3], "review-quarterly")

    def test_lease_uses_memory_host_when_configured(self):
        memory = _FakeMemoryLease()
        service = _FakeServiceWithMemory(self.db, memory)
        cfg = LifeConfig(
            memory_host="astrbot_plugin_engram_core",
            memory_lease_ttl_seconds=120,
        )
        scheduler = LifeScheduler(service=service, config=cfg)
        self.assertTrue(scheduler._acquire_lease("shelly", "key-1", "browse"))
        self.assertEqual(
            memory.claims,
            [("shelly", "key-1", scheduler._instance_id, 120)],
        )
        scheduler._release_lease("shelly", "key-1")
        self.assertEqual(
            memory.releases,
            [("shelly", "key-1", scheduler._instance_id)],
        )
        denied = _FakeMemoryLease(claimed=False)
        scheduler2 = LifeScheduler(
            service=_FakeServiceWithMemory(self.db, denied), config=cfg
        )
        self.assertFalse(scheduler2._acquire_lease("shelly", "key-2", "browse"))

    def test_lease_falls_back_to_local_sqlite(self):
        service = _FakeService(self.db)
        cfg = LifeConfig(lease_ttl_seconds=60)
        scheduler = LifeScheduler(service=service, config=cfg)
        self.assertTrue(scheduler._acquire_lease("shelly", "local-key", "browse"))
        scheduler._release_lease("shelly", "local-key")
        self.assertTrue(scheduler._acquire_lease("shelly", "local-key", "browse"))
        scheduler._release_lease("shelly", "local-key")

    def test_next_target_includes_pending_optional_plan(self):
        self.scheduler.seed_plans(["shelly"], datetime(2026, 8, 12))
        self.db.add_optional_plan(
            "shelly", "2026-08-12", "extra-1", "peek",
            "2026-08-12 08:00:00",
        )
        target = self.scheduler.next_target(datetime(2026, 8, 12, 7, 0), ["shelly"])
        self.assertEqual(target[0], datetime(2026, 8, 12, 8, 0))
        self.assertEqual(target[1], "shelly")
        self.assertEqual(target[2], "peek")
        self.assertEqual(target[3], "extra-1")

    def test_plan_status_mapping(self):
        class _Result:
            def __init__(self, status, reason="", error=""):
                self.status = status
                self.reason = reason
                self.error = error

        self.assertEqual(
            self.scheduler._plan_status_browse(_Result("completed")), ("done", "")
        )
        self.assertEqual(
            self.scheduler._plan_status_browse(_Result("skipped", "sleep_window")),
            ("skipped", "sleep_window"),
        )
        self.assertEqual(
            self.scheduler._plan_status_browse(_Result("error", "", "boom")),
            ("failed", "boom"),
        )
        self.assertEqual(
            self.scheduler._plan_status_diary({"date": "2026-08-12"}), ("done", "")
        )
        self.assertEqual(
            self.scheduler._plan_status_diary({"skipped": "budget_exhausted"}),
            ("skipped", "budget_exhausted"),
        )
        self.assertEqual(
            self.scheduler._plan_status_diary({"error": "boom"}), ("failed", "boom")
        )

    def test_budget_delta_uses_tokens(self):
        before = {"tokens": 10, "llm_calls": 1}
        after = {"tokens": 34, "llm_calls": 2}
        self.assertEqual(self.scheduler._budget_delta(before, after), 24.0)
        self.assertEqual(self.scheduler._budget_delta(None, None), 0.0)

    def test_jitter_crossing_midnight_keeps_plan_anchored(self):
        cfg = LifeConfig(
            browse_times=[], diary_time="23:00",
            browse_jitter_minutes=0, diary_jitter_minutes=60,
            peek_times=[], life_personas=["shelly"],
        )
        scheduler = LifeScheduler(service=_FakeService(self.db), config=cfg)
        with patch(
            "life.scheduler.deterministic_offset",
            return_value=timedelta(minutes=60),
        ):
            count = scheduler.seed_plans(["shelly"], datetime(2026, 8, 12))
            rows = self.db.list_plans("shelly", "2026-08-12")
            self.assertEqual(count, 1)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["task_id"], "diary-23-00")
            self.assertEqual(rows[0]["plan_date"], "2026-08-12")
            self.assertEqual(rows[0]["scheduled_at"], "2026-08-13 00:00:00")
            target = scheduler.next_target(
                datetime(2026, 8, 12, 23, 0), ["shelly"]
            )
            self.assertIsNotNone(target)
            self.assertEqual(target[0], datetime(2026, 8, 13, 0, 0))
            self.assertEqual(target[3], "diary-23-00")
            self.assertEqual(target[4], "2026-08-12")
            self.assertTrue(self.db.update_plan(
                "shelly", target[4], target[3], "done",
                reason="ok",
                finished_at="2026-08-13 00:01:00",
            ))

    def test_scheduler_loop_exits_when_disabled(self):
        class _TrackingService(_FakeService):
            def __init__(self, db):
                super().__init__(db)
                self.calls: list[str] = []

            async def run_browse_session(self, persona_id, trigger):
                self.calls.append(persona_id)
                return None

            def record_skipped_duplicate(self, persona_id, kind, slot):
                self.calls.append("skip")

        service = _TrackingService(self.db)
        cfg = LifeConfig(
            enabled=False, browse_times=["10:00"], diary_time="23:00",
            browse_jitter_minutes=0, diary_jitter_minutes=0,
            peek_times=[], life_personas=["shelly"],
        )
        scheduler = LifeScheduler(service=service, config=cfg)

        async def run():
            task = asyncio.create_task(scheduler._run())
            await asyncio.sleep(0.05)
            scheduler._stop.set()
            await task

        asyncio.run(run())
        self.assertEqual(service.calls, [])


if __name__ == "__main__":
    unittest.main()