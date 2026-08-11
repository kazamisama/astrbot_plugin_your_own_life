import os
import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.timeutil import (
    DEFAULT_TIMEZONE,
    is_valid_timezone,
    local_now,
    local_today,
    normalize_timezone,
    to_local,
)


class TimeUtilTest(unittest.TestCase):
    def test_normalize_timezone(self):
        self.assertEqual(normalize_timezone("UTC"), "UTC")
        self.assertEqual(normalize_timezone("Asia/Shanghai"), "Asia/Shanghai")
        self.assertEqual(normalize_timezone("Mars/Olympus"), DEFAULT_TIMEZONE)
        self.assertEqual(normalize_timezone(""), DEFAULT_TIMEZONE)

    def test_is_valid_timezone(self):
        self.assertTrue(is_valid_timezone("UTC"))
        self.assertFalse(is_valid_timezone("Mars/Olympus"))
        self.assertFalse(is_valid_timezone(""))

    def test_to_local_utc_to_shanghai(self):
        instant = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(
            to_local(instant, "Asia/Shanghai"),
            datetime(2026, 8, 12, 2, 0),
        )

    def test_local_today_crosses_date(self):
        instant = datetime(2026, 8, 11, 18, 0, tzinfo=timezone.utc)
        self.assertEqual(local_today("Asia/Shanghai", instant), "2026-08-12")
        self.assertEqual(local_today("UTC", instant), "2026-08-11")

    def test_local_now_keeps_format(self):
        instant = datetime(2026, 8, 12, 12, 30, tzinfo=timezone.utc)
        self.assertEqual(local_now("UTC", instant), datetime(2026, 8, 12, 12, 30))


if __name__ == "__main__":
    unittest.main()
