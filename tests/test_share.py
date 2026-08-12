import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.config import load_config
from life.db import LifeDB
from life.esm_adapter import ESMAdapter
from life.persona import PersonaPrompt
from life.share import ShareGate


class _FakeLLM:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    async def chat_json(self, prompt):
        if self.error:
            raise self.error
        return self.payload


class _FakePersonas:
    async def resolve(self, persona_id):
        return PersonaPrompt(persona_id, "你是测试人格。", "persona", "ok", "")


class _NoStarContext:
    def get_registered_star(self, plugin_id):
        return None


class ShareGateTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")
        self.config = load_config({
            "sleep_window": "00:00-00:01",
            "share_enabled": True,
            "share_daily_cap": 2,
            "share_cooldown_minutes": 360,
            "share_sessions": {"shelly": ["sid-1"]},
            "share_silence_rate": 0.0,
        })
        self.esm = ESMAdapter(_NoStarContext(), scope_prefix="internet-life", energy_gate=0.3)
        self.llm = _FakeLLM(payload={"message": "今天看到个有趣的东西"})
        self.sent = []

        async def sender(session_id, text):
            self.sent.append((session_id, text))
            return True

        self.gate = ShareGate(
            self.config, self.db, self.esm, self.llm, _FakePersonas(),
            sender=sender, now_fn=datetime.now,
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def _note(self, note_id):
        return self.db.get_note(note_id)

    async def test_sent_path(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "T", "S",
                                   share_decision={"should_share": True, "target": "sid-1"},
                                   url_hash="h1")
        result = await self.gate.attempt_share("shelly", self._note(note_id),
                                               {"should_share": True, "target": "sid-1"})
        self.assertEqual(result.status, "sent")
        self.assertEqual(self._note(note_id)["share_status"], "shared")
        self.assertEqual(self.db.count_share_success("shelly"), 1)
        self.assertEqual(len(self.sent), 1)

    async def test_silence_rate_skips_without_share_log(self):
        self.config.share_silence_rate = 1.0
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "T", "S",
                                   share_decision={"should_share": True, "target": "sid-1"},
                                   url_hash="h6")
        result = await self.gate.attempt_share("shelly", self._note(note_id),
                                               {"should_share": True, "target": "sid-1"})
        self.assertEqual(result.status, "silent")
        self.assertEqual(result.reason, "share_silence")
        self.assertEqual(self.db.count_share_success("shelly"), 0)
        self.assertEqual(len(self.sent), 0)
        self.assertEqual(len(self.db.list_share_log("shelly")), 0)
        self.assertEqual(self._note(note_id)["share_status"], "dropped")
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertTrue(self.db.has_snapshot_activity("shelly", today, "share_silent"))

    async def test_silence_applies_whole_day(self):
        self.config.share_silence_rate = 0.0
        today = datetime.now().strftime("%Y-%m-%d")
        self.db.add_state_snapshot("shelly", "share_silent", 0.8, "")
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "T", "S",
                                   share_decision={"should_share": True, "target": "sid-1"},
                                   url_hash="h7")
        result = await self.gate.attempt_share("shelly", self._note(note_id),
                                               {"should_share": True, "target": "sid-1"})
        self.assertEqual(result.status, "silent")
        self.assertEqual(len(self.db.list_share_log("shelly")), 0)
        self.assertEqual(len(self.sent), 0)
        self.assertTrue(self.db.has_snapshot_activity("shelly", today, "share_silent"))

    async def test_manual_force_bypasses_silence(self):
        self.config.share_silence_rate = 1.0
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "T", "S",
                                   share_decision={"should_share": True, "target": "sid-1"},
                                   url_hash="h8")
        result = await self.gate.attempt_share("shelly", self._note(note_id),
                                               {"should_share": True, "target": "sid-1"},
                                               force=True)
        self.assertEqual(result.status, "sent")
        self.assertEqual(len(self.sent), 1)

    async def test_invalid_target_drops(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "T", "S",
                                   share_decision={"should_share": True, "target": "bad"},
                                   url_hash="h2")
        result = await self.gate.attempt_share("shelly", self._note(note_id),
                                               {"should_share": True, "target": "bad"})
        self.assertEqual(result.status, "blocked")
        self.assertEqual(result.reason, "invalid_target")
        self.assertEqual(self._note(note_id)["share_status"], "dropped")

    async def test_daily_cap_keeps_pending(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "T", "S",
                                   share_decision={"should_share": True, "target": "sid-1"},
                                   url_hash="h3")
        self.db.log_share_attempt("shelly", None, "sent", target_sid="sid-1")
        self.db.log_share_attempt("shelly", None, "sent", target_sid="sid-2")
        result = await self.gate.attempt_share("shelly", self._note(note_id),
                                               {"should_share": True, "target": "sid-1"})
        self.assertEqual(result.reason, "daily_cap")
        self.assertEqual(self._note(note_id)["share_status"], "")

    async def test_cooldown_keeps_pending(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "T", "S",
                                   share_decision={"should_share": True, "target": "sid-1"},
                                   url_hash="h4")
        self.db.log_share_attempt("shelly", None, "sent", target_sid="sid-1")
        result = await self.gate.attempt_share("shelly", self._note(note_id),
                                               {"should_share": True, "target": "sid-1"})
        self.assertEqual(result.reason, "cooldown")
        self.assertEqual(self._note(note_id)["share_status"], "")

    async def test_not_triggered(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "T", "S",
                                   share_decision={"should_share": False},
                                   url_hash="h5")
        result = await self.gate.attempt_share("shelly", self._note(note_id),
                                               {"should_share": False})
        self.assertEqual(result.status, "not_triggered")
        self.assertEqual(self.db.count_share_success("shelly"), 0)


if __name__ == "__main__":
    unittest.main()