import os
import random
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.db import LifeDB
from life.interests import InterestStore, next_weight


class InterestsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")
        self.persona = "shelly"

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_next_weight(self):
        self.assertAlmostEqual(next_weight(0.5, 0.5), 0.45)
        self.assertAlmostEqual(next_weight(0.5, 1.0), 0.70)
        self.assertLessEqual(next_weight(1.0, 1.0), 1.0)

    def test_seed_and_pick(self):
        store = InterestStore(self.db, [("ai", "人工智能"), ("tech", "科技")])
        store.seed(self.persona)
        topics = store.pick_topics(self.persona, count=2, explore_probability=0,
                                   rng=random.Random(1))
        self.assertEqual(topics, ["人工智能", "科技"])

    def test_apply_note_and_updates(self):
        store = InterestStore(self.db, [("ai", "人工智能")])
        store.seed(self.persona)
        store.apply_note(self.persona, "ai", "人工智能", 0.9)
        row = self.db.get_interests(self.persona)[0]
        self.assertGreater(row["weight"], 0.5)
        self.assertEqual(row["seen_count"], 1)

        store.apply_updates(self.persona, {"tech": {"name": "科技", "delta": 0.1}},
                            now=datetime(2026, 8, 10, 12, 0))
        tech = [r for r in self.db.get_interests(self.persona) if r["key"] == "tech"][0]
        self.assertAlmostEqual(tech["weight"], 0.6)

    def test_staging_same_key_accumulates_seen_count(self):
        store = InterestStore(self.db, [("ai", "浜哄伐鏅鸿兘")])
        store.seed(self.persona)
        store.stage_note(self.persona, 1, "ai", "浜哄伐鏅鸿兘", 0.9)
        store.stage_note(self.persona, 1, "ai", "浜哄伐鏅鸿兘", 0.9)
        self.db.commit_staged(self.persona, 1, status="completed")
        row = next(r for r in self.db.get_interests(self.persona) if r["key"] == "ai")
        self.assertEqual(row["seen_count"], 2)
        self.assertGreater(row["weight"], 0.5)

    def test_daily_decay(self):
        store = InterestStore(self.db, [("ai", "人工智能")])
        self.db.upsert_interest(self.persona, "ai", "人工智能", 1.0, seen_count=3)
        store.daily_decay(self.persona)
        self.assertAlmostEqual(self.db.get_interests(self.persona)[0]["weight"], 0.98)


if __name__ == "__main__":
    unittest.main()