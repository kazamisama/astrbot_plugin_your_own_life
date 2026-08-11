import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _astrbot_stub  # noqa: F401  (injects astrbot stubs)
from _astrbot_stub import AstrMessageEvent, Context

import main as plugin_main


class CommandsTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.context = Context()
        config = {
            "owner_ids": ["owner1"],
            "db_path": str(Path(self.tmp.name) / "life.db"),
            "enabled": True,
            "life_personas": ["shelly"],
            "sleep_window": "00:00-00:01",
            "share_sessions": {"shelly": ["sid-1"]},
        }
        self.star = plugin_main.LifeStar(self.context, config)

    def tearDown(self):
        self.star.db.close()
        self.tmp.cleanup()

    async def _run(self, command, message, sender="owner1"):
        event = AstrMessageEvent(message_str=message, sender_id=sender)
        await command(event)
        return event

    async def test_life_overview(self):
        event = await self._run(self.star.cmd_life, "/life")
        self.assertIn("生活档案 · shelly", event._result["text"])
        self.assertIn("分享", event._result["text"])

    async def test_owner_check(self):
        event = await self._run(self.star.cmd_life, "/life", sender="intruder")
        self.assertEqual(event._result["text"], "该命令仅限主人使用。")

    async def test_archive_date_validation(self):
        event = await self._run(self.star.cmd_life_archive, "/life_archive 2026/08/10")
        self.assertIn("日期格式应为", event._result["text"])
        event = await self._run(self.star.cmd_life_archive, "/life_archive 2026-08-10")
        self.assertIn("生活档案 · shelly · 2026-08-10", event._result["text"])

    async def test_interest_command(self):
        self.star.db.upsert_interest("shelly", "ai", "人工智能", 0.6)
        event = await self._run(self.star.cmd_life_interest, "/life_interest")
        self.assertIn("兴趣排行 · shelly", event._result["text"])

    async def test_personas_command(self):
        event = await self._run(self.star.cmd_life_personas, "/life_personas")
        self.assertIn("shelly", event._result["text"])

    async def test_manual_share_command(self):
        note_id = self.star.db.add_note(
            "shelly", None, "hacker-news", "https://example.com", "T", "S",
            share_decision={"should_share": False, "reason": "", "target": ""},
            url_hash="hash-manual",
        )
        event = await self._run(self.star.cmd_life_share, f"/life_share {note_id}")
        self.assertIn("已分享", event._result["text"])
        self.assertTrue(self.context.sent)

    async def test_send_message_honors_context_result(self):
        async def reject(session_id, chain):
            self.context.sent.append((session_id, chain))
            return False

        self.context.send_message = reject
        self.assertFalse(await self.star._send_message("sid-1", "hi"))

    async def test_reset_requires_confirm(self):
        event = await self._run(self.star.cmd_life_reset, "/life_reset")
        self.assertIn("确认请执行", event._result["text"])
        self.star.db.add_note("shelly", None, "hacker-news", "https://example.com", "T", "S",
                              url_hash="hash-x")
        event = await self._run(self.star.cmd_life_reset, "/life_reset confirm")
        self.assertIn("已清空", event._result["text"])
        self.assertEqual(self.star.db.list_notes("shelly"), [])


if __name__ == "__main__":
    unittest.main()