import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.browser import LifeService
from life.config import load_config
from life.db import LifeDB
from life.esm_adapter import ESMAdapter
from life.fetchers import FetchedItem
from life.interests import InterestStore
from life.llm import BudgetExhausted, LLMError
from life.persona import PersonaPrompt, PersonaUnavailable


class _FakeLLM:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = 0

    async def chat_json_managed(self, prompt, retry_limit=3, can_call=None, on_usage=None):
        self.calls += 1
        if can_call is not None:
            can_call()
        if self.error:
            raise self.error
        if on_usage is not None:
            on_usage(None)
        return self.payload

    async def chat_json(self, prompt, retries=2):
        return await self.chat_json_managed(prompt, retry_limit=retries)


class _FakePersonas:
    def __init__(self, prompt="你是测试人格。", unavailable=False):
        self.prompt = prompt
        self.unavailable = unavailable
        self.error = None

    async def resolve(self, persona_id):
        if self.unavailable:
            raise PersonaUnavailable("no prompt")
        return PersonaPrompt(persona_id, self.prompt, "persona", "ok", "")

    def mark_error(self, persona_id, error):
        self.error = error


class _FakeShareGate:
    def __init__(self):
        self.attempts = []
        self.rechecks = 0

    async def attempt_share(self, persona_id, note, decision):
        self.attempts.append((persona_id, note["id"], decision))
        return None

    async def recheck_pending(self, persona_id):
        self.rechecks += 1
        return 0


async def _fake_fetcher(config, client, queries):
    return [
        FetchedItem(source="hacker-news", url="https://example.com/1",
                    title="Story 1", summary="summary 1"),
        FetchedItem(source="github", url="https://example.com/2",
                    title="Repo 2", summary="summary 2"),
    ]


class _NoStarContext:
    def get_registered_star(self, plugin_id):
        return None


class BrowserServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")
        self.config = load_config({"sleep_window": "00:00-00:01",
                                   "share_sessions": {"shelly": ["sid-1"]}})
        self.interests = InterestStore(self.db, self.config.interests_initial)
        self.esm = ESMAdapter(_NoStarContext(), scope_prefix="internet-life", energy_gate=0.3)
        self.personas = _FakePersonas()
        self.share_gate = _FakeShareGate()
        self.service = LifeService(
            self.config, self.db, self.interests, self.esm, _FakeLLM(payload={}),
            self.personas, share_gate=self.share_gate, fetcher_fn=_fake_fetcher,
            now_fn=datetime.now,
        )

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def test_browse_and_diary_end_to_end(self):
        payload = {
            "selected": [
                {"index": 0, "summary": "s1", "opinion": "o1", "mood": "curious",
                 "interest_level": 0.8, "interest_key": "ai", "interest_name": "人工智能",
                 "category": "opinion", "tags": ["ai"],
                 "share": {"should_share": True, "reason": "interesting", "target": "sid-1"}},
                {"index": 1, "summary": "s2", "opinion": "o2", "mood": "calm",
                 "interest_level": 0.6, "interest_key": "tech", "interest_name": "科技",
                 "category": "observation", "tags": [],
                 "share": {"should_share": False, "reason": "", "target": ""}},
            ],
            "session_mood": "curious",
        }
        self.service.llm = _FakeLLM(payload=payload)
        result = await self.service.run_browse_session("shelly", "scheduled")
        self.assertEqual(result.status, "completed")
        self.assertEqual(result.notes_count, 2)
        notes = self.db.list_notes("shelly")
        self.assertEqual({n["opinion"] for n in notes}, {"o1", "o2"})
        self.assertEqual(notes[0]["category"], "observation")
        self.assertEqual(len(self.share_gate.attempts), 1)
        usage = self.db.get_daily_usage("shelly", datetime.now().strftime("%Y-%m-%d"))
        self.assertIsNotNone(usage)
        self.assertGreaterEqual(usage["llm_calls"], 1)

        diary_payload = {
            "diary_text": "今天看到了一些有趣的东西。",
            "mood": "curious",
            "energy_change": -0.05,
            "interest_updates": {"ai": {"name": "人工智能", "delta": 0.05}},
        }
        self.service.llm = _FakeLLM(payload=diary_payload)
        diary_result = await self.service.run_nightly_diary("shelly")
        self.assertFalse(diary_result["fallback"])
        self.assertEqual(self.share_gate.rechecks, 1)
        today = datetime.now().strftime("%Y-%m-%d")
        diary = self.db.get_diary("shelly", today)
        self.assertEqual(diary["content"], "今天看到了一些有趣的东西。")

    async def test_diary_llm_failure_does_not_write_diary(self):
        self.db.add_note("shelly", None, "hn", "https://x", "X", "s", url_hash="dx")
        self.service.llm = _FakeLLM(error=LLMError("boom"))
        result = await self.service.run_nightly_diary("shelly")
        self.assertIn("error", result)
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertIsNone(self.db.get_diary("shelly", today))
        self.assertEqual(self.db._rows("SELECT COUNT(*) AS n FROM staging_diary")[0]["n"], 0)

    async def test_llm_failure_marks_error_without_fallback(self):
        self.service.llm = _FakeLLM(error=LLMError("boom"))
        result = await self.service.run_browse_session("shelly", "scheduled")
        self.assertEqual(result.status, "error")
        self.assertIn("boom", result.error)
        self.assertEqual(self.db.list_notes("shelly"), [])
        sessions = self.db.list_sessions("shelly")
        self.assertEqual(sessions[0]["status"], "failed")
        self.assertIn("boom", sessions[0]["error"])

    async def test_budget_exhausted_skips_session(self):
        self.service.config.daily_llm_call_limit = 1
        today = datetime.now().strftime("%Y-%m-%d")
        self.db.increment_llm_usage("shelly", today, calls=1, tokens=0)
        result = await self.service.run_browse_session("shelly", "scheduled")
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "budget_exhausted")
        self.assertEqual(self.db.list_notes("shelly"), [])
        self.assertEqual(self.db.list_sessions("shelly")[0]["status"], "skipped")

    async def test_persona_unavailable_skips(self):
        self.service.personas = _FakePersonas(unavailable=True)
        result = await self.service.run_browse_session("shelly", "scheduled")
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "persona_unavailable")
        self.assertEqual(self.db.list_notes("shelly"), [])

    async def test_sleep_window_blocks_scheduled_only(self):
        cfg = load_config({"sleep_window": "00:00-07:00"})
        service = LifeService(cfg, self.db, self.interests, self.esm,
                              _FakeLLM(payload={}), self.personas,
                              share_gate=self.share_gate,
                              fetcher_fn=_fake_fetcher,
                              now_fn=lambda: datetime(2026, 8, 10, 3, 0))
        result = await service.run_browse_session("shelly", "scheduled")
        self.assertEqual(result.status, "skipped")
        self.assertEqual(result.reason, "sleep_window")
        manual = await service.run_browse_session("shelly", "manual", force=True)
        self.assertNotEqual(manual.status, "skipped")


if __name__ == "__main__":
    unittest.main()