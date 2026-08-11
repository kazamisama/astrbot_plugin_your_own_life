import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.db import LifeDB

LEGACY_NOTES = """
CREATE TABLE notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER,
    fetched_at TEXT NOT NULL,
    source TEXT NOT NULL,
    url TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL,
    opinion TEXT DEFAULT '',
    mood TEXT DEFAULT '',
    interest_level REAL DEFAULT 0.5,
    interest_key TEXT DEFAULT '',
    interest_name TEXT DEFAULT '',
    url_hash TEXT NOT NULL UNIQUE
);
CREATE TABLE interests (
    key TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5,
    seen_count INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT DEFAULT ''
);
"""


class LifeDBTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def test_session_lifecycle(self):
        sid = self.db.start_browse_session("shelly", "scheduled", energy_before=0.8, mood_before="curious")
        self.assertGreater(sid, 0)
        self.db.finish_browse_session(sid, "completed", notes_count=2)
        sessions = self.db.list_sessions("shelly")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["persona_id"], "shelly")
        self.assertEqual(sessions[0]["status"], "completed")

    def test_persona_isolation(self):
        self.db.add_note("shelly", None, "hacker-news", "https://a", "A", "s",
                         url_hash="h1")
        self.db.add_note("alice", None, "github", "https://b", "B", "s",
                         url_hash="h2")
        self.assertEqual(len(self.db.list_notes("shelly")), 1)
        self.assertEqual(len(self.db.list_notes("alice")), 1)

    def test_note_dedupe_per_persona(self):
        self.db.add_note("shelly", None, "hacker-news", "https://example.com/a", "A", "s", url_hash="hash-a")
        second = self.db.add_note("shelly", None, "hacker-news", "https://example.com/a", "A", "s", url_hash="hash-a")
        other = self.db.add_note("alice", None, "hacker-news", "https://example.com/a", "A", "s", url_hash="hash-a")
        self.assertIsNone(second)
        self.assertIsNotNone(other)

    def test_note_category_and_share_decision(self):
        note_id = self.db.add_note(
            "shelly", None, "hacker-news", "https://example.com", "T", "S",
            category="opinion", tags=["ai"], share_decision={"should_share": True, "target": "sid-1"},
            url_hash="hx",
        )
        note = self.db.get_note(note_id)
        self.assertEqual(note["category"], "opinion")
        self.assertIn("ai", note["tags"])
        self.assertIn("should_share", note["share_decision"])

    def test_diary_upsert_per_persona(self):
        self.db.add_diary("shelly", "2026-08-10", "first", mood="curious", energy=0.6)
        self.db.add_diary("shelly", "2026-08-10", "second", mood="calm", energy=0.5)
        self.db.add_diary("alice", "2026-08-10", "other", mood="calm")
        self.assertEqual(self.db.get_diary("shelly", "2026-08-10")["content"], "second")
        self.assertEqual(self.db.get_diary("alice", "2026-08-10")["content"], "other")

    def test_interests_and_snapshots(self):
        self.db.upsert_interest("shelly", "ai", "人工智能", 0.6)
        self.db.upsert_interest("shelly", "ai", "人工智能", 0.7)
        self.assertEqual(self.db.get_interests("shelly")[0]["seen_count"], 2)
        self.db.add_state_snapshot("shelly", "browse", energy=0.5, mood="curious", curiosity=0.7)
        snapshots = self.db.list_state_snapshots("shelly")
        self.assertEqual(len(snapshots), 1)
        self.assertEqual(snapshots[0]["activity"], "browse")

    def test_share_log_and_pending(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://x", "X", "s",
                                   share_decision={"should_share": True, "target": "sid-1"},
                                   url_hash="hsh")
        self.db.add_note("shelly", None, "hn", "https://no", "No", "s",
                         url_hash="hno")
        pending = self.db.pending_share_notes("shelly")
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["id"], note_id)
        self.db.log_share_attempt("shelly", note_id, "sent", target_sid="sid-1", message="hi")
        self.assertEqual(self.db.count_share_success("shelly"), 1)
        self.db.update_note_share_status(note_id, "shared")
        self.assertEqual(self.db.pending_share_notes("shelly"), [])

    def test_persona_prompt_cache(self):
        self.db.upsert_persona_prompt("shelly", "prompt", "persona", "ok")
        row = self.db.get_persona_prompt("shelly")
        self.assertEqual(row["system_prompt"], "prompt")

    def test_seen_cache_and_reset(self):
        self.assertFalse(self.db.is_seen("shelly", "abc"))
        self.db.mark_seen("shelly", "abc")
        self.assertTrue(self.db.is_seen("shelly", "abc"))
        self.db.reset_all("shelly")
        self.assertEqual(self.db.list_notes("shelly"), [])
        self.assertEqual(self.db.get_interests("shelly"), [])

    def test_legacy_migration(self):
        path = Path(self.tmp.name) / "legacy.db"
        conn = sqlite3.connect(str(path))
        conn.executescript(LEGACY_NOTES)
        conn.execute(
            "INSERT INTO notes (fetched_at, source, url, title, summary, url_hash) "
            "VALUES ('2026-08-10 10:00:00', 'hn', 'https://old', 'Old', 's', 'h1')"
        )
        conn.execute("INSERT INTO interests (key, name, weight) VALUES ('ai', 'AI', 0.8)")
        conn.commit()
        conn.close()
        db = LifeDB(path)
        notes = db.list_notes("default")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["title"], "Old")
        self.assertEqual(db.get_interests("default")[0]["key"], "ai")
        db.close()

    def test_timezone_normalization(self):
        db = LifeDB(Path(self.tmp.name) / "tz.db", timezone="Mars/Olympus")
        self.assertEqual(db.timezone, "Asia/Shanghai")
        db.close()
        db = LifeDB(Path(self.tmp.name) / "tz2.db", timezone="UTC")
        self.assertEqual(db.timezone, "UTC")
        self.assertRegex(db._today(), r"^\d{4}-\d{2}-\d{2}$")
        db.close()


if __name__ == "__main__":
    unittest.main()