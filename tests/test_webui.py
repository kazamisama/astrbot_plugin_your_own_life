import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.config import load_config
from life.db import LifeDB
from life.webui import build_handlers, register_api


class _FakeContext:
    def __init__(self):
        self.registrations = []

    def register_web_api(self, route, handler, methods, desc):
        self.registrations.append((route, methods, desc))


class _FakeMemory:
    def __init__(self):
        self.entities = [
            {"id": "e1", "entity_id": "tokio-rs/tokio", "dimension": "project",
             "name": "Tokio"},
            {"id": "p1", "entity_id": "hacker-news", "dimension": "platform",
             "name": "Hacker News"},
        ]
        self.links = [
            {"src_entity_id": "e1", "dst_entity_id": "p1",
             "relation": "appears_on", "seen_count": 2},
        ]

    def list_entities(self, persona_id, limit=500):
        return self.entities

    def list_links(self, persona_id, limit=1000):
        return self.links


class WebUITest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")
        self.config = load_config({"life_personas": ["shelly"]})

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def test_overview_handler(self):
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        result = await handlers["overview"]()
        self.assertEqual(result["persona_id"], "shelly")
        self.assertIn("stats", result)

    async def test_memory_search_handler(self):
        self.db.add_note("shelly", None, "hn", "https://x", "AI story", "s",
                         category="opinion", tags=["ai"], url_hash="h1")
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        result = await handlers["memory_search"]()
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["items"][0]["title"], "AI story")
        self.assertIn("temperature", result["items"][0])

    async def test_entities_handlers(self):
        config = load_config({
            "life_personas": ["shelly"],
            "memory_host": "astrbot_plugin_engram_core",
        })
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=config,
                                  memory_adapter=_FakeMemory())
        data = await handlers["entities"]()
        self.assertEqual(len(data["entities"]), 2)
        self.assertEqual(len(data["links"]), 1)
        self.assertEqual(data["links"][0]["relation"], "appears_on")
        empty = await handlers["entity_appears_on"]()
        self.assertEqual(empty["platforms"], [])

    async def test_entities_without_memory_returns_empty(self):
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        data = await handlers["entities"]()
        self.assertEqual(data["entities"], [])
        self.assertEqual(data["links"], [])

    async def test_capsules_handler(self):
        note_id = self.db.add_note(
            "shelly", None, "hn", "https://cap", "Cap", "s", url_hash="cu1"
        )
        self.db.seal_capsule(
            "shelly", note_id, "2099-01-01 00:00:00",
            sealed_at="2026-08-01 00:00:00",
        )
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        data = await handlers["capsules"]()
        self.assertEqual(len(data["capsules"]), 1)
        self.assertEqual(data["capsules"][0]["title"], "Cap")
        bad = await handlers["capsules_open"]()
        self.assertFalse(bad["ok"])

    async def test_reviews_handlers(self):
        self.db.upsert_review(
            "shelly", "quarterly", "2026-04-01", "2026-06-30",
            "第一版", confidence=0.7,
        )
        self.db.upsert_review(
            "shelly", "quarterly", "2026-01-01", "2026-03-31",
            "上一版", confidence=0.6,
        )
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        data = await handlers["reviews"]()
        self.assertEqual(len(data["reviews"]), 2)
        self.assertAlmostEqual(data["reviews"][0]["confidence"], 0.7)
        missing = await handlers["reviews_diff"]()
        self.assertFalse(missing["ok"])

    async def test_usage_handler(self):
        self.db.increment_llm_usage("shelly", "2026-08-12", calls=2, tokens=10)
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        result = await handlers["usage"]()
        self.assertEqual(result["persona_id"], "shelly")
        self.assertEqual(result["usage"][0]["llm_calls"], 2)

    async def test_trash_and_change_log_handlers(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "T", "s", url_hash="hx")
        self.db.soft_delete_note("shelly", note_id)
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        trash = await handlers["trash"]()
        self.assertEqual(len(trash["notes"]), 1)
        logs = await handlers["change_log"]()
        self.assertEqual(len(logs["logs"]), 1)

    async def test_injection_log_handler(self):
        self.db.log_injection("shelly", source="hn", context="browse", field="summary", preview="x")
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        result = await handlers["injection_log"]()
        self.assertEqual(len(result["logs"]), 1)
        self.assertEqual(result["logs"][0]["context"], "browse")

    async def test_wishlist_handlers(self):
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_wishlist("shelly", sid, "研究图谱数据库", interest_key="graph", source="diary")
        self.db.commit_staged("shelly", sid, status="completed")
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        listed = await handlers["wishlist"]()
        self.assertEqual(len(listed["items"]), 1)
        self.assertEqual(listed["items"][0]["status"], "pending")
        invalid = await handlers["wishlist_action"]()
        self.assertFalse(invalid["ok"])

    async def test_plans_handler(self):
        today = datetime.now().strftime("%Y-%m-%d")
        self.db.ensure_plan("shelly", today, "browse-10-00", "browse",
                            scheduled_at=f"{today} 10:00:00")
        self.db.update_plan("shelly", today, "browse-10-00", "done", budget_used=5)
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        result = await handlers["plans"]()
        self.assertEqual(result["plan_date"], today)
        self.assertEqual(result["summary"]["total"], 1)
        self.assertEqual(result["items"][0]["status"], "done")

    async def test_events_handler(self):
        self.db.append_event(
            "shelly", "observe", {"n": 1}, [{"url": "https://x"}],
            "e/1", ts="2026-08-12 10:00:00",
        )
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        result = await handlers["events"]()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["items"][0]["kind"], "observe")
        self.assertEqual(len(result["replay"]["items"]), 1)
        self.assertTrue(result["replay"]["read_only"])
        filtered = await handlers["events"]()
        self.assertEqual(filtered["items"][0]["idempotency_key"], "e/1")

    async def test_timeline_handler(self):
        self.db.add_note("shelly", None, "hn", "https://x", "T", "s", url_hash="tl")
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        result = await handlers["timeline"]()
        self.assertEqual(result["persona_id"], "shelly")
        self.assertGreaterEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["kind"], "note")

    async def test_status_and_heatmap_handlers(self):
        self.db.add_note("shelly", None, "hn", "https://x", "T", "s", url_hash="hx")
        handlers = build_handlers(self.db, service=None, share_gate=None,
                                  personas=None, config=self.config)
        status = await handlers["status"]()
        self.assertEqual(status["persona_id"], "shelly")
        self.assertEqual(status["notes_count"], 1)
        heat = await handlers["heatmap"]()
        self.assertGreaterEqual(len(heat["days"]), 1)

    def test_register_api(self):
        context = _FakeContext()
        ok = register_api(context, self.db, service=None, share_gate=None,
                          personas=None, config=self.config)
        self.assertTrue(ok)
        routes = [r[0] for r in context.registrations]
        self.assertIn("/astrbot_plugin_your_own_life/api/overview", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/status", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/timeline/heatmap", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/timeline", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/memory_search", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/usage", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/trash", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/trash_restore", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/change_log", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/injection_log", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/plans", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/events", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/capsules", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/capsules_open", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/reviews", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/reviews_diff", routes)
        self.assertEqual(len(routes), 28)


if __name__ == "__main__":
    unittest.main()