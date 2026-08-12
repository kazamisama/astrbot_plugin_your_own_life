"""Unified memory host adapter - the only place this plugin touches engram_core."""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("your_own_life.memory")

ENGRAM_HOST_ID = "astrbot_plugin_engram_core"


class MemoryHostError(RuntimeError):
    """Raised when the configured unified memory host is unavailable."""


class LifeMemoryAdapter:
    """v2 hard-dependency adapter: host missing raises, no silent fallback."""

    def __init__(self, context: Any, host_id: str = ENGRAM_HOST_ID):
        self.context = context
        self.host_id = host_id or ENGRAM_HOST_ID

    def _host(self) -> Any:
        getter = getattr(self.context, "get_registered_star", None)
        if getter is None:
            raise MemoryHostError("context has no get_registered_star")
        try:
            star = getter(self.host_id)
        except Exception as exc:
            raise MemoryHostError(f"memory host lookup failed: {exc}") from None
        if star is None:
            raise MemoryHostError(f"memory host {self.host_id} not registered")
        return star

    @staticmethod
    def _require_method(star: Any, name: str) -> Any:
        fn = getattr(star, name, None)
        if fn is None:
            raise MemoryHostError(f"memory host {name}() missing")
        return fn

    def available(self) -> bool:
        try:
            return self._host() is not None
        except MemoryHostError:
            return False

    # ----- diary / note / event writes -----

    def store_diary_line(self, persona_id: str, date: str, content: str, *,
                         mood: str = "", signature: str = "",
                         source_refs: Optional[list] = None) -> str:
        fn = self._require_method(self._host(), "store_diary_line")
        return fn(persona_id, date, content, mood=mood, signature=signature,
                  source_refs=source_refs or [], source="your_own_life")

    def add_note(self, persona_id: str, note: dict) -> str:
        fn = self._require_method(self._host(), "add_note")
        return fn(persona_id, note, source="your_own_life")

    def store_event(self, persona_id: str, platform: str, session_id: str,
                    ts: float, kind: str, payload: Optional[dict] = None) -> str:
        fn = self._require_method(self._host(), "store_event")
        return fn(persona_id, platform, session_id, ts, kind,
                  payload=payload or {}, source="your_own_life")

    # ----- recall -----

    def query_recent_memory(self, persona_id: str, query: str = "",
                            k: int = 5, since: float = 0.0) -> list:
        fn = self._require_method(self._host(), "query_recent_memory")
        return fn(persona_id, query=query, k=k, since=since)

    def query_memory(self, persona_id: str, query: str, k: int = 5,
                     memory_types: Optional[list] = None) -> list:
        fn = self._require_method(self._host(), "query_memory")
        return fn(persona_id, query, k=k, memory_types=memory_types)

    def search(self, persona_id: str, query: str, k: int = 5,
               memory_types: Optional[list] = None) -> list:
        fn = self._require_method(self._host(), "search")
        return fn(persona_id, query, k=k, memory_types=memory_types)

    # ----- entity graph -----

    def upsert_entity(self, persona_id: str, entity: dict) -> str:
        fn = self._require_method(self._host(), "upsert_entity")
        return fn(persona_id, entity)

    def link_entities(self, persona_id: str, src_entity_id: str,
                      relation: str, dst_entity_id: str,
                      weight: float = 1.0) -> bool:
        fn = self._require_method(self._host(), "link_entities")
        return fn(persona_id, src_entity_id, relation, dst_entity_id,
                  weight=weight)

    def list_entities(self, persona_id: str, limit: int = 500) -> list:
        fn = self._require_method(self._host(), "list_entities")
        return fn(persona_id, limit=limit)

    def list_links(self, persona_id: str, limit: int = 1000) -> list:
        fn = self._require_method(self._host(), "list_links")
        return fn(persona_id, limit=limit)

    # ----- task leases -----

    def claim_task(self, persona_id: str, task_kind: str,
                   holder: str, ttl_seconds: int = 300) -> bool:
        fn = self._require_method(self._host(), "claim_task")
        return fn(persona_id, task_kind, holder=holder,
                  ttl_seconds=ttl_seconds)

    def renew_task(self, persona_id: str, task_kind: str,
                   holder: str, ttl_seconds: int = 300) -> bool:
        fn = self._require_method(self._host(), "renew_task")
        return fn(persona_id, task_kind, holder=holder,
                  ttl_seconds=ttl_seconds)

    def release_task(self, persona_id: str, task_kind: str,
                     holder: str) -> bool:
        fn = self._require_method(self._host(), "release_task")
        return fn(persona_id, task_kind, holder=holder)

    def task_lease_owner(self, persona_id: str, task_kind: str) -> str:
        fn = self._require_method(self._host(), "task_lease_owner")
        return fn(persona_id, task_kind)
