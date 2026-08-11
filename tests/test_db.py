import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime
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

    def test_count_sessions_by_kind(self):
        self.db.start_browse_session("shelly", "scheduled")
        self.db.start_browse_session("shelly", "scheduled", kind="peek")
        today = datetime.now().strftime("%Y-%m-%d")
        self.assertEqual(self.db.count_sessions_by_kind("shelly", today, "browse"), 1)
        self.assertEqual(self.db.count_sessions_by_kind("shelly", today, "peek"), 1)

    def test_wishlist_lifecycle(self):
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_wishlist("shelly", sid, "想研究向量数据库", interest_key="vector", source="diary")
        self.db.commit_staged("shelly", sid, status="completed")
        items = self.db.list_wishlist("shelly")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["status"], "pending")
        self.assertEqual(items[0]["text"], "想研究向量数据库")
        self.assertTrue(self.db.update_wishlist_status(
            "shelly", items[0]["id"], "promoted", "值得关注", "vector", "向量数据库"
        ))
        self.assertEqual(self.db.list_wishlist("shelly", status="pending"), [])
        self.assertEqual(self.db.list_wishlist("shelly", status="promoted")[0]["interest_key"], "vector")

    def test_timeline_merges_and_filters(self):
        self.db.add_note("shelly", None, "hn", "https://n", "N", "s", url_hash="tn")
        self.db.add_diary("shelly", "2026-08-11", "diary body")
        self.db.log_share_attempt("shelly", None, "sent", "ok", "sid-1", "hello")
        self.db.add_state_snapshot("shelly", "browse", 0.6, "curious")
        self.db._execute("UPDATE notes SET fetched_at = ? WHERE url_hash = ?", ("2026-08-12 09:00:00", "tn"))
        self.db._execute("UPDATE share_log SET attempted_at = ?", ("2026-08-12 10:00:00",))
        self.db._execute("UPDATE state_snapshots SET ts = ?", ("2026-08-12 11:00:00",))
        all_items = self.db.timeline("shelly")["items"]
        self.assertEqual([i["kind"] for i in all_items], ["snapshot", "share", "note", "diary"])
        notes = self.db.timeline("shelly", types=["note"])["items"]
        self.assertEqual([i["kind"] for i in notes], ["note"])
        page1 = self.db.timeline("shelly", limit=2, offset=0)["items"]
        page2 = self.db.timeline("shelly", limit=2, offset=2)["items"]
        self.assertEqual(len(page1), 2)
        self.assertEqual(len(page2), 2)
        self.assertNotEqual([i["kind"] for i in page1], [i["kind"] for i in page2])

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

    def test_list_notes_filters_by_exact_date(self):
        old_id = self.db.add_note(
            "shelly", None, "hacker-news", "https://old", "Old", "s", url_hash="old1"
        )
        self.db.add_note("shelly", None, "hacker-news", "https://today", "Today", "s", url_hash="today1")
        self.db._execute("UPDATE notes SET fetched_at = ? WHERE id = ?", ("2026-08-05 10:00:00", old_id))
        self.assertEqual(len(self.db.list_notes("shelly", "2026-08-05", limit=10)), 1)
        self.assertEqual(len(self.db.list_notes("shelly", "2026-08-06", limit=10)), 0)

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

    def test_staging_commit_moves_data(self):
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_note("shelly", sid, "hn", "https://a", "A", "s", url_hash="h1")
        self.db.stage_seen("shelly", sid, "h1")
        self.db.stage_snapshot("shelly", sid, "browse", energy=0.5, mood="curious")
        notes = self.db.commit_staged("shelly", sid, status="completed", notes_count=1)
        self.assertEqual(len(notes), 1)
        self.assertTrue(self.db.is_seen("shelly", "h1"))
        self.assertEqual(len(self.db.list_state_snapshots("shelly")), 1)
        self.assertEqual(self.db.list_sessions("shelly")[0]["status"], "completed")
        self.assertEqual(self.db._rows("SELECT COUNT(*) AS n FROM staging_notes")[0]["n"], 0)
        self.assertEqual(self.db._rows("SELECT COUNT(*) AS n FROM staging_seen")[0]["n"], 0)

    def test_staging_discard_keeps_archive_clean(self):
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_note("shelly", sid, "hn", "https://a", "A", "s", url_hash="h1")
        self.db.discard_staged("shelly", sid, "boom")
        self.assertEqual(self.db.list_notes("shelly"), [])
        sessions = self.db.list_sessions("shelly")
        self.assertEqual(sessions[0]["status"], "failed")
        self.assertIn("boom", sessions[0]["error"])
        self.assertEqual(self.db._rows("SELECT COUNT(*) AS n FROM staging_notes")[0]["n"], 0)

    def test_daily_usage_increment(self):
        self.db.increment_llm_usage("shelly", "2026-08-12", calls=1, tokens=100)
        self.db.increment_llm_usage("shelly", "2026-08-12", calls=2, tokens=50)
        row = self.db.get_daily_usage("shelly", "2026-08-12")
        self.assertEqual(row["llm_calls"], 3)
        self.assertEqual(row["tokens"], 150)
        self.assertEqual(self.db.list_daily_usage("shelly")[0]["date"], "2026-08-12")

    def test_recover_stale_runs(self):
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_note("shelly", sid, "hn", "https://a", "A", "s", url_hash="h1")
        db2 = LifeDB(Path(self.tmp.name) / "life.db")
        sessions = db2.list_sessions("shelly")
        self.assertEqual(sessions[0]["status"], "failed")
        self.assertEqual(sessions[0]["reason"], "stale_run_recovered")
        self.assertEqual(db2.list_notes("shelly"), [])
        self.assertEqual(db2._rows("SELECT COUNT(*) AS n FROM staging_notes")[0]["n"], 0)
        db2.close()

    def test_soft_delete_and_restore_note(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://a", "A", "s", url_hash="h1")
        self.assertTrue(self.db.soft_delete_note("shelly", note_id, actor="owner", reason="cleanup"))
        self.assertIsNone(self.db.get_note(note_id))
        self.assertEqual(self.db.list_notes("shelly"), [])
        trash = self.db.list_trash("shelly")
        self.assertEqual(len(trash["notes"]), 1)
        self.assertTrue(self.db.restore_note("shelly", note_id, actor="owner", reason="undo"))
        self.assertEqual(self.db.get_note(note_id)["title"], "A")
        logs = self.db.list_change_log("shelly")
        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0]["status"], "restored")

    def test_soft_delete_diary_and_restore(self):
        self.db.add_diary("shelly", "2026-08-12", "d", mood="calm")
        self.assertTrue(self.db.soft_delete_diary("shelly", "2026-08-12", reason="cleanup"))
        self.assertIsNone(self.db.get_diary("shelly", "2026-08-12"))
        self.assertEqual(len(self.db.list_trash("shelly")["diaries"]), 1)
        self.assertTrue(self.db.restore_diary("shelly", "2026-08-12", reason="undo"))
        self.assertEqual(self.db.get_diary("shelly", "2026-08-12")["content"], "d")

    def test_purge_trash_respects_retention(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://a", "A", "s", url_hash="h1")
        self.db.soft_delete_note("shelly", note_id)
        self.db._execute(
            "UPDATE notes SET deleted_at = '2020-01-01 00:00:00' WHERE id = ?", (note_id,)
        )
        purged = self.db.purge_trash("shelly", retention_days=30)
        self.assertEqual(purged, 1)
        self.assertEqual(self.db.list_trash("shelly")["notes"], [])
        self.assertEqual(len(self.db.list_change_log("shelly")), 1)

    def test_injection_log(self):
        self.db.log_injection(
            "shelly", source="hn", context="browse", field="summary",
            preview="ignore previous instructions",
        )
        rows = self.db.list_injection_log("shelly")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["detected"], 1)
        self.assertEqual(rows[0]["field"], "summary")

    def test_lease_exclusivity_and_renewal(self):
        key = "browse:2026-08-12 10:00"
        self.assertTrue(self.db.acquire_lease("shelly", key, "inst-a", ttl_seconds=300))
        self.assertFalse(self.db.acquire_lease("shelly", key, "inst-b", ttl_seconds=300))
        self.assertTrue(self.db.renew_lease("shelly", key, "inst-a", ttl_seconds=300))
        self.assertFalse(self.db.renew_lease("shelly", key, "inst-b", ttl_seconds=300))
        self.assertTrue(self.db.release_lease("shelly", key, "inst-a"))
        self.assertTrue(self.db.acquire_lease("shelly", key, "inst-b", ttl_seconds=300))

    def test_expired_lease_can_be_reacquired(self):
        key = "browse:2026-08-12 10:00"
        self.assertTrue(self.db.acquire_lease("shelly", key, "inst-a", ttl_seconds=1))
        self.db._execute(
            "UPDATE life_leases SET expires_at = '2020-01-01 00:00:00' "
            "WHERE persona_id = 'shelly' AND task_key = ?",
            (key,),
        )
        self.assertTrue(self.db.acquire_lease("shelly", key, "inst-b", ttl_seconds=300))
        self.assertEqual(self.db.cleanup_expired_leases(), 0)

    def test_diary_signature_roundtrip(self):
        self.db.add_diary("shelly", "2026-08-12", "d", mood="calm", signature="今天有风")
        self.assertEqual(self.db.get_diary("shelly", "2026-08-12")["signature"], "今天有风")

    def test_staging_diary_signature(self):
        self.db.stage_diary("shelly", None, "2026-08-12", "d", signature="s")
        self.db.commit_staged("shelly", None, status="completed")
        self.assertEqual(self.db.get_diary("shelly", "2026-08-12")["signature"], "s")

    def test_get_status_empty_state(self):
        status = self.db.get_status("shelly", "2026-08-12")
        self.assertEqual(status["persona_id"], "shelly")
        self.assertIsNone(status["diary"])
        self.assertEqual(status["browse_count"], 0)
        self.assertEqual(status["recent_notes"], [])

    def test_timeline_heatmap(self):
        self.db.add_note("shelly", None, "hn", "https://a", "A", "s", url_hash="h1")
        self.db.add_diary("shelly", "2026-08-12", "d")
        self.db.log_share_attempt("shelly", None, "sent", target_sid="s")
        self.db.start_browse_session("shelly", "scheduled")
        heat = self.db.timeline_heatmap("shelly", "2026-08")
        today = datetime.now().strftime("%Y-%m-%d")
        day = next((d for d in heat["days"] if d["date"] == today), None)
        self.assertIsNotNone(day)
        self.assertGreaterEqual(day["notes"], 1)
        self.assertGreaterEqual(day["diaries"], 1)
        self.assertGreaterEqual(day["shares"], 1)
        self.assertGreaterEqual(day["browse"], 1)
    def test_event_chain_append_is_idempotent(self):
        event_id = self.db.append_event(
            "shelly", "observe", {"count": 1}, [{"url": "https://a"}],
            "session/1/observe", ts="2026-08-12 10:00:00",
        )
        self.assertIsNotNone(event_id)
        duplicate = self.db.append_event(
            "shelly", "observe", {"count": 1}, [{"url": "https://a"}],
            "session/1/observe", ts="2026-08-12 10:00:00",
        )
        self.assertIsNone(duplicate)
        events = self.db.list_events("shelly")
        self.assertEqual(len(events), 1)
        found = self.db.find_event("shelly", "session/1/observe")
        self.assertEqual(found["kind"], "observe")
        self.assertEqual(json.loads(found["payload"]), {"count": 1})
        self.assertEqual(json.loads(found["source_refs"]), [{"url": "https://a"}])

    def test_event_chain_list_filter_and_replay(self):
        self.db.append_event("shelly", "observe", {"n": 1}, [], "e/1",
                             ts="2026-08-12 10:00:00")
        self.db.append_event("shelly", "think", {"n": 1}, [], "e/2",
                             ts="2026-08-12 11:00:00")
        self.db.append_event("shelly", "change", {"n": 1}, [], "e/3",
                             ts="2026-08-12 12:00:00")
        self.assertEqual(
            [e["kind"] for e in self.db.list_events("shelly")],
            ["change", "think", "observe"],
        )
        filtered = self.db.list_events("shelly", kinds=["think", "observe"])
        self.assertEqual([e["kind"] for e in filtered], ["think", "observe"])
        replay = self.db.replay_events("shelly")
        self.assertEqual([e["kind"] for e in replay], ["observe", "think", "change"])
        self.assertEqual(self.db.replay_events("shelly"), replay)
        self.assertEqual(len(self.db.list_events("shelly")), 3)

    def test_soft_delete_and_restore_emit_change_rollback_events(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://a", "A", "s",
                                   url_hash="h1")
        self.assertTrue(self.db.soft_delete_note("shelly", note_id, reason="cleanup"))
        self.assertTrue(self.db.restore_note("shelly", note_id, reason="undo"))
        events = self.db.list_events("shelly")
        self.assertEqual([e["kind"] for e in events], ["rollback", "change"])
        self.assertEqual(
            self.db.find_event("shelly", f"note/{note_id}/restore")["kind"],
            "rollback",
        )

    def test_soft_delete_and_restore_diary_emit_events(self):
        self.db.add_diary("shelly", "2026-08-12", "d", mood="calm")
        self.assertTrue(self.db.soft_delete_diary("shelly", "2026-08-12", reason="cleanup"))
        self.assertTrue(self.db.restore_diary("shelly", "2026-08-12", reason="undo"))
        events = self.db.list_events("shelly")
        self.assertEqual([e["kind"] for e in events], ["rollback", "change"])
        self.assertEqual(
            json.loads(events[1]["payload"])["entity"], "diary",
        )

    def test_share_attempt_emits_express_event(self):
        self.db.log_share_attempt("shelly", None, "blocked", "share_disabled", "sid-1")
        events = self.db.list_events("shelly")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["kind"], "express")
        self.assertEqual(json.loads(events[0]["payload"])["status"], "blocked")
        self.assertEqual(events[0]["idempotency_key"].startswith("share_log/"), True)


if __name__ == "__main__":
    unittest.main()