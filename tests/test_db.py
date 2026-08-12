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

    def test_note_duplicate_url_hash_allowed_for_revisit(self):
        first = self.db.add_note("shelly", None, "hacker-news", "https://example.com/a", "A", "s", url_hash="hash-a")
        second = self.db.add_note("shelly", None, "revisit/hacker-news", "https://example.com/a", "A2", "s", url_hash="hash-a")
        other = self.db.add_note("alice", None, "hacker-news", "https://example.com/a", "A", "s", url_hash="hash-a")
        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNotNone(other)
        self.assertEqual(len(self.db.list_notes_by_url_hash("shelly", "hash-a")), 2)

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

    def test_list_watched_notes_filters_watchlist_source(self):
        self.db.add_note("shelly", None, "watchlist/github-repo", "https://w", "W", "s", url_hash="wl1")
        self.db.add_note("shelly", None, "hacker-news", "https://x", "X", "s", url_hash="wl2")
        rows = self.db.list_watched_notes("shelly")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "W")
        self.assertEqual(self.db.list_watched_notes("alice"), [])

    def test_revisit_candidates_and_chains(self):
        old_id = self.db.add_note("shelly", None, "hn", "https://old", "Old", "s", url_hash="rv-old")
        fresh_id = self.db.add_note("shelly", None, "hn", "https://new", "New", "s", url_hash="rv-new")
        self.db._execute("UPDATE notes SET fetched_at = ? WHERE id = ?", ("2026-07-13 10:00:00", old_id))
        self.db._execute("UPDATE notes SET fetched_at = ? WHERE id = ?", ("2026-08-13 10:00:00", fresh_id))
        candidates = self.db.list_revisit_candidates("shelly", "2026-08-12", limit=10)
        self.assertEqual([row["id"] for row in candidates], [old_id])
        revisit_id = self.db.add_note("shelly", None, "revisit/hn", "https://old", "Later", "s", url_hash="rv-old")
        self.assertTrue(self.db.mark_note_revisit(revisit_id, old_id))
        self.assertEqual(self.db.list_revisit_candidates("shelly", "2026-08-12", limit=10), [])
        follow_ups = self.db.list_notes_by_url_hash("shelly", "rv-old", exclude_id=old_id)
        self.assertEqual([row["id"] for row in follow_ups], [revisit_id])
        chains = self.db.list_revisit_chains("shelly")
        self.assertEqual([row["id"] for row in chains], [old_id, revisit_id])
        self.assertEqual(self.db.list_revisit_chains("alice"), [])

    def test_notes_unique_index_migration_allows_revisit_rows(self):
        db_path = Path(self.tmp.name) / "old_unique.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute("""
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                persona_id TEXT NOT NULL DEFAULT 'default',
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
                category TEXT DEFAULT 'other',
                tags TEXT DEFAULT '[]',
                share_decision TEXT DEFAULT '',
                share_status TEXT DEFAULT '',
                url_hash TEXT NOT NULL,
                deleted_at TEXT DEFAULT '',
                temperature REAL NOT NULL DEFAULT 1.0,
                last_touched_at TEXT DEFAULT '',
                UNIQUE(persona_id, url_hash)
            )
        """)
        conn.execute(
            "INSERT INTO notes (persona_id, fetched_at, source, url, title, summary, url_hash) "
            "VALUES ('default', '2026-07-13 10:00:00', 'hn', 'https://x', 'X', 's', 'h1')"
        )
        conn.commit()
        conn.close()
        migrated = LifeDB(db_path)
        try:
            second = migrated.add_note(
                "default", None, "revisit/hn", "https://x", "X2", "s", url_hash="h1"
            )
            self.assertIsNotNone(second)
            rows = migrated.list_notes_by_url_hash("default", "h1")
            self.assertEqual(len(rows), 2)
        finally:
            migrated.close()

    def test_note_temperature_decay_and_rehydrate(self):
        cold = self.db.add_note("shelly", None, "hn", "https://cold", "Cold", "s", url_hash="cold-t")
        hot = self.db.add_note("shelly", None, "hn", "https://hot", "Hot", "s", url_hash="hot-t")
        self.assertEqual(self.db.get_note(cold)["temperature"], 1.0)
        self.db.decay_note_temperature("shelly", 0.5)
        self.assertEqual(self.db.get_note(cold)["temperature"], 0.5)
        self.assertEqual(self.db.get_note(hot)["temperature"], 0.5)
        self.db.rehydrate_notes([cold])
        note = self.db.get_note(cold)
        self.assertEqual(note["temperature"], 1.0)
        self.assertTrue(note["last_touched_at"])
        self.db.decay_note_temperature("shelly", 0.0)
        self.assertEqual(self.db.get_note(hot)["temperature"], 0.05)

    def test_search_notes_temperature_weighted(self):
        cold = self.db.add_note("shelly", None, "hn", "https://cold", "Cold", "s", url_hash="cw")
        hot = self.db.add_note("shelly", None, "hn", "https://hot", "Hot", "s", url_hash="hw")
        self.db._execute("UPDATE notes SET temperature = ? WHERE id = ?", (0.2, cold))
        self.db._execute("UPDATE notes SET temperature = ? WHERE id = ?", (0.9, hot))
        rows = self.db.search_notes("shelly", temperature_weighted=True)
        self.assertEqual([row["id"] for row in rows], [hot, cold])

    def test_reviews_upsert_and_period_notes(self):
        self.db.add_note("shelly", None, "hn", "https://a", "A", "s", url_hash="rv-a")
        self.db._execute("UPDATE notes SET fetched_at = ? WHERE url_hash = ?", ("2026-07-15 10:00:00", "rv-a"))
        self.db.add_note("shelly", None, "hn", "https://b", "B", "s", url_hash="rv-b")
        self.db._execute("UPDATE notes SET fetched_at = ? WHERE url_hash = ?", ("2026-08-02 10:00:00", "rv-b"))
        self.assertEqual(self.db.count_notes_between("shelly", "2026-07-01", "2026-07-31"), 1)
        self.assertEqual(len(self.db.list_notes_between("shelly", "2026-07-01", "2026-07-31")), 1)
        cats = self.db.category_counts_between("shelly", "2026-07-01", "2026-08-31")
        self.assertEqual(sum(int(c["n"]) for c in cats), 2)
        rid = self.db.upsert_review(
            "shelly", "monthly", "2026-07-01", "2026-07-31", "第一版",
            source_refs=[{"diary_date": "2026-07-31"}],
        )
        self.assertGreater(rid, 0)
        self.db.upsert_review(
            "shelly", "monthly", "2026-07-01", "2026-07-31", "第二版",
            status="fallback", confidence=0.6,
        )
        rows = self.db.list_reviews("shelly")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["content"], "第二版")
        self.assertEqual(rows[0]["status"], "fallback")
        self.assertAlmostEqual(rows[0]["confidence"], 0.6)

    def test_time_capsules_lifecycle(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://cap", "C", "s", url_hash="cap1")
        cid = self.db.seal_capsule(
            "shelly", note_id, "2026-09-01 09:00:00",
            sealed_at="2026-08-01 09:00:00",
        )
        self.assertIsNotNone(cid)
        self.assertIsNone(self.db.seal_capsule(
            "shelly", note_id, "2026-10-01 09:00:00",
            sealed_at="2026-08-01 09:00:00",
        ))
        self.assertEqual(len(self.db.capsules_due("shelly", "2026-08-31 23:59:59")), 0)
        due = self.db.capsules_due("shelly", "2026-09-01 09:00:00")
        self.assertEqual(len(due), 1)
        self.assertTrue(self.db.unlock_capsule("shelly", cid, now_str="2026-09-01 09:00:00"))
        self.assertTrue(self.db.save_capsule_reply("shelly", cid, "当时的我…现在的我…"))
        row = self.db.get_capsule("shelly", cid)
        self.assertEqual(row["status"], "replied")
        self.assertEqual(row["reply"], "当时的我…现在的我…")
        self.assertEqual(len(self.db.capsules_due("shelly", "2026-12-01")), 0)

    def test_llm_edit_apply_and_rollback(self):
        note_id = self.db.add_note(
            "shelly", None, "hn", "https://x", "Old title", "Old summary", url_hash="edit1"
        )
        old = self.db.update_note_field("shelly", note_id, "summary", "New summary")
        self.assertEqual(old, "Old summary")
        self.assertEqual(self.db.get_note(note_id)["summary"], "New summary")
        self.assertIsNone(self.db.update_note_field("shelly", note_id, "diary", "x"))
        log_id = self.db.log_change(
            "shelly", "note", note_id,
            '{"field":"summary","value":"Old summary"}',
            '{"field":"summary","value":"New summary"}',
            actor="llm", status="pending_owner",
        )
        self.assertEqual(self.db.get_change_log_entry("shelly", log_id)["status"], "pending_owner")
        self.assertIsNotNone(self.db.apply_change("shelly", log_id))
        self.assertEqual(self.db.get_change_log_entry("shelly", log_id)["status"], "applied")
        self.assertIsNotNone(self.db.rollback_change("shelly", log_id))
        self.assertEqual(self.db.get_note(note_id)["summary"], "Old summary")
        self.assertEqual(self.db.get_change_log_entry("shelly", log_id)["status"], "rolled_back")
        self.assertFalse(self.db.reject_change("shelly", log_id))
        log2 = self.db.log_change(
            "shelly", "interest", "ai",
            '{"key":"ai","name":"AI","weight":0.5}',
            '{"key":"ai","name":"AI","weight":0.8}',
            actor="llm", status="pending_owner",
        )
        self.assertTrue(self.db.reject_change("shelly", log2))
        self.assertEqual(self.db.get_change_log_entry("shelly", log2)["status"], "rejected")
        self.assertIsNone(self.db.apply_change("shelly", log2))

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

    def test_staging_commit_null_session_returns_only_new_notes(self):
        self.db.add_note("shelly", None, "hn", "https://pre", "Pre", "s", url_hash="pre-null")
        self.db.stage_note("shelly", None, "hn", "https://new", "New", "s", url_hash="new-null")
        notes = self.db.commit_staged("shelly", None, status="completed")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["title"], "New")
        self.assertEqual(len(self.db.list_notes_by_url_hash("shelly", "pre-null")), 1)

    def test_memory_overview_excludes_deleted_notes(self):
        self.db.add_note("shelly", None, "hn", "https://keep", "Keep", "s", url_hash="mo-keep")
        gone_id = self.db.add_note("shelly", None, "hn", "https://gone", "Gone", "s", url_hash="mo-gone")
        self.db.soft_delete_note("shelly", gone_id)
        overview = self.db.memory_overview("shelly")
        self.assertEqual(overview["total_notes"], 1)
        self.assertEqual(overview["diary_count"], 0)
        self.assertEqual([r["category"] for r in overview["categories"]], ["other"])

    def test_apply_change_rejects_malformed_entity_id(self):
        self.db.log_change(
            "shelly", "note", "not-a-number",
            json.dumps({"field": "summary", "value": "old"}),
            json.dumps({"field": "summary", "value": "new"}),
            actor="llm", status="pending_owner",
        )
        row = self.db.get_change_log_entry("shelly", 1)
        self.assertEqual(row["status"], "pending_owner")
        self.assertIsNone(self.db.apply_change("shelly", 1))

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

    def test_daily_usage_energy_accumulates(self):
        self.db.increment_energy_usage("shelly", "2026-08-12", 0.15)
        self.db.increment_energy_usage("shelly", "2026-08-12", 0.2)
        row = self.db.get_daily_usage("shelly", "2026-08-12")
        self.assertAlmostEqual(row["energy_used"], 0.35)
        other = self.db.get_daily_usage("shelly", "2026-08-13")
        self.assertIsNone(other)

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
        self.assertEqual(self.db.count_events("shelly"), 3)
        self.assertEqual(self.db.count_events("shelly", kinds=["think"]), 1)
        self.assertEqual(self.db.count_events("shelly", kinds=["recall"]), 0)

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
    def test_life_plans_board(self):
        self.db.ensure_plan("shelly", "2026-08-12", "browse-10-00", "browse",
                            scheduled_at="2026-08-12 10:00:00")
        self.db.ensure_plan("shelly", "2026-08-12", "browse-15-00", "browse",
                            scheduled_at="2026-08-12 15:00:00")
        self.db.ensure_plan("shelly", "2026-08-12", "diary-23-00", "diary",
                            scheduled_at="2026-08-12 23:00:00")
        self.assertTrue(self.db.update_plan(
            "shelly", "2026-08-12", "browse-10-00", "done", budget_used=12.5,
        ))
        self.assertTrue(self.db.update_plan(
            "shelly", "2026-08-12", "browse-15-00", "skipped", reason="sleep_window",
        ))
        items = self.db.list_plans("shelly", "2026-08-12")
        self.assertEqual(len(items), 3)
        self.assertEqual([i["task_id"] for i in items],
                         ["browse-10-00", "browse-15-00", "diary-23-00"])
        done = self.db.list_plans("shelly", "2026-08-12", status="done")
        self.assertEqual(len(done), 1)
        self.assertEqual(done[0]["budget_used"], 12.5)
        summary = self.db.plan_summary("shelly", "2026-08-12")
        self.assertEqual(summary["total"], 3)
        self.assertEqual(summary["done"], 1)
        self.assertEqual(summary["skipped"], 1)
        self.assertEqual(summary["pending"], 1)
        self.assertEqual(summary["budget_used"], 12.5)

    def test_ensure_plan_is_idempotent(self):
        self.db.ensure_plan("shelly", "2026-08-12", "browse-10-00", "browse")
        again = self.db.ensure_plan("shelly", "2026-08-12", "browse-10-00", "browse")
        self.assertEqual(again, 1)
        self.assertEqual(len(self.db.list_plans("shelly", "2026-08-12")), 1)
    def test_optional_plan_mutations_and_events(self):
        self.db.ensure_plan("shelly", "2026-08-12", "browse-10-00", "browse",
                            scheduled_at="2026-08-12 10:00:00", fixed=True)
        plan_id = self.db.add_optional_plan(
            "shelly", "2026-08-12", "extra-1", "browse",
            "2026-08-12 12:00:00", reason="llm",
        )
        self.assertIsNotNone(plan_id)
        self.assertIsNone(self.db.add_optional_plan(
            "shelly", "2026-08-12", "extra-1", "browse",
            "2026-08-12 12:00:00",
        ))
        self.assertTrue(self.db.defer_plan(
            "shelly", "2026-08-12", "extra-1", "2026-08-12 14:00:00", reason="busy",
        ))
        self.assertTrue(self.db.skip_plan(
            "shelly", "2026-08-12", "extra-1", "not_now",
        ))
        items = self.db.list_plans("shelly", "2026-08-12")
        extra = next(item for item in items if item["task_id"] == "extra-1")
        self.assertEqual(extra["status"], "skipped")
        self.assertEqual(extra["reason"], "not_now")
        actions = [
            json.loads(e["payload"])["action"]
            for e in self.db.list_events("shelly")
            if e["kind"] == "change"
        ]
        self.assertIn("add", actions)
        self.assertIn("defer", actions)
        self.assertIn("skip", actions)

    def test_fixed_plan_cannot_be_mutated(self):
        self.db.ensure_plan("shelly", "2026-08-12", "browse-10-00", "browse",
                            scheduled_at="2026-08-12 10:00:00", fixed=True)
        self.assertFalse(self.db.defer_plan(
            "shelly", "2026-08-12", "browse-10-00", "2026-08-12 14:00:00",
        ))
        self.assertFalse(self.db.skip_plan(
            "shelly", "2026-08-12", "browse-10-00", "no",
        ))
        self.assertEqual(len(self.db.list_events("shelly")), 0)

    def test_reorder_plan_swaps_optional_tasks(self):
        self.db.ensure_plan("shelly", "2026-08-12", "browse-10-00", "browse",
                            scheduled_at="2026-08-12 10:00:00", fixed=True)
        self.db.add_optional_plan("shelly", "2026-08-12", "extra-1", "peek",
                                  "2026-08-12 12:00:00")
        self.db.add_optional_plan("shelly", "2026-08-12", "extra-2", "peek",
                                  "2026-08-12 14:00:00")
        self.assertTrue(self.db.reorder_plan("shelly", "2026-08-12", "extra-1", 3))
        items = self.db.list_plans("shelly", "2026-08-12")
        self.assertEqual(
            [item["task_id"] for item in items],
            ["browse-10-00", "extra-2", "extra-1"],
        )
        self.assertFalse(self.db.reorder_plan("shelly", "2026-08-12", "extra-1", 1))


if __name__ == "__main__":
    unittest.main()