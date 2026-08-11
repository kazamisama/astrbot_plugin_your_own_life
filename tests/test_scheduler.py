import os
import sys
import unittest
from datetime import datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.config import LifeConfig, SleepWindow
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
                         life_personas=["shelly"])
        scheduler = LifeScheduler(service=None, config=cfg)
        target = scheduler.next_target(datetime(2026, 8, 10, 16, 0), ["shelly"])
        self.assertEqual(target[0], datetime(2026, 8, 10, 23, 0))
        self.assertEqual(target[2], "diary")

    def test_sleep_window_contains(self):
        window = SleepWindow(time(23, 0), time(7, 0))
        self.assertTrue(window.contains(datetime(2026, 8, 10, 0, 30)))
        self.assertFalse(window.contains(datetime(2026, 8, 10, 12, 0)))

    def test_current_target_uses_configured_timezone(self):
        cfg = LifeConfig(
            browse_times=["10:00", "15:00"], diary_time="23:00",
            browse_jitter_minutes=0, diary_jitter_minutes=0,
            life_personas=["shelly"], timezone="America/New_York",
        )
        scheduler = LifeScheduler(
            service=None, config=cfg,
            now_fn=lambda: datetime(2026, 8, 12, 23, 30),
        )
        target = scheduler._current_target(["shelly"])
        self.assertEqual(target[0], datetime(2026, 8, 12, 15, 0))
        self.assertEqual(target[2], "browse")


if __name__ == "__main__":
    unittest.main()