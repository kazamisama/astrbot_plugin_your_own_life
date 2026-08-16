import asyncio
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.db import LifeDB
from life.presence import LifePresence


class LifePresenceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def test_wait_until_free_wakes_on_clear(self):
        presence = LifePresence()
        presence.mark_busy("shelly", "browse")
        waiter = asyncio.create_task(
            presence.wait_until_free("shelly", max_wait_seconds=5)
        )
        await asyncio.sleep(0.02)
        presence.clear_busy("shelly")
        self.assertTrue(await waiter)
        self.assertEqual(presence.take_last_busy("shelly")["kind"], "browse")

    async def test_wait_until_free_times_out(self):
        presence = LifePresence()
        presence.mark_busy("shelly", "diary")
        self.assertFalse(
            await presence.wait_until_free("shelly", max_wait_seconds=0.05)
        )

    def test_conversation_window_blocks_scheduler_persona(self):
        now = datetime(2026, 8, 12, 12, 0, 0)
        presence = LifePresence()
        presence.set_conversation_window(
            "shelly", now + timedelta(minutes=5)
        )
        self.assertTrue(presence.conversation_active("shelly", now))
        self.assertFalse(presence.conversation_active("alice", now))
        closed = presence.close_expired_conversations(
            ["shelly", "alice"], self.db, now + timedelta(minutes=6)
        )
        self.assertEqual(len(closed), 1)
        self.assertEqual(closed[0]["reason"], "timeout")
        events = self.db.list_events("shelly")
        self.assertEqual(events[0]["kind"], "conversation_end")
        self.assertEqual(events[0]["ts"], "2026-08-12 12:06:00")
        self.assertFalse(presence.conversation_active("shelly", now))


if __name__ == "__main__":
    unittest.main()
