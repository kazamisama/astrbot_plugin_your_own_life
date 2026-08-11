import os
import sys
import unittest
from datetime import datetime, time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.config import SleepWindow, load_config, parse_interest_line


class ConfigTest(unittest.TestCase):
    def test_sleep_window_day_and_overnight(self):
        day = SleepWindow(time(0, 0), time(7, 0))
        self.assertTrue(day.contains(datetime(2026, 8, 10, 3, 0)))
        self.assertFalse(day.contains(datetime(2026, 8, 10, 9, 0)))
        night = SleepWindow(time(23, 0), time(7, 0))
        self.assertTrue(night.contains(datetime(2026, 8, 10, 23, 30)))
        self.assertTrue(night.contains(datetime(2026, 8, 11, 1, 0)))
        self.assertFalse(night.contains(datetime(2026, 8, 11, 12, 0)))

    def test_parse_interest_line(self):
        self.assertEqual(parse_interest_line("ai:人工智能"), ("ai", "人工智能"))
        self.assertEqual(parse_interest_line("open-source"), ("open-source", "open-source"))
        self.assertEqual(parse_interest_line(""), ("", ""))

    def test_load_config_defaults_and_overrides(self):
        cfg = load_config({
            "browse_times": ["09:00", "17:00"],
            "diary_time": "22:00",
            "energy_gate": "0.5",
            "notes_min": 2,
            "notes_max": 4,
            "interests_initial": ["tech:科技", "ai:人工智能"],
        })
        self.assertEqual(cfg.browse_times, ["09:00", "17:00"])
        self.assertEqual(cfg.diary_time, "22:00")
        self.assertEqual(cfg.energy_gate, 0.5)
        self.assertEqual(cfg.notes_min, 2)
        self.assertEqual(cfg.notes_max, 4)
        self.assertEqual(cfg.interests_initial, [("tech", "科技"), ("ai", "人工智能")])

    def test_notes_range_is_coherent(self):
        cfg = load_config({"notes_min": 5, "notes_max": 2})
        self.assertGreaterEqual(cfg.notes_max, cfg.notes_min)


if __name__ == "__main__":
    unittest.main()