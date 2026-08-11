import os
import sys
import tempfile
import unittest
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
        self.assertEqual(len(routes), 20)


if __name__ == "__main__":
    unittest.main()