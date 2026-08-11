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

    def test_timezone_config(self):
        cfg = load_config({"timezone": "UTC"})
        self.assertEqual(cfg.timezone, "UTC")
        self.assertFalse(cfg.timezone_error)
        invalid = load_config({"timezone": "Mars/Olympus"})
        self.assertEqual(invalid.timezone, "Asia/Shanghai")
        self.assertTrue(invalid.timezone_error)
        default = load_config({})
        self.assertEqual(default.timezone, "Asia/Shanghai")
        self.assertFalse(default.timezone_error)

    def test_llm_budget_defaults(self):
        cfg = load_config({})
        self.assertEqual(cfg.daily_llm_call_limit, 0)
        self.assertEqual(cfg.daily_token_budget, 0)
        self.assertEqual(cfg.llm_retry_limit, 3)
        cfg = load_config({
            "daily_llm_call_limit": "5",
            "daily_token_budget": "1000",
            "llm_retry_limit": "4",
        })
        self.assertEqual(cfg.daily_llm_call_limit, 5)
        self.assertEqual(cfg.daily_token_budget, 1000)
        self.assertEqual(cfg.llm_retry_limit, 4)

    def test_trash_retention_default(self):
        cfg = load_config({})
        self.assertEqual(cfg.trash_retention_days, 30)
        cfg = load_config({"trash_retention_days": "7"})
        self.assertEqual(cfg.trash_retention_days, 7)

    def test_injection_log_enabled_default(self):
        self.assertTrue(load_config({}).injection_log_enabled)
        self.assertFalse(load_config({"injection_log_enabled": False}).injection_log_enabled)

    def test_lease_ttl_default(self):
        self.assertEqual(load_config({}).lease_ttl_seconds, 300)
        self.assertEqual(load_config({"lease_ttl_seconds": "60"}).lease_ttl_seconds, 60)

    def test_signature_enabled_default(self):
        self.assertTrue(load_config({}).signature_enabled)
        self.assertFalse(load_config({"signature_enabled": False}).signature_enabled)

    def test_revisit_config(self):
        cfg = load_config({})
        self.assertEqual(cfg.revisit_days, [7, 30])
        self.assertEqual(cfg.revisit_probability, 0.5)
        cfg = load_config({"revisit_days": ["14", "30", "0"], "revisit_probability": "0.8"})
        self.assertEqual(cfg.revisit_days, [14, 30])
        self.assertEqual(cfg.revisit_probability, 0.8)
        self.assertEqual(load_config({"revisit_probability": "9"}).revisit_probability, 1.0)

    def test_rest_probability_config(self):
        self.assertEqual(load_config({}).rest_probability, 0.1)
        self.assertEqual(load_config({"rest_probability": "0.25"}).rest_probability, 0.25)
        self.assertEqual(load_config({"rest_probability": "9"}).rest_probability, 1.0)


if __name__ == "__main__":
    unittest.main()