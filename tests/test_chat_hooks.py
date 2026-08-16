import asyncio
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.chat_hooks import (
    build_presence_block,
    handle_llm_request,
    handle_llm_response,
    resolve_event_persona,
)
from life.config import LifeConfig
from life.db import LifeDB
from life.presence import LifePresence
from life.timeutil import local_now


class _FakeEvent:
    unified_msg_origin = "aiocqhttp:GroupMessage:123"
    message_str = "hello"

    def __init__(self):
        self._extra = {}

    def get_extra(self, key):
        return self._extra.get(key)

    def set_extra(self, key, value):
        self._extra[key] = value


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


class _FakeContext:
    def __init__(self):
        self.conversation_manager = _FakeConvManager()
        self.persona_manager = _FakePersonaManager()


class _FakeRequest:
    def __init__(self):
        self.extra_user_content_parts = []
        self.system_prompt = ""


class _FakeResponse:
    completion_text = "ok, I was reading the news"


class ChatHooksTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")
        self.presence = LifePresence()
        self.config = LifeConfig(
            life_personas=["shelly"],
            life_presence_enabled=True,
            conversation_wait_minutes=5,
            busy_reply_max_wait_minutes=1,
        )
        self.context = _FakeContext()

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def test_resolve_event_persona(self):
        self.assertEqual(
            await resolve_event_persona(self.context, _FakeEvent()), "shelly"
        )

    async def test_request_records_message_and_injects_after_busy(self):
        self.db.add_note(
            "shelly", None, "hn", "https://x", "Morning AI news",
            "summary", url_hash="ch1",
        )
        self.presence.mark_busy("shelly", "browse")
        request = _FakeRequest()

        async def clear_later():
            await asyncio.sleep(0.02)
            self.presence.clear_busy("shelly")

        clearer = asyncio.create_task(clear_later())
        ok = await handle_llm_request(
            self.context, self.presence, self.db, self.config,
            _FakeEvent(), request,
        )
        await clearer
        self.assertTrue(ok)
        events = self.db.list_events("shelly")
        self.assertEqual(events[0]["kind"], "message_in")
        payload = json.loads(events[0]["payload"])
        self.assertTrue(payload["deferred"])
        self.assertTrue(request.extra_user_content_parts)
        block = request.extra_user_content_parts[-1].text
        self.assertIn("<life-presence>", block)
        self.assertIn("Morning AI news", block)

    async def test_request_without_busy_records_message_only(self):
        request = _FakeRequest()
        ok = await handle_llm_request(
            self.context, self.presence, self.db, self.config,
            _FakeEvent(), request,
        )
        self.assertTrue(ok)
        self.assertFalse(request.extra_user_content_parts)
        events = self.db.list_events("shelly")
        self.assertEqual(events[0]["kind"], "message_in")
        self.assertFalse(json.loads(events[0]["payload"])["deferred"])

    async def test_response_records_reply_and_opens_window(self):
        ok = await handle_llm_response(
            self.context, self.presence, self.db, self.config,
            _FakeEvent(), _FakeResponse(),
        )
        self.assertTrue(ok)
        events = self.db.list_events("shelly")
        self.assertEqual(events[0]["kind"], "reply_out")
        self.assertTrue(self.presence.conversation_active("shelly"))

    async def test_request_records_message_only_once_per_event(self):
        request = _FakeRequest()
        event = _FakeEvent()
        await handle_llm_request(
            self.context, self.presence, self.db, self.config,
            event, request,
        )
        await handle_llm_request(
            self.context, self.presence, self.db, self.config,
            event, request,
        )
        events = [
            e for e in self.db.list_events("shelly")
            if e["kind"] == "message_in"
        ]
        self.assertEqual(len(events), 1)

    async def test_disabled_presence_does_nothing(self):
        config = LifeConfig(
            life_personas=["shelly"], life_presence_enabled=False
        )
        request = _FakeRequest()
        ok = await handle_llm_request(
            self.context, self.presence, self.db, config,
            _FakeEvent(), request,
        )
        self.assertFalse(ok)
        self.assertEqual(self.db.list_events("shelly"), [])

    async def test_request_event_uses_passed_local_now(self):
        tz_db = LifeDB(Path(self.tmp.name) / "tz_life.db", timezone="America/New_York")
        try:
            tz_config = LifeConfig(
                life_personas=["shelly"],
                life_presence_enabled=True,
                conversation_wait_minutes=5,
                busy_reply_max_wait_minutes=1,
                timezone="America/New_York",
            )
            request = _FakeRequest()
            ok = await handle_llm_request(
                self.context, self.presence, tz_db, tz_config, _FakeEvent(), request,
                now_fn=lambda: local_now("America/New_York", datetime(2026, 8, 12, 12, 0)),
            )
            self.assertTrue(ok)
            events = tz_db.list_events("shelly")
            self.assertTrue(events[0]["ts"].startswith("2026-08-12"))
        finally:
            tz_db.close()

    async def test_response_event_uses_passed_local_now(self):
        tz_db = LifeDB(Path(self.tmp.name) / "tz_reply_life.db", timezone="America/New_York")
        try:
            tz_config = LifeConfig(
                life_personas=["shelly"],
                life_presence_enabled=True,
                conversation_wait_minutes=5,
                busy_reply_max_wait_minutes=1,
                timezone="America/New_York",
            )
            ok = await handle_llm_response(
                self.context, self.presence, tz_db, tz_config,
                _FakeEvent(), _FakeResponse(),
                now_fn=lambda: local_now("America/New_York", datetime(2026, 8, 12, 12, 0)),
            )
            self.assertTrue(ok)
            events = tz_db.list_events("shelly")
            self.assertEqual(events[0]["kind"], "reply_out")
            self.assertTrue(events[0]["ts"].startswith("2026-08-12"))
        finally:
            tz_db.close()

    def test_build_presence_block_uses_tags(self):
        block = build_presence_block({"sessions": [], "notes": [], "events": []})
        self.assertIn("<life-presence>", block)
        self.assertIn("</life-presence>", block)


if __name__ == "__main__":
    unittest.main()
