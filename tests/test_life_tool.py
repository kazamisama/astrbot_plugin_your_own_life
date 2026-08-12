import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.db import LifeDB
from life.life_tool import (
    LifeEditTool,
    LifeMemoryTool,
    LifePlanEditTool,
    LifePlansTool,
    LifeStatusTool,
    edit_life_memory,
    query_life_status,
    recall_life_memory,
    search_life_memory,
)


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
        self.assertIn("temperature", note_item)

    def test_recall_rehydrates_and_weights_by_temperature(self):
        cold = self.db.add_note("shelly", None, "hn", "https://cold", "Cold memory", "s", url_hash="r-cold")
        hot = self.db.add_note("shelly", None, "hn", "https://hot", "Hot memory", "s", url_hash="r-hot")
        self.db._execute("UPDATE notes SET temperature = ? WHERE id = ?", (0.2, cold))
        self.db._execute("UPDATE notes SET temperature = ? WHERE id = ?", (0.9, hot))
        data = recall_life_memory(self.db, "shelly", query="memory", k=5)
        self.assertEqual(data["items"][0]["id"], hot)
        self.assertAlmostEqual(data["items"][0]["temperature"], 0.9)
        self.assertEqual(self.db.get_note(cold)["temperature"], 1.0)
        self.assertEqual(self.db.get_note(hot)["temperature"], 1.0)

    def test_edit_life_memory_allowed_and_pending(self):
        note_id = self.db.add_note(
            "shelly", None, "hn", "https://x", "T", "Old summary", url_hash="et1"
        )
        data = edit_life_memory(
            self.db, "shelly", "update", entity="note",
            entity_id=str(note_id), field="summary", value="New summary",
            allowed=["note.summary"],
        )
        self.assertTrue(data["ok"])
        self.assertEqual(self.db.get_note(note_id)["summary"], "New summary")
        pending = edit_life_memory(
            self.db, "shelly", "update", entity="note",
            entity_id=str(note_id), field="title", value="New title",
            allowed=["note.summary"],
        )
        self.assertTrue(pending["needs_owner_confirmation"])
        entry = self.db.get_change_log_entry("shelly", pending["change_id"])
        self.assertEqual(entry["status"], "pending_owner")

    def test_edit_tool_cannot_rollback_another_actor_change(self):
        note_id = self.db.add_note(
            "shelly", None, "hn", "https://x", "T", "Old", url_hash="rt1"
        )
        owner = edit_life_memory(
            self.db, "shelly", "update", entity="note",
            entity_id=str(note_id), field="summary", value="Owner new",
            allowed=["note.summary"], actor="owner", reason="owner edit",
        )
        self.assertTrue(owner["ok"])
        log_id = owner["change_id"]
        data = edit_life_memory(
            self.db, "shelly", "rollback", change_id=log_id, actor="llm",
        )
        self.assertFalse(data["ok"])
        self.assertIn("another actor", data["error"])
        entry = self.db.get_change_log_entry("shelly", log_id)
        self.assertEqual(entry["status"], "applied")
        self.assertEqual(self.db.get_note(note_id)["summary"], "Owner new")
        ok = edit_life_memory(
            self.db, "shelly", "rollback", change_id=log_id, actor="owner",
        )
        self.assertTrue(ok["ok"])
        self.assertEqual(self.db.get_note(note_id)["summary"], "Old")

    async def test_edit_tool_updates_and_rolls_back(self):
        tool = LifeEditTool(self.db, _FakePersonas(), allowed=["note.summary"])
        note_id = self.db.add_note(
            "shelly", None, "hn", "https://x", "T", "Old", url_hash="et2"
        )
        raw = await tool.call(
            _FakeWrapper(), action="update", entity="note",
            entity_id=str(note_id), field="summary", value="New",
        )
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        change_id = data["change_id"]
        raw = await tool.call(_FakeWrapper(), action="rollback", change_id=change_id)
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(self.db.get_note(note_id)["summary"], "Old")
        events = self.db.list_events("shelly")
        self.assertEqual(events[0]["kind"], "change")

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

    async def test_edit_plan_tool_add_skip_and_fixed_guard(self):
        self.db.ensure_plan("shelly", "2026-08-12", "browse-10-00", "browse",
                            scheduled_at="2026-08-12 10:00:00", fixed=True)
        tool = LifePlanEditTool(self.db, _FakePersonas())
        raw = await tool.call(_FakeWrapper(), action="add", task_id="extra-1",
                              date="2026-08-12", kind="peek", time="12:00",
                              reason="try")
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        raw = await tool.call(_FakeWrapper(), action="skip", task_id="extra-1",
                              date="2026-08-12", reason="not now")
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        raw = await tool.call(_FakeWrapper(), action="skip", task_id="browse-10-00",
                              date="2026-08-12", reason="no")
        data = json.loads(raw)
        self.assertFalse(data["ok"])
        items = self.db.list_plans("shelly", "2026-08-12")
        extra = next(item for item in items if item["task_id"] == "extra-1")
        self.assertEqual(extra["status"], "skipped")
        self.assertEqual(extra["reason"], "not now")

    def test_query_life_status_returns_sections(self):
        sid = self.db.start_browse_session(
            "shelly", "scheduled", 0.6, "curious"
        )
        self.db.finish_browse_session(sid, "completed", 2, "")
        self.db.add_state_snapshot(
            "shelly", "browse", 0.5, "curious",
            extra='{"trigger": "scheduled"}',
        )
        self.db.add_note(
            "shelly", None, "hn", "https://x", "Morning AI news",
            "summary", url_hash="st1",
        )
        self.db.append_event(
            "shelly", "observe",
            {"entity": "browse", "session_id": sid, "notes_count": 2},
            [{"url": "https://x"}],
            f"session/{sid}/observe",
        )
        data = query_life_status(self.db, "shelly")
        self.assertEqual(data["persona_id"], "shelly")
        self.assertEqual(data["stats"]["completed"], 1)
        self.assertEqual(len(data["sessions"]), 1)
        self.assertEqual(len(data["snapshots"]), 1)
        self.assertEqual(len(data["events"]), 1)
        self.assertEqual(data["events"][0]["kind"], "observe")
        self.assertEqual(data["notes"][0]["title"], "Morning AI news")
        self.assertEqual(data["notes"][0]["url"], "https://x")

    async def test_status_tool_reads_activity_and_writes_recall(self):
        sid = self.db.start_browse_session("shelly", "scheduled", 0.6, "")
        self.db.finish_browse_session(sid, "completed", 1, "")
        self.db.add_state_snapshot("shelly", "browse", 0.5, "curious")
        self.db.add_note(
            "shelly", None, "hn", "https://x", "Morning AI news",
            "summary", url_hash="st2",
        )
        self.db.append_event(
            "shelly", "observe",
            {"entity": "browse", "session_id": sid, "notes_count": 1},
            [{"url": "https://x"}],
            f"session/{sid}/observe-2",
        )
        tool = LifeStatusTool(self.db, _FakePersonas())
        raw = await tool.call(_FakeWrapper())
        data = json.loads(raw)
        self.assertTrue(data["ok"])
        self.assertEqual(data["persona_id"], "shelly")
        self.assertTrue(data["sessions"])
        self.assertTrue(data["snapshots"])
        self.assertTrue(data["events"])
        self.assertTrue(any(
            n["title"] == "Morning AI news" for n in data["notes"]
        ))
        events = self.db.list_events("shelly")
        self.assertEqual(events[0]["kind"], "recall")
        self.assertEqual(json.loads(events[0]["payload"])["query"], "life_status")

    async def test_status_tool_refuses_without_persona(self):
        tool = LifeStatusTool(self.db, _FakePersonas())
        raw = await tool.call(_FakeWrapper(with_managers=False))
        data = json.loads(raw)
        self.assertFalse(data["ok"])


if __name__ == "__main__":
    unittest.main()