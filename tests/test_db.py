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

    def test_old_staging_diary_schema_gets_signature_column(self):
        path = self.db.path
        self.db.close()
        conn = sqlite3.connect(str(path))
        conn.execute("ALTER TABLE staging_diary DROP COLUMN signature")
        conn.commit()
        conn.close()
        self.db = LifeDB(path)
        self.db.stage_diary(
            "shelly", None, "2026-08-12", "旧库日记", "calm", 0.5, "ai", "sig",
        )
        rows = self.db._rows("SELECT signature FROM staging_diary")
        self.assertEqual(rows[0]["signature"], "sig")

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

    def test_capsule_manual_open_keeps_unlock_at(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://cap2", "C2", "s",
                                   url_hash="cap2")
        cid = self.db.seal_capsule(
            "shelly", note_id, "2099-01-01 00:00:00",
            sealed_at="2026-08-01 09:00:00",
        )
        self.assertEqual(self.db.capsules_sealed_on("shelly", "2026-08-01"), 1)
        self.assertEqual(self.db.capsules_due("shelly", "2026-08-02"), [])
        self.assertTrue(self.db.unlock_capsule("shelly", cid))
        self.assertEqual(
            self.db.get_capsule("shelly", cid)["unlock_at"], "2099-01-01 00:00:00"
        )
        self.assertEqual(len(self.db.capsules_due("shelly", "2026-08-02")), 1)

    def test_purge_trash_cascades_time_capsules(self):
        note_id = self.db.add_note("shelly", None, "hn", "https://cap3", "C3", "s",
                                   url_hash="cap3")
        self.db.seal_capsule(
            "shelly", note_id, "2099-01-01 00:00:00",
            sealed_at="2026-08-01 09:00:00",
        )
        self.assertTrue(self.db.soft_delete_note("shelly", note_id))
        self.assertEqual(self.db.purge_trash("shelly", 0), 1)
        self.assertEqual(self.db.list_capsules("shelly"), [])
        logs = self.db.list_change_log("shelly")
        self.assertTrue(logs)
        self.assertTrue(all(row["old_value"] == "" for row in logs))

    def test_purge_trash_scrubs_event_references(self):
        note_id = self.db.add_note(
            "shelly", None, "hn", "https://scrub", "Scrub", "s",
            url_hash="scrub",
        )
        self.assertTrue(self.db.soft_delete_note("shelly", note_id))
        date = "2026-08-01"
        self.db.add_diary("shelly", date, "hidden diary")
        self.assertTrue(self.db.soft_delete_diary("shelly", date))
        self.db._execute(
            "UPDATE notes SET deleted_at = '2020-01-01 00:00:00' WHERE id = ?",
            (note_id,),
        )
        self.db._execute(
            "UPDATE diary_entries SET deleted_at = '2020-01-01 00:00:00' "
            "WHERE persona_id = ? AND date = ?",
            ("shelly", date),
        )
        other_id = self.db.add_note(
            "shelly", None, "hn", "https://keep", "Keep", "s",
            url_hash="keep-ref",
        )
        self.db.upsert_review(
            "shelly", "monthly", "2026-08-01", "2026-08-31",
            "review text",
            source_refs=[
                {"note_id": note_id, "url": "https://scrub"},
                {"note_id": other_id, "url": "https://keep"},
                {"diary_date": date},
            ],
        )
        self.db.log_share_attempt(
            "shelly", note_id, "sent", message="shared secret"
        )
        self.assertEqual(self.db.purge_trash("shelly", 0), 2)
        review = self.db.list_reviews("shelly")[0]
        self.assertEqual(review["content"], "review text")
        self.assertEqual(
            json.loads(review["source_refs"]),
            [{"note_id": other_id, "url": "https://keep"}],
        )
        shares = self.db.list_share_log("shelly")
        self.assertEqual(len(shares), 1)
        self.assertIsNone(shares[0]["note_id"])
        self.assertEqual(shares[0]["message"], "")
        events = self.db.list_events("shelly")
        note_event = next(
            row for row in events
            if row["idempotency_key"].startswith(f"note/{note_id}/soft-delete/")
        )
        diary_event = next(
            row for row in events
            if row["idempotency_key"].startswith(f"diary/{date}/soft-delete/")
        )
        for row in (note_event, diary_event):
            self.assertEqual(row["payload"], "{}")
            self.assertEqual(row["source_refs"], "[]")

    def test_delete_restore_delete_keeps_distinct_events(self):
        note_id = self.db.add_note(
            "shelly", None, "hn", "https://cycle", "Cycle", "s",
            url_hash="cycle",
        )
        self.assertTrue(self.db.soft_delete_note("shelly", note_id))
        self.assertTrue(self.db.restore_note("shelly", note_id))
        self.assertTrue(self.db.soft_delete_note("shelly", note_id))
        rows = self.db.list_events("shelly")
        keys = [row["idempotency_key"] for row in rows]
        self.assertEqual(len(keys), 3)
        self.assertEqual(len(set(keys)), 3)

    def test_change_apply_and_rollback_emit_events(self):
        note_id = self.db.add_note(
            "shelly", None, "hn", "https://audit", "Audit", "Old",
            url_hash="audit",
        )
        log_id = self.db.log_change(
            "shelly", "note", note_id,
            json.dumps({"field": "summary", "value": "Old"}),
            json.dumps({"field": "summary", "value": "New"}),
            actor="llm", status="pending_owner",
        )
        self.assertIsNotNone(self.db.apply_change("shelly", log_id))
        self.assertIsNotNone(self.db.rollback_change("shelly", log_id, actor="owner"))
        kinds = [row["kind"] for row in self.db.list_events("shelly")]
        self.assertEqual(sorted(kinds), ["change", "rollback"])
        keys = [row["idempotency_key"] for row in self.db.list_events("shelly")]
        self.assertEqual(len(set(keys)), 2)

    def test_interest_weight_zero_is_restored_and_keeps_seen_count(self):
        self.db.upsert_interest("shelly", "ai", "AI", 0.8, seen_count=5)
        log_id = self.db.log_change(
            "shelly", "interest", "ai",
            json.dumps({"name": "AI", "key": "ai", "weight": 0.8}),
            json.dumps({"name": "AI", "key": "ai", "weight": 0.0}),
            actor="llm", status="pending_owner",
        )
        self.assertIsNotNone(self.db.apply_change("shelly", log_id))
        row = self.db.get_interests("shelly")[0]
        self.assertEqual(row["weight"], 0.0)
        self.assertEqual(row["seen_count"], 5)
        self.assertIsNotNone(self.db.rollback_change("shelly", log_id, actor="owner"))
        row = self.db.get_interests("shelly")[0]
        self.assertAlmostEqual(row["weight"], 0.8)
        self.assertEqual(row["seen_count"], 5)

    def test_overview_and_status_counts_are_not_truncated(self):
        date = datetime.now().strftime("%Y-%m-%d")
        for index in range(25):
            self.db.add_note(
                "shelly", None, "hn", f"https://n{index}", f"N{index}", "s",
                url_hash=f"n{index}",
            )
        for _ in range(22):
            sid = self.db.start_browse_session("shelly", "scheduled")
            self.db.finish_browse_session(sid, "completed", notes_count=0)
        overview = self.db.get_overview("shelly", date)
        self.assertEqual(overview["stats"]["notes"], 25)
        self.assertEqual(overview["stats"]["sessions"], 22)
        self.assertEqual(overview["stats"]["completed"], 22)
        status = self.db.get_status("shelly", date)
        self.assertEqual(status["notes_count"], 25)
        self.assertEqual(status["browse_count"], 22)

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
        self.db.stage_seen("shelly", 0, "abc")
        self.db.commit_staged("shelly", 0, status="completed")
        self.assertTrue(self.db.is_seen("shelly", "abc"))
        self.db.reset_all("shelly")
        self.assertEqual(self.db.list_notes("shelly"), [])
        self.assertEqual(self.db.get_interests("shelly"), [])

    def test_reset_all_clears_plans_events_and_persona_prompts(self):
        self.db.ensure_plan("shelly", "2026-08-12", "browse-10-00", "browse",
                            scheduled_at="2026-08-12 10:00:00", fixed=True)
        self.db.add_optional_plan("shelly", "2026-08-12", "extra-1", "peek",
                                  "2026-08-12 11:00:00")
        self.db.append_event("shelly", "observe", {"x": 1}, [])
        self.db.upsert_persona_prompt("shelly", "sys", "persona", "ok")
        self.db.reset_all("shelly")
        self.assertEqual(self.db.list_plans("shelly", "2026-08-12"), [])
        self.assertEqual(self.db.list_events("shelly"), [])
        self.assertIsNone(self.db.get_persona_prompt("shelly"))

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
        indexes = {row["name"] for row in db._rows("PRAGMA index_list('notes')")}
        self.assertIn("idx_notes_persona_url", indexes)
        self.assertIn("idx_notes_persona_fetched", indexes)
        db.close()

    def test_unique_notes_migration_rebuilds_indexes(self):
        path = Path(self.tmp.name) / "unique.db"
        conn = sqlite3.connect(str(path))
        conn.executescript(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                persona_id TEXT NOT NULL DEFAULT '',
                session_id INTEGER,
                fetched_at TEXT NOT NULL,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                url_hash TEXT NOT NULL,
                UNIQUE(persona_id, url_hash)
            );
            CREATE INDEX idx_notes_persona_url ON notes(persona_id, url_hash);
            CREATE INDEX idx_notes_persona_fetched ON notes(persona_id, fetched_at);
            """
        )
        conn.execute(
            "INSERT INTO notes (persona_id, fetched_at, source, url, title, summary, url_hash) "
            "VALUES ('shelly', '2026-08-10 10:00:00', 'hn', 'https://old', 'Old', 's', 'h1')"
        )
        conn.commit()
        conn.close()
        db = LifeDB(path)
        indexes = {row["name"] for row in db._rows("PRAGMA index_list('notes')")}
        self.assertIn("idx_notes_persona_url", indexes)
        self.assertIn("idx_notes_persona_fetched", indexes)
        self.assertEqual(len(db.list_notes("shelly")), 1)
        db.close()

    def test_notes_migration_preserves_id_high_water_mark(self):
        path = Path(self.tmp.name) / "seq.db"
        conn = sqlite3.connect(str(path))
        conn.executescript(
            """
            CREATE TABLE notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                persona_id TEXT NOT NULL DEFAULT '',
                fetched_at TEXT NOT NULL,
                source TEXT NOT NULL,
                url TEXT NOT NULL,
                title TEXT NOT NULL,
                summary TEXT NOT NULL,
                url_hash TEXT NOT NULL,
                UNIQUE(persona_id, url_hash)
            );
            """
        )
        conn.execute(
            "INSERT INTO notes (id, persona_id, fetched_at, source, url, title, summary, url_hash) "
            "VALUES (5, 'shelly', '2026-08-10 10:00:00', 'hn', 'https://old', 'Old', 's', 'h1')"
        )
        conn.execute("DELETE FROM notes WHERE id = 5")
        conn.execute(
            "UPDATE sqlite_sequence SET seq = 5 WHERE name = 'notes'"
        )
        conn.commit()
        conn.close()
        db = LifeDB(path)
        new_id = db.add_note(
            "shelly", None, "hn", "https://new", "New", "s", url_hash="h2"
        )
        self.assertEqual(new_id, 6)
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

    def test_commit_staged_marks_revisits_atomically(self):
        original_id = self.db.add_note(
            "shelly", None, "hn", "https://old", "Old", "s", url_hash="rv-a"
        )
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_note(
            "shelly", sid, "revisit/hn", "https://old", "Later", "s",
            url_hash="rv-a",
        )
        notes = self.db.commit_staged(
            "shelly", sid, status="completed", revisit_of=[original_id]
        )
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["revisit_of"], original_id)
        self.assertEqual(self.db.get_note(original_id)["revisit_of"], 0)

    def test_commit_staged_revisit_length_mismatch_rolls_back(self):
        original_id = self.db.add_note(
            "shelly", None, "hn", "https://old2", "Old2", "s", url_hash="rv-b"
        )
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_note(
            "shelly", sid, "revisit/hn", "https://old2", "Later2", "s",
            url_hash="rv-b",
        )
        with self.assertRaisesRegex(ValueError, "revisit_of"):
            self.db.commit_staged("shelly", sid, revisit_of=[])
        self.assertEqual(len(self.db.list_notes("shelly")), 1)
        self.assertEqual(
            self.db._rows(
                "SELECT COUNT(*) AS n FROM staging_notes WHERE session_id = ?",
                (sid,),
            )[0]["n"],
            1,
        )
        self.assertEqual(self.db.get_note(original_id)["revisit_of"], 0)

    def test_commit_refuses_terminal_session(self):
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.finish_browse_session(sid, "failed", 0, "stale")
        self.db.stage_note("shelly", sid, "hn", "https://late", "Late", "s", url_hash="late")
        with self.assertRaises(RuntimeError):
            self.db.commit_staged("shelly", sid, status="completed")
        self.assertEqual(self.db.list_notes("shelly"), [])

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

    def test_recover_stale_runs_ignores_recent_and_fails_old(self):
        old = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_note("shelly", old, "hn", "https://a", "A", "s", url_hash="h1")
        self.db._execute(
            "UPDATE browse_sessions SET started_at = '2020-01-01 00:00:00' WHERE id = ?",
            (old,),
        )
        fresh = self.db.start_browse_session("shelly", "scheduled")
        db2 = LifeDB(Path(self.tmp.name) / "life.db")
        try:
            sessions = db2.list_sessions("shelly")
            by_id = {row["id"]: row for row in sessions}
            self.assertEqual(by_id[old]["status"], "failed")
            self.assertEqual(by_id[old]["reason"], "stale_run_recovered")
            self.assertEqual(by_id[fresh]["status"], "running")
            self.assertEqual(db2.list_notes("shelly"), [])
            self.assertEqual(
                db2._rows("SELECT COUNT(*) AS n FROM staging_notes")[0]["n"], 0
            )
        finally:
            db2.close()

    def test_recover_stale_runs_cleans_orphan_staging_by_age(self):
        self.db.stage_diary("shelly", None, "2020-01-01", "old null diary")
        self.db.stage_note("shelly", None, "hn", "https://null", "Null", "s", url_hash="null-h")
        self.db.stage_note("shelly", -1001, "hn", "https://tok", "Tok", "s", url_hash="tok-h")
        self.db.stage_note("shelly", -2002, "hn", "https://fresh", "Fresh", "s", url_hash="fresh-h")
        self.db._execute(
            "UPDATE staging_notes SET fetched_at = '2020-01-01 00:00:00' WHERE url_hash = 'tok-h'"
        )
        self.db._execute(
            "UPDATE staging_diary SET created_at = '2020-01-01 00:00:00' WHERE date = '2020-01-01'"
        )
        db2 = LifeDB(Path(self.tmp.name) / "life.db")
        try:
            notes = db2._rows("SELECT session_id, url_hash FROM staging_notes")
            self.assertEqual(
                {(row["session_id"], row["url_hash"]) for row in notes},
                {(None, "null-h"), (-2002, "fresh-h")},
            )
            self.assertEqual(
                db2._rows("SELECT COUNT(*) AS n FROM staging_diary")[0]["n"], 0
            )
        finally:
            db2.close()

    def test_commit_staged_returns_only_new_notes_when_old_duplicate_exists(self):
        same_ts = self.db._now()
        old_id = self.db.add_note(
            "shelly", None, "hn", "https://a", "Same", "s", url_hash="dup-h"
        )
        self.db._execute(
            "UPDATE notes SET fetched_at = ? WHERE id = ?", (same_ts, old_id)
        )
        self.db.stage_note("shelly", None, "hn", "https://a", "Same", "s", url_hash="dup-h")
        self.db._execute(
            "UPDATE staging_notes SET fetched_at = ? WHERE persona_id = 'shelly'",
            (same_ts,),
        )
        notes = self.db.commit_staged("shelly", None, status="completed")
        self.assertEqual(len(notes), 1)
        self.assertNotEqual(notes[0]["id"], old_id)
        self.assertEqual(notes[0]["url_hash"], "dup-h")

    def test_add_diary_rewrite_after_soft_delete_becomes_visible(self):
        self.db.add_diary("shelly", "2026-08-12", "old", mood="calm")
        self.assertTrue(self.db.soft_delete_diary("shelly", "2026-08-12", reason="cleanup"))
        self.assertIsNone(self.db.get_diary("shelly", "2026-08-12"))
        self.db.add_diary("shelly", "2026-08-12", "new", mood="curious")
        row = self.db.get_diary("shelly", "2026-08-12")
        self.assertIsNotNone(row)
        self.assertEqual(row["content"], "new")

    def test_staged_diary_rewrite_after_soft_delete_becomes_visible(self):
        self.db.add_diary("shelly", "2026-08-12", "old")
        self.assertTrue(self.db.soft_delete_diary("shelly", "2026-08-12", reason="cleanup"))
        self.db.stage_diary("shelly", None, "2026-08-12", "staged", signature="s")
        self.db.commit_staged("shelly", None, status="completed")
        row = self.db.get_diary("shelly", "2026-08-12")
        self.assertIsNotNone(row)
        self.assertEqual(row["content"], "staged")

    def test_synthetic_token_staging_is_scoped(self):
        self.db.stage_note("shelly", -101, "hn", "https://a", "A", "s", url_hash="t1")
        self.db.stage_note("shelly", -102, "hn", "https://b", "B", "s", url_hash="t2")
        notes = self.db.commit_staged("shelly", -102, status="completed")
        self.assertEqual(len(notes), 1)
        self.assertEqual(notes[0]["url_hash"], "t2")
        remaining = self.db._rows(
            "SELECT session_id FROM staging_notes WHERE persona_id = 'shelly'"
        )
        self.assertEqual([row["session_id"] for row in remaining], [-101])

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

    def test_empty_seen_digest_does_not_wipe_watched_fingerprint(self):
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_seen("shelly", sid, "watch-hash", "digest-a")
        self.db.commit_staged("shelly", sid, status="completed")
        self.assertTrue(self.db.is_seen("shelly", "watch-hash", "digest-a"))

        revisit_sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_seen("shelly", revisit_sid, "watch-hash")
        self.db.commit_staged("shelly", revisit_sid, status="completed")
        self.assertTrue(self.db.is_seen("shelly", "watch-hash", "digest-a"))

    def test_commit_staged_interest_applies_delta_over_owner_edits(self):
        self.db.upsert_interest("shelly", "ai", "AI", 0.5, seen_count=0)
        sid = self.db.start_browse_session("shelly", "scheduled")
        self.db.stage_interest(
            "shelly", sid, "ai", "AI", 0.6, 1,
            base_weight=0.5, base_seen_count=0,
        )
        self.db.stage_interest(
            "shelly", sid, "ai", "AI", 0.7, 2,
            base_weight=0.5, base_seen_count=0,
        )
        self.db.upsert_interest("shelly", "ai", "AI owner", 0.6, seen_count=5)
        self.db.commit_staged("shelly", sid, status="completed")
        rows = {row["key"]: row for row in self.db.get_interests("shelly")}
        self.assertAlmostEqual(rows["ai"]["weight"], 0.8)
        self.assertEqual(rows["ai"]["seen_count"], 7)

    def test_rollback_soft_delete_restores_note_and_diary(self):
        note_id = self.db.add_note(
            "shelly", None, "hn", "https://rb", "RB", "s", url_hash="rb1"
        )
        self.assertTrue(self.db.soft_delete_note("shelly", note_id))
        note_log = self.db.list_change_log("shelly")[0]
        self.assertIsNotNone(self.db.rollback_change("shelly", note_log["id"]))
        self.assertIsNotNone(self.db.get_note(note_id))

        self.db.add_diary("shelly", "2026-08-13", "body")
        self.assertTrue(self.db.soft_delete_diary("shelly", "2026-08-13"))
        diary_log = self.db.list_change_log("shelly")[0]
        self.assertIsNotNone(self.db.rollback_change("shelly", diary_log["id"]))
        self.assertIsNotNone(self.db.get_diary("shelly", "2026-08-13"))

    def test_rollback_promotion_without_previous_interest_removes_ghost(self):
        self.db.upsert_interest("shelly", "ghost", "Ghost", 0.5, seen_count=0)
        log_id = self.db.log_change(
            "shelly", "interest", "ghost",
            json.dumps({"exists": False, "key": "ghost"}),
            json.dumps({"action": "wishlist_promote", "key": "ghost",
                        "name": "Ghost"}),
            actor="owner", reason="wishlist_promote", status="applied",
        )
        self.assertIsNotNone(self.db.rollback_change("shelly", log_id))
        self.assertNotIn(
            "ghost", [row["key"] for row in self.db.get_interests("shelly")]
        )

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
        today = datetime.now().strftime("%Y-%m-%d")
        self.db.add_note("shelly", None, "hn", "https://a", "A", "s", url_hash="h1")
        self.db.add_diary("shelly", today, "d")
        self.db.log_share_attempt("shelly", None, "sent", target_sid="s")
        self.db.start_browse_session("shelly", "scheduled")
        heat = self.db.timeline_heatmap("shelly", today[:7])
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
        restore = next(
            event for event in events
            if json.loads(event["payload"]).get("action") == "restore"
        )
        self.assertEqual(restore["kind"], "rollback")
        self.assertIn(f"note/{note_id}/restore/", restore["idempotency_key"])

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

    def test_life_plans_started_at_dead_column_is_dropped(self):
        path = Path(self.tmp.name) / "old_plans.db"
        raw = sqlite3.connect(path)
        raw.executescript(
            """
            CREATE TABLE life_plans (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                persona_id TEXT NOT NULL DEFAULT 'default',
                plan_date TEXT NOT NULL,
                task_id TEXT NOT NULL,
                kind TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                fixed INTEGER NOT NULL DEFAULT 0,
                reason TEXT DEFAULT '',
                budget_used REAL DEFAULT 0,
                scheduled_at TEXT DEFAULT '',
                started_at TEXT DEFAULT '',
                finished_at TEXT DEFAULT '',
                UNIQUE(persona_id, plan_date, task_id)
            );
            INSERT INTO life_plans
                (persona_id, plan_date, task_id, kind, status, started_at)
            VALUES
                ('shelly', '2026-08-12', 'old-task', 'browse', 'done',
                 '2026-08-12 09:00:00');
            """
        )
        raw.commit()
        raw.close()

        migrated = LifeDB(path)
        rows = migrated.list_plans("shelly", "2026-08-12")
        self.assertEqual(len(rows), 1)
        self.assertNotIn("started_at", rows[0].keys())
        migrated.close()

        check = sqlite3.connect(path)
        cols = [row[1] for row in check.execute("PRAGMA table_info('life_plans')")]
        check.close()
        self.assertNotIn("started_at", cols)

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

    def test_plan_mutations_reject_non_pending_rows(self):
        self.db.add_optional_plan(
            "shelly", "2026-08-12", "extra-1", "peek", "2026-08-12 12:00:00",
        )
        self.assertTrue(self.db.update_plan(
            "shelly", "2026-08-12", "extra-1", "done",
        ))
        self.assertFalse(self.db.defer_plan(
            "shelly", "2026-08-12", "extra-1", "2026-08-12 14:00:00",
        ))
        self.assertFalse(self.db.skip_plan(
            "shelly", "2026-08-12", "extra-1", "late",
        ))
        self.assertFalse(self.db.reorder_plan(
            "shelly", "2026-08-12", "extra-1", 1,
        ))
        row = next(
            item for item in self.db.list_plans("shelly", "2026-08-12")
            if item["task_id"] == "extra-1"
        )
        self.assertEqual(row["status"], "done")

    def test_reorder_plan_same_timestamp_is_not_reported_as_success(self):
        self.db.add_optional_plan(
            "shelly", "2026-08-12", "extra-1", "peek", "2026-08-12 12:00:00",
        )
        self.db.add_optional_plan(
            "shelly", "2026-08-12", "extra-2", "peek", "2026-08-12 12:00:00",
        )
        self.assertFalse(self.db.reorder_plan("shelly", "2026-08-12", "extra-1", 2))
        actions = [
            json.loads(e["payload"])["action"]
            for e in self.db.list_events("shelly")
            if e["kind"] == "change"
        ]
        self.assertNotIn("reorder", actions)


if __name__ == "__main__":
    unittest.main()