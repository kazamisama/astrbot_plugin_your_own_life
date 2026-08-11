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

    def test_register_api(self):
        context = _FakeContext()
        ok = register_api(context, self.db, service=None, share_gate=None,
                          personas=None, config=self.config)
        self.assertTrue(ok)
        routes = [r[0] for r in context.registrations]
        self.assertIn("/astrbot_plugin_your_own_life/api/overview", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/memory_search", routes)
        self.assertIn("/astrbot_plugin_your_own_life/api/usage", routes)
        self.assertEqual(len(routes), 11)


if __name__ == "__main__":
    unittest.main()