import os
import sys
import tempfile
import unittest
from datetime import datetime, time
from pathlib import Path

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
        task_ids = {item["task_id"] for item in items}
        self.assertIn("browse-10-00", task_ids)
        self.assertIn("browse-15-00", task_ids)
        self.assertIn("peek-09-00", task_ids)
        self.assertIn("diary-23-00", task_ids)

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


if __name__ == "__main__":
    unittest.main()