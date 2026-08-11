"""Per-persona SQLite storage for the internet-life archive."""
from __future__ import annotations

import json
import sqlite3
import threading
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
    UNIQUE(persona_id, url_hash)
);
CREATE TABLE IF NOT EXISTS diary_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    date TEXT NOT NULL,
    content TEXT NOT NULL,
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
CREATE TABLE IF NOT EXISTS staging_seen (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    persona_id TEXT NOT NULL DEFAULT 'default',
    session_id INTEGER,
    url_hash TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
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
    PRIMARY KEY (persona_id, date)
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
    ) -> int:
        cur = self._execute(
            "INSERT INTO browse_sessions (persona_id, started_at, trigger, status, energy_before, mood_before) "
            "VALUES (?, ?, ?, 'running', ?, ?)",
            (persona_id, self._now(), trigger, energy_before, mood_before),
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
    ) -> None:
        self._execute(
            "INSERT INTO diary_entries (persona_id, date, content, mood, energy, interest_top, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(persona_id, date) DO UPDATE SET content = excluded.content, mood = excluded.mood, "
            "energy = excluded.energy, interest_top = excluded.interest_top",
            (persona_id, date, content, mood, energy, interest_top, self._now()),
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
    ) -> int:
        cur = self._execute(
            "INSERT INTO staging_diary "
            "(persona_id, session_id, date, content, mood, energy, interest_top, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (persona_id, session_id, date, content, mood, energy, interest_top, self._now()),
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
                "(persona_id, date, content, mood, energy, interest_top, created_at) "
                "SELECT persona_id, date, content, mood, energy, interest_top, created_at "
                "FROM staging_diary WHERE persona_id = ? AND "
                "(session_id = ? OR (session_id IS NULL AND ? IS NULL)) "
                "ON CONFLICT(persona_id, date) DO UPDATE SET content = excluded.content, mood = excluded.mood, "
                "energy = excluded.energy, interest_top = excluded.interest_top",
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
        return len(rows)

    def _delete_staging(self, persona_id: str, session_id: Optional[int]) -> None:
        for table in ("staging_notes", "staging_diary", "staging_snapshots",
                      "staging_seen", "staging_interests"):
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
        return int(cur.lastrowid)

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
                "sessions": len(sessions),
                "notes": len(notes),
                "completed": sum(1 for s in sessions if s["status"] == "completed"),
                "skipped": sum(1 for s in sessions if s["status"].startswith("skipped")),
                "errors": sum(1 for s in sessions if s["status"] in ("error", "failed")),
                "shares_sent": sum(1 for s in share_logs if s["status"] == "sent"),
                "shares_blocked": sum(1 for s in share_logs if s["status"] == "blocked"),
            },
        }

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
                "staging_notes",
                "staging_diary",
                "staging_snapshots",
                "staging_seen",
                "staging_interests",
            ):
                self._conn.execute(
                    f"DELETE FROM {table} WHERE persona_id = ?", (persona_id,)
                )
            self._conn.commit()