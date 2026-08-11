import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.db import LifeDB
from life.life_tool import LifeMemoryTool, LifePlansTool, search_life_memory


class _FakeEvent:
    unified_msg_origin = "aiocqhttp:GroupMessage:123"


class _FakeConversation:
    persona_id = "shelly"


class _FakeConvManager:
    async def get_curr_conversation_id(self, umo):
        return "c1"

    async def get_conversation(self, umo, conv_id):
        return _FakeConversation()


class _FakePersonaManager:
    async def get_default_persona_v3(self, umo=""):
        return {"name": "shelly", "prompt": "x"}


class _FakeAgentContext:
    def __init__(self, with_managers=True):
        self.event = _FakeEvent()
        if with_managers:
            self.conversation_manager = _FakeConvManager()
            self.persona_manager = _FakePersonaManager()


class _FakeWrapper:
    def __init__(self, with_managers=True):
        self.context = _FakeAgentContext(with_managers)


class _FakePersonas:
    pass


class LifeToolTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_search_life_memory(self):
        self.db.add_note("shelly", None, "hn", "https://x", "AI story", "summary",
                         opinion="interesting", category="opinion", tags=["ai"],
                         url_hash="h1")
        self.db.add_note("alice", None, "hn", "https://y", "Other", "s", url_hash="h2")
        self.db.add_diary("shelly", "2026-08-10", "今天看了 AI 的东西")
        result = search_life_memory(self.db, "shelly", query="AI", k=5)
        self.assertEqual(result["persona_id"], "shelly")
        self.assertEqual(result["count"], 2)
        kinds = {item["kind"] for item in result["items"]}
        self.assertEqual(kinds, {"note", "diary"})
        note_item = next(item for item in result["items"] if item["kind"] == "note")
        self.assertEqual(note_item["tags"], ["ai"])

    async def test_tool_resolves_persona(self):
        tool = LifeMemoryTool(self.db, _FakePersonas())
        self.db.add_note("shelly", None, "hn", "https://x", "AI story", "s",
                         url_hash="h3")
        raw = await tool.call(_FakeWrapper(), query="AI")
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["persona_id"], "shelly")
        self.assertEqual(data["count"], 1)

    async def test_tool_refuses_without_persona(self):
        tool = LifeMemoryTool(self.db, _FakePersonas())
        raw = await tool.call(_FakeWrapper(with_managers=False), query="AI")
        data = json.loads(raw)
        self.assertFalse(data["ok"])

    async def test_tool_recall_writes_event(self):
        tool = LifeMemoryTool(self.db, _FakePersonas())
        self.db.add_note("shelly", None, "hn", "https://x", "AI story", "s",
                         url_hash="h4")
        raw = await tool.call(_FakeWrapper(), query="AI")
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        events = self.db.list_events("shelly")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "recall")
        self.assertEqual(json.loads(events[0]["payload"])["query"], "AI")
        self.assertEqual(json.loads(events[0]["source_refs"]), [{"url": "https://x"}])
        self.assertTrue(events[0]["idempotency_key"])

    async def test_plans_tool_reads_board(self):
        self.db.ensure_plan("shelly", "2026-08-12", "browse-10-00", "browse",
                            scheduled_at="2026-08-12 10:00:00")
        self.db.update_plan("shelly", "2026-08-12", "browse-10-00", "done",
                            reason="ok", budget_used=3)
        tool = LifePlansTool(self.db, _FakePersonas())
        raw = await tool.call(_FakeWrapper(), date="2026-08-12")
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["count"], 1)
        self.assertEqual(data["summary"]["done"], 1)
        self.assertEqual(data["summary"]["pending"], 0)
        self.assertEqual(data["items"][0]["budget_used"], 3)
        self.assertEqual(data["items"][0]["status"], "done")


if __name__ == "__main__":
    unittest.main()