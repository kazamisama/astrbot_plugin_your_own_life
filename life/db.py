"""Per-persona SQLite storage for the internet-life archive."""
from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterator, Optional

from life.timeutil import (
    DEFAULT_TIMEZONE,
    local_now,
    local_today,
    normalize_timezone,
    to_local,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS browse_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    trigger TEXT NOT NULL DEFAULT 'scheduled',
    kind TEXT NOT NULL DEFAULT 'browse',
    status TEXT NOT NULL DEFAULT 'running',
    reason TEXT DEFAULT '',
    energy_before REAL,
    mood_before TEXT DEFAULT '',
    notes_count INTEGER DEFAULT 0,
    error TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS notes (
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
);
CREATE TABLE IF NOT EXISTS diary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    date TEXT NOT NULL,
    content TEXT NOT NULL,
    signature TEXT DEFAULT '',
    mood TEXT DEFAULT '',
    energy REAL,
    interest_top TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    deleted_at TEXT DEFAULT '',
    UNIQUE(persona_id, date)
);
CREATE TABLE IF NOT EXISTS interests (
    persona_id TEXT NOT NULL DEFAULT 'default',
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5,
    seen_count INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT DEFAULT '',
    PRIMARY KEY (persona_id, key)
);
CREATE TABLE IF NOT EXISTS state_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    ts TEXT NOT NULL,
    activity TEXT NOT NULL,
    energy REAL,
    mood TEXT DEFAULT '',
    curiosity REAL,
    extra TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS seen_items (
    persona_id TEXT NOT NULL DEFAULT 'default',
    url_hash TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (persona_id, url_hash)
);
CREATE TABLE IF NOT EXISTS share_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    note_id INTEGER,
    attempted_at TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT DEFAULT '',
    target_sid TEXT DEFAULT '',
    message TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS persona_prompts (
    persona_id TEXT PRIMARY KEY,
    system_prompt TEXT DEFAULT '',
    fetched_at TEXT DEFAULT '',
    source TEXT DEFAULT '',
    status TEXT DEFAULT 'ok',
    error TEXT DEFAULT '',
    updated_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    entity TEXT NOT NULL,
    entity_id TEXT DEFAULT '',
    old_value TEXT DEFAULT '',
    new_value TEXT DEFAULT '',
    actor TEXT DEFAULT 'owner',
    reason TEXT DEFAULT '',
    status TEXT DEFAULT 'applied',
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_change_log_persona_time ON change_log(persona_id, ts);
CREATE TABLE IF NOT EXISTS event_chain (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT DEFAULT '{}',
    source_refs TEXT DEFAULT '[]',
    idempotency_key TEXT NOT NULL,
    UNIQUE(persona_id, idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_event_chain_persona_time
    ON event_chain(persona_id, ts);
CREATE INDEX IF NOT EXISTS idx_event_chain_persona_kind_time
    ON event_chain(persona_id, kind, ts);
CREATE TABLE IF NOT EXISTS life_plans (
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
CREATE INDEX IF NOT EXISTS idx_life_plans_persona_date
    ON life_plans(persona_id, plan_date, status);
CREATE TABLE IF NOT EXISTS injection_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    ts TEXT NOT NULL,
    source TEXT DEFAULT '',
    context TEXT DEFAULT '',
    field TEXT DEFAULT '',
    preview TEXT DEFAULT '',
    detected INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_injection_log_persona_time ON injection_log(persona_id, ts);
CREATE TABLE IF NOT EXISTS life_leases (
    persona_id TEXT NOT NULL,
    task_key TEXT NOT NULL,
    holder TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    PRIMARY KEY (persona_id, task_key)
);
CREATE TABLE IF NOT EXISTS staging_notes (
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
    url_hash TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_diary (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    session_id INTEGER,
    date TEXT NOT NULL,
    content TEXT NOT NULL,
    signature TEXT DEFAULT '',
    mood TEXT DEFAULT '',
    energy REAL,
    interest_top TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    session_id INTEGER,
    ts TEXT NOT NULL,
    activity TEXT NOT NULL,
    energy REAL,
    mood TEXT DEFAULT '',
    curiosity REAL,
    extra TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    text TEXT NOT NULL,
    interest_key TEXT DEFAULT '',
    interest_name TEXT DEFAULT '',
    source TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    reason TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_wishlist_persona_status ON wishlist(persona_id, status, created_at);
CREATE TABLE IF NOT EXISTS staging_seen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    session_id INTEGER,
    url_hash TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    session_id INTEGER,
    text TEXT NOT NULL,
    interest_key TEXT DEFAULT '',
    source TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS staging_interests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    session_id INTEGER,
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    weight REAL NOT NULL DEFAULT 0.5,
    seen_count INTEGER NOT NULL DEFAULT 0,
    last_seen_at TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS daily_usage (
    persona_id TEXT NOT NULL,
    date TEXT NOT NULL,
    llm_calls INTEGER NOT NULL DEFAULT 0,
    tokens INTEGER NOT NULL DEFAULT 0,
    energy_used REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (persona_id, date)
);
CREATE TABLE IF NOT EXISTS reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    period TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'done',
    content TEXT NOT NULL,
    confidence REAL NOT NULL DEFAULT 0.0,
    source_refs TEXT DEFAULT '[]',
    UNIQUE(persona_id, period, period_start)
);
CREATE TABLE IF NOT EXISTS time_capsules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    note_id INTEGER NOT NULL,
    sealed_at TEXT NOT NULL,
    unlock_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'sealed',
    reply TEXT DEFAULT '',
    replied_at TEXT DEFAULT '',
    source_refs TEXT DEFAULT '[]',
    UNIQUE(persona_id, note_id)
);
CREATE INDEX IF NOT EXISTS idx_notes_persona_fetched ON notes(persona_id, fetched_at);
CREATE INDEX IF NOT EXISTS idx_sessions_persona_started ON browse_sessions(persona_id, started_at);
CREATE INDEX IF NOT EXISTS idx_snapshots_persona_ts ON state_snapshots(persona_id, ts);
CREATE INDEX IF NOT EXISTS idx_share_log_persona_time ON share_log(persona_id, attempted_at);
"""

_LEGACY_TABLES = (
    "browse_sessions",
    "notes",
    "diary_entries",
    "interests",
    "state_snapshots",
    "seen_items",
)


def _now_str(tz_name: str = DEFAULT_TIMEZONE) -> str:
    return local_now(tz_name).strftime("%Y-%m-%d %H:%M:%S")


def _today_str(tz_name: str = DEFAULT_TIMEZONE) -> str:
    return local_today(tz_name)


class LifeDB:
    """Per-persona sqlite wrapper with automatic v0.1 -> v2 migration."""

    def __init__(self, path: str | Path, timezone: str = DEFAULT_TIMEZONE):
        self.path = Path(path)
        self.timezone = normalize_timezone(timezone)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            if self._is_legacy():
                self._migrate_legacy()
            self._conn.executescript(_SCHEMA)
            self._ensure_column("notes", "deleted_at", "deleted_at TEXT DEFAULT ''")
            self._ensure_column("diary_entries", "deleted_at", "deleted_at TEXT DEFAULT ''")
            self._ensure_column("diary_entries", "signature", "signature TEXT DEFAULT ''")
            self._ensure_column("browse_sessions", "kind", "kind TEXT NOT NULL DEFAULT 'browse'")
            self._ensure_column("wishlist", "interest_name", "interest_name TEXT DEFAULT ''")
            self._ensure_column("life_plans", "fixed", "fixed INTEGER NOT NULL DEFAULT 0")
            self._ensure_column("daily_usage", "energy_used", "energy_used REAL NOT NULL DEFAULT 0")
            self._ensure_column("notes", "temperature", "temperature REAL NOT NULL DEFAULT 1.0")
            self._ensure_column("notes", "last_touched_at", "last_touched_at TEXT DEFAULT ''")
            self._ensure_column("reviews", "confidence", "confidence REAL NOT NULL DEFAULT 0")
            self._conn.commit()
        self.recover_stale_runs()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def _now(self) -> str:
        return _now_str(self.timezone)

    def _today(self) -> str:
        return _today_str(self.timezone)

    # ----- schema helpers -----

    def _column_names(self, table: str) -> set[str]:
        cur = self._conn.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cur.fetchall()}

    def _table_exists(self, table: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
        )
        return cur.fetchone() is not None

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        if column not in self._column_names(table):
            self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")

    def _is_legacy(self) -> bool:
        if not self._table_exists("notes"):
            return False
        cols = self._column_names("notes")
        return bool(cols) and "persona_id" not in cols

    def _migrate_legacy(self) -> None:
        for table in _LEGACY_TABLES:
            if self._table_exists(table):
                self._conn.execute(f"ALTER TABLE {table} RENAME TO {table}_legacy")
        self._conn.executescript(_SCHEMA)
        copies = (
            (
                "browse_sessions",
                "(persona_id, started_at, ended_at, trigger, status, reason, energy_before, mood_before, notes_count, error)",
                "SELECT 'default', started_at, ended_at, trigger, status, reason, energy_before, mood_before, notes_count, error FROM browse_sessions_legacy",
            ),
            (
                "notes",
                "(persona_id, session_id, fetched_at, source, url, title, summary, opinion, mood, interest_level, interest_key, interest_name, category, tags, share_decision, share_status, url_hash)",
                "SELECT 'default', session_id, fetched_at, source, url, title, summary, opinion, mood, interest_level, interest_key, interest_name, 'other', '[]', '', '', url_hash FROM notes_legacy",
            ),
            (
                "diary_entries",
                "(persona_id, date, content, mood, energy, interest_top, created_at)",
                "SELECT 'default', date, content, mood, energy, interest_top, created_at FROM diary_entries_legacy",
            ),
            (
                "interests",
                "(persona_id, key, name, weight, seen_count, last_seen_at)",
                "SELECT 'default', key, name, weight, seen_count, last_seen_at FROM interests_legacy",
            ),
            (
                "state_snapshots",
                "(persona_id, ts, activity, energy, mood, curiosity, extra)",
                "SELECT 'default', ts, activity, energy, mood, curiosity, extra FROM state_snapshots_legacy",
            ),
            (
                "seen_items",
                "(persona_id, url_hash, first_seen_at)",
                "SELECT 'default', url_hash, first_seen_at FROM seen_items_legacy",
            ),
        )
        for table, cols, select in copies:
            if self._table_exists(table + "_legacy"):
                self._conn.execute(f"INSERT OR IGNORE INTO {table} {cols} {select}")
        for table in _LEGACY_TABLES:
            if self._table_exists(table + "_legacy"):
                self._conn.execute(f"DROP TABLE {table}_legacy")
        self._conn.commit()

    def _execute(self, sql: str, params: tuple = (), commit: bool = True):
        with self._lock:
            cur = self._conn.execute(sql, params)
            if commit:
                self._conn.commit()
            return cur

    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cur = self._conn.execute(sql, params)
            return [dict(row) for row in cur.fetchall()]

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                yield
                self._conn.commit()
            except BaseException:
                self._conn.rollback()
                raise

    def _one(self, sql: str, params: tuple = ()) -> Optional[dict]:
        rows = self._rows(sql, params)
        return rows[0] if rows else None

    # ----- browse sessions -----

    def start_browse_session(
        self,
        persona_id: str,
        trigger: str = "scheduled",
        energy_before: Optional[float] = None,
        mood_before: str = "",
        kind: str = "browse",
    ) -> int:
        cur = self._execute(
            "INSERT INTO browse_sessions (persona_id, started_at, trigger, kind, status, energy_before, mood_before) "
            "VALUES (?, ?, ?, ?, 'running', ?, ?)",
            (persona_id, self._now(), trigger, kind, energy_before, mood_before),
        )
        return int(cur.lastrowid)

    def finish_browse_session(
        self,
        session_id: int,
        status: str,
        notes_count: int = 0,
        reason: str = "",
        error: str = "",
    ) -> None:
        self._execute(
            "UPDATE browse_sessions SET ended_at = ?, status = ?, notes_count = ?, reason = ?, error = ? "
            "WHERE id = ?",
            (self._now(), status, notes_count, reason, error, session_id),
        )

    def list_sessions(
        self, persona_id: str, date: Optional[str] = None, limit: int = 20
    ) -> list[dict]:
        if date:
            return self._rows(
                "SELECT * FROM browse_sessions WHERE persona_id = ? AND started_at LIKE ? "
                "ORDER BY started_at DESC LIMIT ?",
                (persona_id, date + "%", limit),
            )
        return self._rows(
            "SELECT * FROM browse_sessions WHERE persona_id = ? ORDER BY started_at DESC LIMIT ?",
            (persona_id, limit),
        )

    def count_sessions_by_kind(
        self, persona_id: str, date: str, kind: str = "browse"
    ) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM browse_sessions "
            "WHERE persona_id = ? AND kind = ? AND started_at LIKE ?",
            (persona_id, kind, date + "%"),
        )
        return int(row["n"] or 0) if row else 0

    # ----- notes -----

    def add_note(
        self,
        persona_id: str,
        session_id: Optional[int],
        source: str,
        url: str,
        title: str,
        summary: str,
        opinion: str = "",
        mood: str = "",
        interest_level: float = 0.5,
        interest_key: str = "",
        interest_name: str = "",
        category: str = "other",
        tags: Optional[list[str]] = None,
        share_decision: Optional[dict] = None,
        url_hash: str = "",
    ) -> Optional[int]:
        share_json = ""
        if share_decision and share_decision.get("should_share"):
            share_json = json.dumps(share_decision, ensure_ascii=False)
        cur = self._execute(
            "INSERT OR IGNORE INTO notes "
            "(persona_id, session_id, fetched_at, source, url, title, summary, opinion, mood, "
            "interest_level, interest_key, interest_name, category, tags, share_decision, share_status, url_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)",
            (
                persona_id,
                session_id,
                self._now(),
                source,
                url,
                title,
                summary,
                opinion,
                mood,
                interest_level,
                interest_key,
                interest_name,
                category,
                json.dumps(tags or [], ensure_ascii=False),
                share_json,
                url_hash,
            ),
        )
        if cur.rowcount == 0:
            return None
        return int(cur.lastrowid)

    def get_note(self, note_id: int) -> Optional[dict]:
        return self._one("SELECT * FROM notes WHERE id = ? AND deleted_at = ''", (note_id,))

    def list_notes(
        self, persona_id: str, date: Optional[str] = None, limit: int = 100
    ) -> list[dict]:
        if date:
            return self._rows(
                "SELECT * FROM notes WHERE persona_id = ? AND fetched_at LIKE ? "
                "AND deleted_at = '' ORDER BY fetched_at DESC LIMIT ?",
                (persona_id, date + "%", limit),
            )
        return self._rows(
            "SELECT * FROM notes WHERE persona_id = ? AND deleted_at = '' "
            "ORDER BY fetched_at DESC LIMIT ?",
            (persona_id, limit),
        )

    def pending_share_notes(self, persona_id: str, limit: int = 50) -> list[dict]:
        return self._rows(
            "SELECT * FROM notes WHERE persona_id = ? AND share_status = '' "
            "AND share_decision != '' AND deleted_at = '' ORDER BY fetched_at ASC LIMIT ?",
            (persona_id, limit),
        )

    def update_note_share_status(self, note_id: int, status: str) -> None:
        self._execute(
            "UPDATE notes SET share_status = ? WHERE id = ?", (status, note_id)
        )

    def search_notes(
        self,
        persona_id: str,
        query: str = "",
        category: str = "",
        date: str = "",
        limit: int = 10,
        temperature_weighted: bool = False,
    ) -> list[dict]:
        sql = "SELECT * FROM notes WHERE persona_id = ? AND deleted_at = ''"
        params: list[Any] = [persona_id]
        if query:
            sql += " AND (title LIKE ? OR summary LIKE ? OR opinion LIKE ? OR tags LIKE ?)"
            like = f"%{query}%"
            params += [like, like, like, like]
        if category:
            sql += " AND category = ?"
            params.append(category)
        if date:
            sql += " AND fetched_at LIKE ?"
            params.append(date + "%")
        if temperature_weighted:
            sql += " ORDER BY temperature DESC, fetched_at DESC LIMIT ?"
        else:
            sql += " ORDER BY fetched_at DESC LIMIT ?"
        params.append(limit)
        return self._rows(sql, tuple(params))

    def search_diary(
        self,
        persona_id: str,
        query: str = "",
        category: str = "",
        date: str = "",
        limit: int = 10,
    ) -> list[dict]:
        sql = "SELECT * FROM diary_entries WHERE persona_id = ? AND deleted_at = ''"
        params: list[Any] = [persona_id]
        if query:
            sql += " AND content LIKE ?"
            params.append(f"%{query}%")
        if date:
            sql += " AND date = ?"
            params.append(date)
        sql += " ORDER BY date DESC LIMIT ?"
        params.append(limit)
        return self._rows(sql, tuple(params))

    # ----- diary -----

    def add_diary(
        self,
        persona_id: str,
        date: str,
        content: str,
        mood: str = "",
        energy: Optional[float] = None,
        interest_top: str = "",
        signature: str = "",
    ) -> None:
        self._execute(
            "INSERT INTO diary_entries "
            "(persona_id, date, content, signature, mood, energy, interest_top, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id, date) DO UPDATE SET content = excluded.content, "
            "signature = excluded.signature, mood = excluded.mood, energy = excluded.energy, "
            "interest_top = excluded.interest_top",
            (persona_id, date, content, signature, mood, energy, interest_top, self._now()),
        )

    def get_diary(self, persona_id: str, date: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM diary_entries WHERE persona_id = ? AND date = ? "
            "AND deleted_at = ''",
            (persona_id, date),
        )

    def list_diaries(self, persona_id: str, limit: int = 30) -> list[dict]:
        return self._rows(
            "SELECT * FROM diary_entries WHERE persona_id = ? AND deleted_at = '' "
            "ORDER BY date DESC LIMIT ?",
            (persona_id, limit),
        )

    # ----- interests -----

    def get_interests(self, persona_id: str, limit: Optional[int] = None) -> list[dict]:
        if limit:
            return self._rows(
                "SELECT * FROM interests WHERE persona_id = ? ORDER BY weight DESC LIMIT ?",
                (persona_id, limit),
            )
        return self._rows(
            "SELECT * FROM interests WHERE persona_id = ? ORDER BY weight DESC",
            (persona_id,),
        )

    def upsert_interest(
        self,
        persona_id: str,
        key: str,
        name: str,
        weight: float,
        seen_count: Optional[int] = None,
        last_seen_at: Optional[str] = None,
    ) -> None:
        current = self._one(
            "SELECT * FROM interests WHERE persona_id = ? AND key = ?",
            (persona_id, key),
        )
        if current is None:
            self._execute(
                "INSERT INTO interests (persona_id, key, name, weight, seen_count, last_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (persona_id, key, name, weight,
                 seen_count if seen_count is not None else 1,
                 last_seen_at or self._now()),
            )
            return
        self._execute(
            "UPDATE interests SET name = ?, weight = ?, seen_count = ?, last_seen_at = ? "
            "WHERE persona_id = ? AND key = ?",
            (name, weight,
             seen_count if seen_count is not None else current["seen_count"] + 1,
             last_seen_at or self._now(), persona_id, key),
        )

    def decay_interests(
        self, persona_id: str, factor: float, now_str: Optional[str] = None
    ) -> int:
        cur = self._execute(
            "UPDATE interests SET weight = MAX(0.0, MIN(1.0, weight * ?)) "
            "WHERE persona_id = ?",
            (factor, persona_id),
        )
        return int(cur.rowcount)

    # ----- memory temperature -----

    def decay_note_temperature(
        self, persona_id: str, factor: float, now_str: Optional[str] = None
    ) -> int:
        """Decay note warmth by a daily multiplier; floor keeps cold memory alive."""
        factor = max(0.0, min(1.0, float(factor)))
        cur = self._execute(
            "UPDATE notes SET temperature = MAX(0.05, MIN(1.0, temperature * ?)) "
            "WHERE persona_id = ? AND deleted_at = ''",
            (factor, persona_id),
        )
        return int(cur.rowcount)

    def rehydrate_notes(
        self,
        note_ids: list[int],
        boost: float = 1.0,
        now_str: Optional[str] = None,
    ) -> int:
        """Warm recalled notes back up and mark when they were touched."""
        ids = [int(note_id) for note_id in note_ids if int(note_id) > 0]
        if not ids:
            return 0
        boost = max(0.0, min(1.0, float(boost)))
        placeholders = ",".join("?" * len(ids))
        cur = self._execute(
            f"UPDATE notes SET temperature = MAX(?, temperature), "
            f"last_touched_at = ? "
            f"WHERE id IN ({placeholders}) AND deleted_at = ''",
            (boost, now_str or self._now(), *ids),
        )
        return int(cur.rowcount)

    # ----- state snapshots -----

    def add_state_snapshot(
        self,
        persona_id: str,
        activity: str,
        energy: Optional[float] = None,
        mood: str = "",
        curiosity: Optional[float] = None,
        extra: str = "",
    ) -> int:
        cur = self._execute(
            "INSERT INTO state_snapshots (persona_id, ts, activity, energy, mood, curiosity, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (persona_id, self._now(), activity, energy, mood, curiosity, extra),
        )
        return int(cur.lastrowid)

    def list_state_snapshots(
        self,
        persona_id: str,
        since_date: Optional[str] = None,
        limit: int = 200,
    ) -> list[dict]:
        if since_date:
            return self._rows(
                "SELECT * FROM state_snapshots WHERE persona_id = ? AND ts LIKE ? "
                "ORDER BY ts DESC LIMIT ?",
                (persona_id, since_date + "%", limit),
            )
        return self._rows(
            "SELECT * FROM state_snapshots WHERE persona_id = ? ORDER BY ts DESC LIMIT ?",
            (persona_id, limit),
        )

    def has_snapshot_activity(
        self, persona_id: str, date: str, activity: str
    ) -> bool:
        row = self._one(
            "SELECT 1 AS n FROM state_snapshots WHERE persona_id = ? "
            "AND activity = ? AND ts LIKE ? LIMIT 1",
            (persona_id, activity, date + "%"),
        )
        return row is not None

    # ----- seen cache -----

    def is_seen(self, persona_id: str, url_hash: str) -> bool:
        row = self._one(
            "SELECT 1 FROM seen_items WHERE persona_id = ? AND url_hash = ?",
            (persona_id, url_hash),
        )
        return row is not None

    def mark_seen(self, persona_id: str, url_hash: str, now_str: Optional[str] = None) -> None:
        self._execute(
            "INSERT OR IGNORE INTO seen_items (persona_id, url_hash, first_seen_at) VALUES (?, ?, ?)",
            (persona_id, url_hash, now_str or self._now()),
        )

    # ----- run staging (crash-safe run writes) -----

    def stage_note(
        self,
        persona_id: str,
        session_id: int,
        source: str,
        url: str,
        title: str,
        summary: str,
        opinion: str = "",
        mood: str = "",
        interest_level: float = 0.5,
        interest_key: str = "",
        interest_name: str = "",
        category: str = "other",
        tags: Optional[list[str]] = None,
        share_decision: Optional[dict] = None,
        url_hash: str = "",
    ) -> int:
        share_json = ""
        if share_decision and share_decision.get("should_share"):
            share_json = json.dumps(share_decision, ensure_ascii=False)
        cur = self._execute(
            "INSERT INTO staging_notes "
            "(persona_id, session_id, fetched_at, source, url, title, summary, opinion, mood, "
            "interest_level, interest_key, interest_name, category, tags, share_decision, share_status, url_hash) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', ?)",
            (
                persona_id,
                session_id,
                self._now(),
                source,
                url,
                title,
                summary,
                opinion,
                mood,
                interest_level,
                interest_key,
                interest_name,
                category,
                json.dumps(tags or [], ensure_ascii=False),
                share_json,
                url_hash,
            ),
        )
        return int(cur.lastrowid)

    def stage_diary(
        self,
        persona_id: str,
        session_id: Optional[int],
        date: str,
        content: str,
        mood: str = "",
        energy: Optional[float] = None,
        interest_top: str = "",
        signature: str = "",
    ) -> int:
        cur = self._execute(
            "INSERT INTO staging_diary "
            "(persona_id, session_id, date, content, signature, mood, energy, interest_top, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (persona_id, session_id, date, content, signature, mood, energy, interest_top, self._now()),
        )
        return int(cur.lastrowid)

    def stage_snapshot(
        self,
        persona_id: str,
        session_id: Optional[int],
        activity: str,
        energy: Optional[float] = None,
        mood: str = "",
        curiosity: Optional[float] = None,
        extra: str = "",
    ) -> int:
        cur = self._execute(
            "INSERT INTO staging_snapshots "
            "(persona_id, session_id, ts, activity, energy, mood, curiosity, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (persona_id, session_id, self._now(), activity, energy, mood, curiosity, extra),
        )
        return int(cur.lastrowid)

    def stage_seen(self, persona_id: str, session_id: int, url_hash: str) -> int:
        cur = self._execute(
            "INSERT INTO staging_seen (persona_id, session_id, url_hash, first_seen_at) "
            "VALUES (?, ?, ?, ?)",
            (persona_id, session_id, url_hash, self._now()),
        )
        return int(cur.lastrowid)

    def stage_interest(
        self,
        persona_id: str,
        session_id: Optional[int],
        key: str,
        name: str,
        weight: float,
        seen_count: int,
        last_seen_at: Optional[str] = None,
    ) -> int:
        cur = self._execute(
            "INSERT INTO staging_interests "
            "(persona_id, session_id, key, name, weight, seen_count, last_seen_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (persona_id, session_id, key, name, weight, seen_count, last_seen_at or self._now()),
        )
        return int(cur.lastrowid)

    def stage_wishlist(
        self,
        persona_id: str,
        session_id: Optional[int],
        text: str,
        interest_key: str = "",
        source: str = "",
    ) -> int:
        cur = self._execute(
            "INSERT INTO staging_wishlist "
            "(persona_id, session_id, text, interest_key, source, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (persona_id, session_id, text, interest_key, source, self._now()),
        )
        return int(cur.lastrowid)

    def list_wishlist(
        self, persona_id: str, status: Optional[str] = None, limit: int = 200
    ) -> list[dict]:
        if status:
            return self._rows(
                "SELECT * FROM wishlist WHERE persona_id = ? AND status = ? "
                "ORDER BY created_at DESC LIMIT ?",
                (persona_id, status, limit),
            )
        return self._rows(
            "SELECT * FROM wishlist WHERE persona_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (persona_id, limit),
        )

    def update_wishlist_status(
        self,
        persona_id: str,
        item_id: int,
        status: str,
        reason: str = "",
        interest_key: str = "",
        interest_name: str = "",
    ) -> bool:
        if status not in ("pending", "promoted", "discarded"):
            return False
        cur = self._execute(
            "UPDATE wishlist SET status = ?, reason = ?, interest_key = ?, interest_name = ?, "
            "updated_at = ? WHERE id = ? AND persona_id = ?",
            (status, reason, interest_key, interest_name, self._now(), item_id, persona_id),
        )
        return int(cur.rowcount) > 0

    def commit_staged(
        self,
        persona_id: str,
        session_id: int,
        status: str = "completed",
        notes_count: int = 0,
        reason: str = "",
        error: str = "",
    ) -> list[dict]:
        with self._transaction():
            self._conn.execute(
                "INSERT INTO notes "
                "(persona_id, session_id, fetched_at, source, url, title, summary, opinion, mood, "
                "interest_level, interest_key, interest_name, category, tags, share_decision, share_status, url_hash) "
                "SELECT persona_id, session_id, fetched_at, source, url, title, summary, opinion, mood, "
                "interest_level, interest_key, interest_name, category, tags, share_decision, share_status, url_hash "
                "FROM staging_notes WHERE persona_id = ? AND "
                "(session_id = ? OR (session_id IS NULL AND ? IS NULL))",
                (persona_id, session_id, session_id),
            )
            self._conn.execute(
                "INSERT INTO diary_entries "
                "(persona_id, date, content, signature, mood, energy, interest_top, created_at) "
                "SELECT persona_id, date, content, signature, mood, energy, interest_top, created_at "
                "FROM staging_diary WHERE persona_id = ? AND "
                "(session_id = ? OR (session_id IS NULL AND ? IS NULL)) "
                "ON CONFLICT(persona_id, date) DO UPDATE SET content = excluded.content, "
                "signature = excluded.signature, mood = excluded.mood, "
                "energy = excluded.energy, interest_top = excluded.interest_top",
                (persona_id, session_id, session_id),
            )
            self._conn.execute(
                "INSERT INTO wishlist "
                "(persona_id, text, interest_key, interest_name, source, status, reason, created_at, updated_at) "
                "SELECT persona_id, text, interest_key, '', source, 'pending', '', created_at, created_at "
                "FROM staging_wishlist WHERE persona_id = ? AND "
                "(session_id = ? OR (session_id IS NULL AND ? IS NULL))",
                (persona_id, session_id, session_id),
            )
            self._conn.execute(
                "INSERT INTO state_snapshots "
                "(persona_id, ts, activity, energy, mood, curiosity, extra) "
                "SELECT persona_id, ts, activity, energy, mood, curiosity, extra "
                "FROM staging_snapshots WHERE persona_id = ? AND "
                "(session_id = ? OR (session_id IS NULL AND ? IS NULL))",
                (persona_id, session_id, session_id),
            )
            self._conn.execute(
                "INSERT OR IGNORE INTO seen_items (persona_id, url_hash, first_seen_at) "
                "SELECT persona_id, url_hash, first_seen_at FROM staging_seen "
                "WHERE persona_id = ? AND "
                "(session_id = ? OR (session_id IS NULL AND ? IS NULL))",
                (persona_id, session_id, session_id),
            )
            interest_rows = self._conn.execute(
                "SELECT persona_id, key, name, weight, seen_count, last_seen_at "
                "FROM staging_interests WHERE persona_id = ? AND "
                "(session_id = ? OR (session_id IS NULL AND ? IS NULL))",
                (persona_id, session_id, session_id),
            ).fetchall()
            for row in interest_rows:
                self._conn.execute(
                    "INSERT INTO interests (persona_id, key, name, weight, seen_count, last_seen_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(persona_id, key) DO UPDATE SET name = excluded.name, weight = excluded.weight, "
                    "seen_count = excluded.seen_count, last_seen_at = excluded.last_seen_at",
                    (row["persona_id"], row["key"], row["name"], row["weight"], row["seen_count"], row["last_seen_at"]),
                )
            self._conn.execute(
                "UPDATE browse_sessions SET ended_at = ?, status = ?, notes_count = ?, reason = ?, error = ? "
                "WHERE id = ?",
                (self._now(), status, notes_count, reason, error, session_id),
            )
            self._delete_staging(persona_id, session_id)
        return self._rows(
            "SELECT * FROM notes WHERE persona_id = ? AND session_id = ? ORDER BY id",
            (persona_id, session_id),
        )

    def discard_staged(self, persona_id: str, session_id: int, error: str = "") -> None:
        with self._transaction():
            self._delete_staging(persona_id, session_id)
            self._conn.execute(
                "UPDATE browse_sessions SET ended_at = ?, status = 'failed', reason = 'staging_discarded', error = ? "
                "WHERE id = ? AND status = 'running'",
                (self._now(), error, session_id),
            )

    def recover_stale_runs(self) -> int:
        with self._transaction():
            rows = self._conn.execute(
                "SELECT id, persona_id FROM browse_sessions WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                self._delete_staging(row["persona_id"], int(row["id"]))
                self._conn.execute(
                    "UPDATE browse_sessions SET ended_at = ?, status = 'failed', "
                    "reason = 'stale_run_recovered', error = 'interrupted before commit' WHERE id = ?",
                    (self._now(), int(row["id"])),
                )
            self._conn.execute(
                "DELETE FROM staging_diary WHERE session_id IS NULL"
            )
            self._conn.execute(
                "DELETE FROM life_leases WHERE expires_at <= ?", (self._now(),)
            )
        return len(rows)

    def _delete_staging(self, persona_id: str, session_id: Optional[int]) -> None:
        for table in ("staging_notes", "staging_diary", "staging_snapshots",
                      "staging_seen", "staging_interests", "staging_wishlist"):
            self._conn.execute(
                f"DELETE FROM {table} WHERE persona_id = ? "
                "AND (session_id = ? OR (session_id IS NULL AND ? IS NULL))",
                (persona_id, session_id, session_id),
            )

    # ----- daily usage -----

    def increment_llm_usage(
        self, persona_id: str, date: str, calls: int = 1, tokens: int = 0
    ) -> None:
        self._execute(
            "INSERT INTO daily_usage (persona_id, date, llm_calls, tokens) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(persona_id, date) DO UPDATE SET "
            "llm_calls = daily_usage.llm_calls + excluded.llm_calls, "
            "tokens = daily_usage.tokens + excluded.tokens",
            (persona_id, date, max(0, int(calls)), max(0, int(tokens))),
        )

    def increment_energy_usage(self, persona_id: str, date: str, amount: float) -> None:
        self._execute(
            "INSERT INTO daily_usage (persona_id, date, energy_used) VALUES (?, ?, ?) "
            "ON CONFLICT(persona_id, date) DO UPDATE SET "
            "energy_used = daily_usage.energy_used + excluded.energy_used",
            (persona_id, date, max(0.0, float(amount))),
        )

    def get_daily_usage(self, persona_id: str, date: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM daily_usage WHERE persona_id = ? AND date = ?",
            (persona_id, date),
        )

    def list_daily_usage(self, persona_id: str, limit: int = 90) -> list[dict]:
        return self._rows(
            "SELECT * FROM daily_usage WHERE persona_id = ? ORDER BY date DESC LIMIT ?",
            (persona_id, limit),
        )

    # ----- reviews / period stats -----

    def upsert_review(
        self,
        persona_id: str,
        period: str,
        period_start: str,
        period_end: str,
        content: str,
        status: str = "done",
        confidence: float = 0.0,
        source_refs: Optional[list] = None,
    ) -> int:
        cur = self._execute(
            "INSERT INTO reviews "
            "(persona_id, period, period_start, period_end, generated_at, status, content, confidence, source_refs) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id, period, period_start) DO UPDATE SET "
            "generated_at = excluded.generated_at, status = excluded.status, "
            "content = excluded.content, confidence = excluded.confidence, "
            "source_refs = excluded.source_refs",
            (
                persona_id,
                period,
                period_start,
                period_end,
                self._now(),
                status,
                content,
                max(0.0, min(1.0, float(confidence))),
                json.dumps(source_refs or [], ensure_ascii=False, default=str),
            ),
        )
        row = self._one(
            "SELECT * FROM reviews WHERE persona_id = ? AND period = ? AND period_start = ?",
            (persona_id, period, period_start),
        )
        return int(row["id"]) if row else 0

    def list_reviews(self, persona_id: str, limit: int = 12) -> list[dict]:
        return self._rows(
            "SELECT * FROM reviews WHERE persona_id = ? ORDER BY period_start DESC LIMIT ?",
            (persona_id, limit),
        )

    def count_notes_between(self, persona_id: str, start: str, end: str) -> int:
        row = self._one(
            "SELECT COUNT(*) AS n FROM notes WHERE persona_id = ? AND deleted_at = '' "
            "AND date(fetched_at) BETWEEN ? AND ?",
            (persona_id, start, end),
        )
        return int(row["n"] or 0) if row else 0

    def list_notes_between(
        self, persona_id: str, start: str, end: str, limit: int = 50
    ) -> list[dict]:
        return self._rows(
            "SELECT * FROM notes WHERE persona_id = ? AND deleted_at = '' "
            "AND date(fetched_at) BETWEEN ? AND ? ORDER BY fetched_at DESC LIMIT ?",
            (persona_id, start, end, limit),
        )

    def category_counts_between(
        self, persona_id: str, start: str, end: str
    ) -> list[dict]:
        return self._rows(
            "SELECT category, COUNT(*) AS n FROM notes WHERE persona_id = ? "
            "AND deleted_at = '' AND date(fetched_at) BETWEEN ? AND ? "
            "GROUP BY category ORDER BY n DESC",
            (persona_id, start, end),
        )

    # ----- time capsules -----

    def seal_capsule(
        self,
        persona_id: str,
        note_id: int,
        unlock_at: str,
        sealed_at: Optional[str] = None,
        source_refs: Optional[list] = None,
    ) -> Optional[int]:
        cur = self._execute(
            "INSERT OR IGNORE INTO time_capsules "
            "(persona_id, note_id, sealed_at, unlock_at, status, reply, replied_at, source_refs) "
            "VALUES (?, ?, ?, ?, 'sealed', '', '', ?)",
            (persona_id, note_id, sealed_at or self._now(), unlock_at,
             json.dumps(source_refs or [], ensure_ascii=False, default=str)),
        )
        if cur.rowcount == 0:
            return None
        return int(cur.lastrowid)

    def list_capsules(
        self, persona_id: str, status: Optional[str] = None, limit: int = 100
    ) -> list[dict]:
        if status:
            return self._rows(
                "SELECT * FROM time_capsules WHERE persona_id = ? AND status = ? "
                "ORDER BY sealed_at DESC LIMIT ?",
                (persona_id, status, limit),
            )
        return self._rows(
            "SELECT * FROM time_capsules WHERE persona_id = ? "
            "ORDER BY sealed_at DESC LIMIT ?",
            (persona_id, limit),
        )

    def get_capsule(self, persona_id: str, capsule_id: int) -> Optional[dict]:
        return self._one(
            "SELECT * FROM time_capsules WHERE persona_id = ? AND id = ?",
            (persona_id, capsule_id),
        )

    def capsules_due(
        self, persona_id: str, now_str: Optional[str] = None
    ) -> list[dict]:
        return self._rows(
            "SELECT * FROM time_capsules WHERE persona_id = ? "
            "AND status IN ('sealed', 'unlocked') AND reply = '' "
            "AND unlock_at <= ? ORDER BY unlock_at ASC",
            (persona_id, now_str or self._now()),
        )

    def unlock_capsule(
        self,
        persona_id: str,
        capsule_id: int,
        now_str: Optional[str] = None,
    ) -> bool:
        cur = self._execute(
            "UPDATE time_capsules SET status = 'unlocked', unlock_at = ? "
            "WHERE persona_id = ? AND id = ?",
            (now_str or self._now(), persona_id, capsule_id),
        )
        return cur.rowcount > 0

    def open_capsule_now(self, persona_id: str, capsule_id: int) -> bool:
        return self.unlock_capsule(persona_id, capsule_id)

    def save_capsule_reply(
        self,
        persona_id: str,
        capsule_id: int,
        reply: str,
        replied_at: Optional[str] = None,
    ) -> bool:
        cur = self._execute(
            "UPDATE time_capsules SET status = 'replied', reply = ?, replied_at = ? "
            "WHERE persona_id = ? AND id = ?",
            (reply, replied_at or self._now(), persona_id, capsule_id),
        )
        return cur.rowcount > 0

    # ----- task leases -----

    def _lease_expires(self, ttl_seconds: int) -> str:
        return to_local(
            datetime.now() + timedelta(seconds=max(1, int(ttl_seconds))),
            self.timezone,
        ).strftime("%Y-%m-%d %H:%M:%S")

    def acquire_lease(
        self, persona_id: str, task_key: str, holder: str, ttl_seconds: int = 300
    ) -> bool:
        now = self._now()
        expires = self._lease_expires(ttl_seconds)
        with self._transaction():
            self._conn.execute(
                "DELETE FROM life_leases WHERE persona_id = ? AND task_key = ? "
                "AND expires_at <= ?",
                (persona_id, task_key, now),
            )
            cur = self._conn.execute(
                "INSERT OR IGNORE INTO life_leases "
                "(persona_id, task_key, holder, acquired_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (persona_id, task_key, holder, now, expires),
            )
            return cur.rowcount > 0

    def renew_lease(
        self, persona_id: str, task_key: str, holder: str, ttl_seconds: int = 300
    ) -> bool:
        expires = self._lease_expires(ttl_seconds)
        cur = self._execute(
            "UPDATE life_leases SET acquired_at = ?, expires_at = ? "
            "WHERE persona_id = ? AND task_key = ? AND holder = ? AND expires_at > ?",
            (self._now(), expires, persona_id, task_key, holder, self._now()),
        )
        return cur.rowcount > 0

    def release_lease(self, persona_id: str, task_key: str, holder: str) -> bool:
        cur = self._execute(
            "DELETE FROM life_leases WHERE persona_id = ? AND task_key = ? AND holder = ?",
            (persona_id, task_key, holder),
        )
        return cur.rowcount > 0

    def cleanup_expired_leases(self) -> int:
        cur = self._execute(
            "DELETE FROM life_leases WHERE expires_at <= ?", (self._now(),)
        )
        return int(cur.rowcount)

    # ----- share log -----

    def log_share_attempt(
        self,
        persona_id: str,
        note_id: Optional[int],
        status: str,
        reason: str = "",
        target_sid: str = "",
        message: str = "",
    ) -> int:
        cur = self._execute(
            "INSERT INTO share_log (persona_id, note_id, attempted_at, status, reason, target_sid, message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (persona_id, note_id, self._now(), status, reason, target_sid, message),
        )
        share_id = int(cur.lastrowid)
        self.append_event(
            persona_id,
            "express",
            {
                "entity": "share",
                "note_id": note_id,
                "status": status,
                "reason": reason,
                "target_sid": target_sid,
            },
            [{"note_id": note_id}] if note_id else [],
            f"share_log/{share_id}",
        )
        return share_id

    def list_share_log(
        self, persona_id: str, date: Optional[str] = None, limit: int = 100
    ) -> list[dict]:
        if date:
            return self._rows(
                "SELECT * FROM share_log WHERE persona_id = ? AND attempted_at LIKE ? "
                "ORDER BY attempted_at DESC LIMIT ?",
                (persona_id, date + "%", limit),
            )
        return self._rows(
            "SELECT * FROM share_log WHERE persona_id = ? ORDER BY attempted_at DESC LIMIT ?",
            (persona_id, limit),
        )

    def count_share_success(self, persona_id: str, date: Optional[str] = None) -> int:
        if date:
            row = self._one(
                "SELECT COUNT(*) AS n FROM share_log WHERE persona_id = ? "
                "AND attempted_at LIKE ? AND status = 'sent'",
                (persona_id, date + "%"),
            )
        else:
            row = self._one(
                "SELECT COUNT(*) AS n FROM share_log WHERE persona_id = ? AND status = 'sent'",
                (persona_id,),
            )
        return int(row["n"] if row else 0)

    def last_share_success(self, persona_id: str, target_sid: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM share_log WHERE persona_id = ? AND target_sid = ? "
            "AND status = 'sent' ORDER BY attempted_at DESC LIMIT 1",
            (persona_id, target_sid),
        )

    def shared_url_hashes_since(
        self, persona_id: str, hours: int, now_ts: Optional[float] = None
    ) -> set[str]:
        import time as _time

        now = now_ts if now_ts is not None else _time.time()
        threshold = now - hours * 3600
        rows = self._rows(
            "SELECT n.url_hash AS h FROM share_log s JOIN notes n ON n.id = s.note_id "
            "WHERE s.persona_id = ? AND s.status = 'sent' AND s.attempted_at >= ? "
            "AND n.deleted_at = ''",
            (persona_id, to_local(datetime.fromtimestamp(threshold), self.timezone).strftime("%Y-%m-%d %H:%M:%S")),
        )
        return {row["h"] for row in rows if row["h"]}

    # ----- change log & trash -----

    def log_change(
        self,
        persona_id: str,
        entity: str,
        entity_id: Any,
        old_value: Any = "",
        new_value: Any = "",
        actor: str = "owner",
        reason: str = "",
        status: str = "applied",
    ) -> int:
        cur = self._execute(
            "INSERT INTO change_log "
            "(persona_id, entity, entity_id, old_value, new_value, actor, reason, status, ts) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                persona_id,
                entity,
                str(entity_id),
                old_value or "",
                new_value or "",
                actor or "owner",
                reason or "",
                status or "applied",
                self._now(),
            ),
        )
        return int(cur.lastrowid)

    def list_change_log(self, persona_id: str, limit: int = 100) -> list[dict]:
        return self._rows(
            "SELECT * FROM change_log WHERE persona_id = ? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (persona_id, limit),
        )

    def log_injection(
        self,
        persona_id: str,
        source: str = "",
        context: str = "",
        field: str = "",
        preview: str = "",
        detected: bool = True,
    ) -> int:
        cur = self._execute(
            "INSERT INTO injection_log "
            "(persona_id, ts, source, context, field, preview, detected) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                persona_id,
                self._now(),
                source or "",
                context or "",
                field or "",
                preview or "",
                1 if detected else 0,
            ),
        )
        return int(cur.lastrowid)

    def list_injection_log(self, persona_id: str, limit: int = 100) -> list[dict]:
        return self._rows(
            "SELECT * FROM injection_log WHERE persona_id = ? "
            "ORDER BY ts DESC, id DESC LIMIT ?",
            (persona_id, limit),
        )

    # ----- event chain -----

    def append_event(
        self,
        persona_id: str,
        kind: str,
        payload: Any = None,
        source_refs: Optional[list] = None,
        idempotency_key: Optional[str] = None,
        ts: Optional[str] = None,
    ) -> Optional[int]:
        if not kind:
            raise ValueError("kind is required")
        key = (idempotency_key or "").strip() or uuid.uuid4().hex
        cur = self._execute(
            "INSERT OR IGNORE INTO event_chain "
            "(persona_id, ts, kind, payload, source_refs, idempotency_key) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                persona_id,
                ts or self._now(),
                kind,
                json.dumps(payload or {}, ensure_ascii=False, default=str),
                json.dumps(source_refs or [], ensure_ascii=False, default=str),
                key,
            ),
        )
        if cur.rowcount == 0:
            return None
        return int(cur.lastrowid)

    def find_event(self, persona_id: str, idempotency_key: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM event_chain WHERE persona_id = ? AND idempotency_key = ?",
            (persona_id, idempotency_key),
        )

    def list_events(
        self,
        persona_id: str,
        kinds: Optional[list[str]] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict]:
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            return self._rows(
                f"SELECT * FROM event_chain WHERE persona_id = ? "
                f"AND kind IN ({placeholders}) ORDER BY ts DESC, id DESC "
                "LIMIT ? OFFSET ?",
                (persona_id, *kinds, max(0, int(limit)), max(0, int(offset))),
            )
        return self._rows(
            "SELECT * FROM event_chain WHERE persona_id = ? "
            "ORDER BY ts DESC, id DESC LIMIT ? OFFSET ?",
            (persona_id, max(0, int(limit)), max(0, int(offset))),
        )

    def replay_events(
        self,
        persona_id: str,
        kinds: Optional[list[str]] = None,
        limit: int = 1000,
    ) -> list[dict]:
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            return self._rows(
                f"SELECT * FROM event_chain WHERE persona_id = ? "
                f"AND kind IN ({placeholders}) ORDER BY ts ASC, id ASC LIMIT ?",
                (persona_id, *kinds, max(0, int(limit))),
            )
        return self._rows(
            "SELECT * FROM event_chain WHERE persona_id = ? "
            "ORDER BY ts ASC, id ASC LIMIT ?",
            (persona_id, max(0, int(limit))),
        )

    def count_events(
        self, persona_id: str, kinds: Optional[list[str]] = None
    ) -> int:
        if kinds:
            placeholders = ",".join("?" for _ in kinds)
            row = self._one(
                f"SELECT COUNT(*) AS n FROM event_chain WHERE persona_id = ? "
                f"AND kind IN ({placeholders})",
                (persona_id, *kinds),
            )
        else:
            row = self._one(
                "SELECT COUNT(*) AS n FROM event_chain WHERE persona_id = ?",
                (persona_id,),
            )
        return int(row["n"] or 0) if row else 0

    # ----- life plans -----

    def ensure_plan(
        self,
        persona_id: str,
        plan_date: str,
        task_id: str,
        kind: str,
        scheduled_at: str = "",
        fixed: bool = False,
    ) -> int:
        row = self._one(
            "SELECT id FROM life_plans WHERE persona_id = ? AND plan_date = ? AND task_id = ?",
            (persona_id, plan_date, task_id),
        )
        if row is not None:
            return int(row["id"])
        cur = self._execute(
            "INSERT INTO life_plans (persona_id, plan_date, task_id, kind, fixed, scheduled_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (persona_id, plan_date, task_id, kind, 1 if fixed else 0, scheduled_at or ""),
        )
        return int(cur.lastrowid)

    def update_plan(
        self,
        persona_id: str,
        plan_date: str,
        task_id: str,
        status: str,
        reason: str = "",
        budget_used: Optional[float] = None,
        finished_at: str = "",
    ) -> bool:
        sets = ["status = ?", "reason = ?"]
        params: list[Any] = [status, reason or ""]
        if budget_used is not None:
            sets.append("budget_used = ?")
            params.append(max(0.0, float(budget_used)))
        if finished_at:
            sets.append("finished_at = ?")
            params.append(finished_at)
        params += [persona_id, plan_date, task_id]
        cur = self._execute(
            f"UPDATE life_plans SET {', '.join(sets)} "
            "WHERE persona_id = ? AND plan_date = ? AND task_id = ?",
            tuple(params),
        )
        return cur.rowcount > 0

    def list_plans(
        self,
        persona_id: str,
        plan_date: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[dict]:
        sql = "SELECT * FROM life_plans WHERE persona_id = ?"
        params: list[Any] = [persona_id]
        if plan_date:
            sql += " AND plan_date = ?"
            params.append(plan_date)
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY scheduled_at ASC, id ASC"
        return self._rows(sql, tuple(params))

    def plan_summary(self, persona_id: str, plan_date: str) -> dict[str, Any]:
        rows = self._rows(
            "SELECT status, COUNT(*) AS n, COALESCE(SUM(budget_used), 0) AS budget "
            "FROM life_plans WHERE persona_id = ? AND plan_date = ? GROUP BY status",
            (persona_id, plan_date),
        )
        counts = {"done": 0, "pending": 0, "skipped": 0, "failed": 0}
        total = 0
        budget = 0.0
        for row in rows:
            status = str(row["status"] or "")
            total += int(row["n"] or 0)
            budget += float(row["budget"] or 0)
            if status in counts:
                counts[status] = int(row["n"] or 0)
        return {
            "persona_id": persona_id,
            "plan_date": plan_date,
            "total": total,
            "budget_used": budget,
            **counts,
        }

    def add_optional_plan(
        self,
        persona_id: str,
        plan_date: str,
        task_id: str,
        kind: str,
        scheduled_at: str,
        reason: str = "",
    ) -> Optional[int]:
        existing = self._one(
            "SELECT id FROM life_plans WHERE persona_id = ? AND plan_date = ? AND task_id = ?",
            (persona_id, plan_date, task_id),
        )
        if existing is not None:
            return None
        cur = self._execute(
            "INSERT INTO life_plans "
            "(persona_id, plan_date, task_id, kind, status, fixed, reason, scheduled_at) "
            "VALUES (?, ?, ?, ?, 'pending', 0, ?, ?)",
            (persona_id, plan_date, task_id, kind, reason or "", scheduled_at or ""),
        )
        plan_id = int(cur.lastrowid)
        self.append_event(
            persona_id,
            "change",
            {"entity": "plan", "action": "add", "plan_date": plan_date,
             "task_id": task_id, "kind": kind, "reason": reason},
            [{"entity": "plan", "plan_date": plan_date, "task_id": task_id}],
            f"plan/{plan_date}/{task_id}/add",
        )
        return plan_id

    def reorder_plan(
        self,
        persona_id: str,
        plan_date: str,
        task_id: str,
        position: int,
    ) -> bool:
        rows = self.list_plans(persona_id, plan_date)
        indexes = {str(row["task_id"]): i for i, row in enumerate(rows)}
        if task_id not in indexes:
            return False
        current = indexes[task_id]
        if rows[current].get("fixed"):
            return False
        target = max(0, min(int(position) - 1, len(rows) - 1))
        if target == current:
            return True
        if rows[target].get("fixed"):
            return False
        neighbor = rows[target]
        cur = self._execute(
            "UPDATE life_plans SET scheduled_at = ? "
            "WHERE persona_id = ? AND plan_date = ? AND task_id = ?",
            (neighbor.get("scheduled_at") or "", persona_id, plan_date, task_id),
        )
        self._execute(
            "UPDATE life_plans SET scheduled_at = ? "
            "WHERE persona_id = ? AND plan_date = ? AND task_id = ?",
            (rows[current].get("scheduled_at") or "", persona_id, plan_date, neighbor["task_id"]),
        )
        if cur.rowcount == 0:
            return False
        self.append_event(
            persona_id,
            "change",
            {"entity": "plan", "action": "reorder", "plan_date": plan_date,
             "task_id": task_id, "position": target + 1},
            [{"entity": "plan", "plan_date": plan_date, "task_id": task_id}],
            f"plan/{plan_date}/{task_id}/reorder/{target + 1}",
        )
        return True

    def defer_plan(
        self,
        persona_id: str,
        plan_date: str,
        task_id: str,
        scheduled_at: str,
        reason: str = "",
    ) -> bool:
        row = self._one(
            "SELECT * FROM life_plans WHERE persona_id = ? AND plan_date = ? AND task_id = ?",
            (persona_id, plan_date, task_id),
        )
        if row is None or row.get("fixed"):
            return False
        cur = self._execute(
            "UPDATE life_plans SET scheduled_at = ?, reason = ? "
            "WHERE persona_id = ? AND plan_date = ? AND task_id = ?",
            (scheduled_at or "", reason or "", persona_id, plan_date, task_id),
        )
        if cur.rowcount == 0:
            return False
        self.append_event(
            persona_id,
            "change",
            {"entity": "plan", "action": "defer", "plan_date": plan_date,
             "task_id": task_id, "scheduled_at": scheduled_at, "reason": reason},
            [{"entity": "plan", "plan_date": plan_date, "task_id": task_id}],
            f"plan/{plan_date}/{task_id}/defer",
        )
        return True

    def skip_plan(
        self,
        persona_id: str,
        plan_date: str,
        task_id: str,
        reason: str = "",
    ) -> bool:
        row = self._one(
            "SELECT * FROM life_plans WHERE persona_id = ? AND plan_date = ? AND task_id = ?",
            (persona_id, plan_date, task_id),
        )
        if row is None or row.get("fixed"):
            return False
        now = self._now()
        cur = self._execute(
            "UPDATE life_plans SET status = 'skipped', reason = ?, finished_at = ? "
            "WHERE persona_id = ? AND plan_date = ? AND task_id = ?",
            (reason or "skipped", now, persona_id, plan_date, task_id),
        )
        if cur.rowcount == 0:
            return False
        self.append_event(
            persona_id,
            "change",
            {"entity": "plan", "action": "skip", "plan_date": plan_date,
             "task_id": task_id, "reason": reason},
            [{"entity": "plan", "plan_date": plan_date, "task_id": task_id}],
            f"plan/{plan_date}/{task_id}/skip",
        )
        return True

    def soft_delete_note(
        self, persona_id: str, note_id: int, actor: str = "owner", reason: str = ""
    ) -> bool:
        note = self._one(
            "SELECT * FROM notes WHERE id = ? AND persona_id = ?", (note_id, persona_id)
        )
        if note is None or note.get("deleted_at"):
            return False
        now = self._now()
        self._execute(
            "UPDATE notes SET deleted_at = ? WHERE id = ? AND persona_id = ?",
            (now, note_id, persona_id),
        )
        self.log_change(
            persona_id, "note", note_id,
            json.dumps(note, ensure_ascii=False, default=str),
            json.dumps({"deleted_at": now}, ensure_ascii=False),
            actor=actor, reason=reason, status="applied",
        )
        self.append_event(
            persona_id,
            "change",
            {"entity": "note", "note_id": note_id, "action": "soft_delete",
             "reason": reason},
            [{"note_id": note_id, "url": note.get("url") or ""}],
            f"note/{note_id}/soft-delete",
            ts=now,
        )
        return True

    def restore_note(
        self, persona_id: str, note_id: int, actor: str = "owner", reason: str = ""
    ) -> bool:
        note = self._one(
            "SELECT * FROM notes WHERE id = ? AND persona_id = ?", (note_id, persona_id)
        )
        if note is None or not note.get("deleted_at"):
            return False
        self._execute(
            "UPDATE notes SET deleted_at = '' WHERE id = ? AND persona_id = ?",
            (note_id, persona_id),
        )
        self.log_change(
            persona_id, "note", note_id,
            json.dumps({"deleted_at": note["deleted_at"]}, ensure_ascii=False),
            json.dumps({"deleted_at": ""}, ensure_ascii=False),
            actor=actor, reason=reason, status="restored",
        )
        self.append_event(
            persona_id,
            "rollback",
            {"entity": "note", "note_id": note_id, "action": "restore",
             "reason": reason},
            [{"note_id": note_id, "url": note.get("url") or ""}],
            f"note/{note_id}/restore",
        )
        return True

    def soft_delete_diary(
        self, persona_id: str, date: str, actor: str = "owner", reason: str = ""
    ) -> bool:
        diary = self._one(
            "SELECT * FROM diary_entries WHERE persona_id = ? AND date = ?",
            (persona_id, date),
        )
        if diary is None or diary.get("deleted_at"):
            return False
        now = self._now()
        self._execute(
            "UPDATE diary_entries SET deleted_at = ? WHERE persona_id = ? AND date = ?",
            (now, persona_id, date),
        )
        self.log_change(
            persona_id, "diary", date,
            json.dumps(diary, ensure_ascii=False, default=str),
            json.dumps({"deleted_at": now}, ensure_ascii=False),
            actor=actor, reason=reason, status="applied",
        )
        self.append_event(
            persona_id,
            "change",
            {"entity": "diary", "date": date, "action": "soft_delete",
             "reason": reason},
            [{"entity": "diary", "date": date}],
            f"diary/{date}/soft-delete",
            ts=now,
        )
        return True

    def restore_diary(
        self, persona_id: str, date: str, actor: str = "owner", reason: str = ""
    ) -> bool:
        diary = self._one(
            "SELECT * FROM diary_entries WHERE persona_id = ? AND date = ?",
            (persona_id, date),
        )
        if diary is None or not diary.get("deleted_at"):
            return False
        self._execute(
            "UPDATE diary_entries SET deleted_at = '' WHERE persona_id = ? AND date = ?",
            (persona_id, date),
        )
        self.log_change(
            persona_id, "diary", date,
            json.dumps({"deleted_at": diary["deleted_at"]}, ensure_ascii=False),
            json.dumps({"deleted_at": ""}, ensure_ascii=False),
            actor=actor, reason=reason, status="restored",
        )
        self.append_event(
            persona_id,
            "rollback",
            {"entity": "diary", "date": date, "action": "restore",
             "reason": reason},
            [{"entity": "diary", "date": date}],
            f"diary/{date}/restore",
        )
        return True

    def list_trash(self, persona_id: str, limit: int = 100) -> dict[str, Any]:
        notes = self._rows(
            "SELECT * FROM notes WHERE persona_id = ? AND deleted_at != '' "
            "ORDER BY deleted_at DESC LIMIT ?",
            (persona_id, limit),
        )
        diaries = self._rows(
            "SELECT * FROM diary_entries WHERE persona_id = ? AND deleted_at != '' "
            "ORDER BY deleted_at DESC LIMIT ?",
            (persona_id, limit),
        )
        return {"persona_id": persona_id, "notes": notes, "diaries": diaries}

    def purge_trash(self, persona_id: str, retention_days: int) -> int:
        cutoff = to_local(
            datetime.now() - timedelta(days=max(0, int(retention_days))), self.timezone
        ).strftime("%Y-%m-%d %H:%M:%S")
        with self._transaction():
            note_rows = self._conn.execute(
                "SELECT id FROM notes WHERE persona_id = ? AND deleted_at != '' "
                "AND deleted_at <= ?",
                (persona_id, cutoff),
            ).fetchall()
            diary_rows = self._conn.execute(
                "SELECT date FROM diary_entries WHERE persona_id = ? AND deleted_at != '' "
                "AND deleted_at <= ?",
                (persona_id, cutoff),
            ).fetchall()
            for row in note_rows:
                self._conn.execute("DELETE FROM notes WHERE id = ?", (int(row["id"]),))
            for row in diary_rows:
                self._conn.execute(
                    "DELETE FROM diary_entries WHERE persona_id = ? AND date = ?",
                    (persona_id, row["date"]),
                )
        return len(note_rows) + len(diary_rows)

    # ----- persona prompt cache -----

    def get_persona_prompt(self, persona_id: str) -> Optional[dict]:
        return self._one(
            "SELECT * FROM persona_prompts WHERE persona_id = ?", (persona_id,)
        )

    def upsert_persona_prompt(
        self,
        persona_id: str,
        system_prompt: str,
        source: str,
        status: str = "ok",
        error: str = "",
    ) -> None:
        now = self._now()
        self._execute(
            "INSERT INTO persona_prompts (persona_id, system_prompt, fetched_at, source, status, error, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id) DO UPDATE SET system_prompt = excluded.system_prompt, "
            "fetched_at = excluded.fetched_at, source = excluded.source, status = excluded.status, "
            "error = excluded.error, updated_at = excluded.updated_at",
            (persona_id, system_prompt, now, source, status, error, now),
        )

    def list_persona_prompts(self) -> list[dict]:
        return self._rows("SELECT * FROM persona_prompts ORDER BY persona_id")

    # ----- queries used by commands / webui -----

    def get_overview(self, persona_id: str, date: Optional[str] = None) -> dict[str, Any]:
        date = date or self._today()
        sessions = self.list_sessions(persona_id, date, limit=20)
        notes = self.list_notes(persona_id, date, limit=20)
        diary = self.get_diary(persona_id, date)
        interests = self.get_interests(persona_id, limit=8)
        snapshots = self.list_state_snapshots(persona_id, since_date=date, limit=100)
        share_logs = self.list_share_log(persona_id, date, limit=50)
        browse_sessions = [s for s in sessions if s.get("kind") != "peek"]
        return {
            "persona_id": persona_id,
            "date": date,
            "diary": diary,
            "sessions": sessions,
            "notes": notes,
            "interests": interests,
            "snapshots": snapshots,
            "share_logs": share_logs,
            "stats": {
                "sessions": len(browse_sessions),
                "notes": len(notes),
                "completed": sum(1 for s in browse_sessions if s["status"] == "completed"),
                "skipped": sum(1 for s in browse_sessions if s["status"].startswith("skipped")),
                "errors": sum(1 for s in browse_sessions if s["status"] in ("error", "failed")),
                "shares_sent": sum(1 for s in share_logs if s["status"] == "sent"),
                "shares_blocked": sum(1 for s in share_logs if s["status"] == "blocked"),
            },
        }

    def get_status(self, persona_id: str, date: Optional[str] = None) -> dict[str, Any]:
        date = date or self._today()
        sessions = self.list_sessions(persona_id, date, limit=20)
        notes = self.list_notes(persona_id, date, limit=5)
        diary = self.get_diary(persona_id, date)
        snapshots = self.list_state_snapshots(persona_id, since_date=date, limit=5)
        latest = snapshots[0] if snapshots else {}
        completed = sum(
            1 for s in sessions if s["status"] == "completed" and s.get("kind") != "peek"
        )
        return {
            "persona_id": persona_id,
            "date": date,
            "mood": latest.get("mood") or (diary.get("mood") if diary else "") or "",
            "energy": latest.get("energy")
            if latest.get("energy") is not None
            else (diary.get("energy") if diary else None),
            "browse_count": completed,
            "notes_count": len(notes),
            "recent_notes": [
                {"id": n["id"], "title": n["title"]} for n in notes[:5]
            ],
            "diary": (
                {
                    "date": diary["date"],
                    "signature": diary.get("signature") or "",
                    "content": diary.get("content") or "",
                }
                if diary
                else None
            ),
            "sessions": [
                {
                    "id": s["id"],
                    "status": s["status"],
                    "reason": s.get("reason") or "",
                }
                for s in sessions[:8]
            ],
        }

    def timeline_heatmap(self, persona_id: str, month: str) -> dict[str, Any]:
        days: dict[str, dict[str, int]] = {}
        default = {"notes": 0, "diaries": 0, "shares": 0, "browse": 0, "peeks": 0}
        prefix = (month or "")[:7] + "%"
        for row in self._rows(
            "SELECT substr(fetched_at, 1, 10) AS d, COUNT(*) AS n "
            "FROM notes WHERE persona_id = ? AND fetched_at LIKE ? AND deleted_at = '' "
            "GROUP BY d",
            (persona_id, prefix),
        ):
            day = days.setdefault(row["d"], dict(default))
            day["notes"] = int(row["n"])
        for row in self._rows(
            "SELECT date AS d, COUNT(*) AS n FROM diary_entries "
            "WHERE persona_id = ? AND date LIKE ? AND deleted_at = '' GROUP BY d",
            (persona_id, prefix),
        ):
            day = days.setdefault(row["d"], dict(default))
            day["diaries"] = int(row["n"])
        for row in self._rows(
            "SELECT substr(attempted_at, 1, 10) AS d, COUNT(*) AS n "
            "FROM share_log WHERE persona_id = ? AND attempted_at LIKE ? GROUP BY d",
            (persona_id, prefix),
        ):
            day = days.setdefault(row["d"], dict(default))
            day["shares"] = int(row["n"])
        for row in self._rows(
            "SELECT substr(started_at, 1, 10) AS d, COUNT(*) AS n "
            "FROM browse_sessions WHERE persona_id = ? AND started_at LIKE ? AND kind != 'peek' GROUP BY d",
            (persona_id, prefix),
        ):
            day = days.setdefault(row["d"], dict(default))
            day["browse"] = int(row["n"])
        for row in self._rows(
            "SELECT substr(started_at, 1, 10) AS d, COUNT(*) AS n "
            "FROM browse_sessions WHERE persona_id = ? AND started_at LIKE ? AND kind = 'peek' GROUP BY d",
            (persona_id, prefix),
        ):
            day = days.setdefault(row["d"], dict(default))
            day["peeks"] = int(row["n"])
        return {
            "persona_id": persona_id,
            "month": (month or "")[:7],
            "days": [{"date": k, **v} for k, v in sorted(days.items())],
        }

    def timeline(
        self,
        persona_id: str,
        types: Optional[Sequence[str]] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Merge notes, diaries, share log and snapshots into a reverse timeline."""
        wanted = set(types or ())
        allowed = {"note", "diary", "share", "snapshot"}
        if wanted and not wanted.issubset(allowed):
            wanted = set()
        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
        window = limit + offset
        items: list[dict[str, Any]] = []
        if not wanted or "note" in wanted:
            for row in self._rows(
                "SELECT * FROM notes WHERE persona_id = ? AND deleted_at = '' "
                "ORDER BY fetched_at DESC LIMIT ?",
                (persona_id, window),
            ):
                items.append({
                    "kind": "note", "ts": row.get("fetched_at") or "",
                    "title": row.get("title") or "", "text": row.get("summary") or "",
                    "source": row.get("source") or "", "url": row.get("url") or "",
                    "id": row.get("id"),
                })
        if not wanted or "diary" in wanted:
            for row in self._rows(
                "SELECT * FROM diary_entries WHERE persona_id = ? AND deleted_at = '' "
                "ORDER BY date DESC LIMIT ?",
                (persona_id, window),
            ):
                items.append({
                    "kind": "diary", "ts": (row.get("date") or "") + " 00:00:00",
                    "title": "日记 " + str(row.get("date") or ""),
                    "text": row.get("content") or "", "source": "",
                    "url": "", "id": row.get("id"), "signature": row.get("signature") or "",
                })
        if not wanted or "share" in wanted:
            for row in self._rows(
                "SELECT * FROM share_log WHERE persona_id = ? "
                "ORDER BY attempted_at DESC LIMIT ?",
                (persona_id, window),
            ):
                items.append({
                    "kind": "share", "ts": row.get("attempted_at") or "",
                    "title": "分享 " + str(row.get("status") or ""),
                    "text": row.get("message") or "", "source": row.get("target_sid") or "",
                    "url": "", "id": row.get("id"), "reason": row.get("reason") or "",
                })
        if not wanted or "snapshot" in wanted:
            for row in self._rows(
                "SELECT * FROM state_snapshots WHERE persona_id = ? "
                "ORDER BY ts DESC LIMIT ?",
                (persona_id, window),
            ):
                items.append({
                    "kind": "snapshot", "ts": row.get("ts") or "",
                    "title": str(row.get("activity") or ""),
                    "text": "", "source": "", "url": "", "id": row.get("id"),
                    "mood": row.get("mood") or "", "energy": row.get("energy"),
                })
        items.sort(key=lambda x: str(x.get("ts") or ""), reverse=True)
        return {"persona_id": persona_id, "items": items[offset:offset + limit], "offset": offset}

    def archive_for_date(self, persona_id: str, date: str) -> dict[str, Any]:
        return {
            "persona_id": persona_id,
            "date": date,
            "diary": self.get_diary(persona_id, date),
            "notes": self.list_notes(persona_id, date, limit=200),
            "sessions": self.list_sessions(persona_id, date, limit=50),
            "snapshots": self.list_state_snapshots(persona_id, since_date=date, limit=200),
            "share_logs": self.list_share_log(persona_id, date, limit=200),
        }

    def memory_overview(self, persona_id: str) -> dict[str, Any]:
        rows = self._rows(
            "SELECT category, COUNT(*) AS n FROM notes WHERE persona_id = ? GROUP BY category ORDER BY n DESC",
            (persona_id,),
        )
        return {
            "persona_id": persona_id,
            "categories": rows,
            "total_notes": sum(int(r["n"]) for r in rows),
            "diary_count": len(self.list_diaries(persona_id, limit=100000)),
        }

    def reset_all(self, persona_id: str) -> None:
        with self._lock:
            for table in (
                "seen_items",
                "state_snapshots",
                "interests",
                "diary_entries",
                "notes",
                "browse_sessions",
                "share_log",
                "daily_usage",
                "change_log",
                "injection_log",
                "life_leases",
                "wishlist",
                "reviews",
                "time_capsules",
                "staging_notes",
                "staging_diary",
                "staging_snapshots",
                "staging_seen",
                "staging_interests",
                "staging_wishlist",
            ):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE persona_id = ?", (persona_id,)
                )
            self._conn.commit()