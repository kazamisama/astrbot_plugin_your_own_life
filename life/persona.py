"""Per-persona system prompt resolution and cache."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from life.db import LifeDB


class PersonaUnavailable(RuntimeError):
    pass


@dataclass
class PersonaPrompt:
    persona_id: str
    system_prompt: str
    source: str = ""
    status: str = "ok"
    error: str = ""


class PersonaService:
    """Resolves each whitelisted persona's system_prompt and caches it."""

    def __init__(
        self,
        context: Any,
        db: LifeDB,
        config: Any,
        logger: Optional[logging.Logger] = None,
    ):
        self.context = context
        self.db = db
        self.config = config
        self.log = logger or logging.getLogger("your_own_life.persona")

    def _is_stale(self, row: Optional[dict]) -> bool:
        if not row or not row.get("system_prompt"):
            return True
        fetched = row.get("fetched_at") or ""
        try:
            fetched_dt = datetime.strptime(fetched, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return True
        hours = float(self.config.persona_cache_hours or 24.0)
        return datetime.now() - fetched_dt > timedelta(hours=hours)

    async def ensure_fresh(self, persona_id: str) -> None:
        row = self.db.get_persona_prompt(persona_id)
        if row and row.get("status") == "ok" and not self._is_stale(row):
            return
        await self.refresh(persona_id)

    async def refresh(self, persona_id: str) -> PersonaPrompt:
        prompt, source = await self._fetch(persona_id)
        max_chars = int(getattr(self.config, "persona_prompt_max_chars", 6000) or 6000)
        truncated = (prompt or "")[:max_chars]
        self.db.upsert_persona_prompt(persona_id, truncated, source, "ok", "")
        return PersonaPrompt(persona_id, truncated, source, "ok")

    async def resolve(self, persona_id: str) -> PersonaPrompt:
        try:
            await self.ensure_fresh(persona_id)
        except PersonaUnavailable:
            raise
        except Exception as exc:
            raise PersonaUnavailable(f"persona resolve error: {exc}") from exc
        row = self.db.get_persona_prompt(persona_id)
        if not row or not row.get("system_prompt"):
            raise PersonaUnavailable(f"system_prompt for {persona_id} unavailable")
        return PersonaPrompt(
            persona_id,
            row["system_prompt"],
            row.get("source") or "",
            row.get("status") or "ok",
            row.get("error") or "",
        )

    def mark_error(self, persona_id: str, error: str) -> None:
        self.db.upsert_persona_prompt(persona_id, "", "", "error", str(error))

    def get_cached(self, persona_id: str) -> Optional[dict]:
        return self.db.get_persona_prompt(persona_id)

    def list_cache(self) -> list[dict]:
        return self.db.list_persona_prompts()

    async def _fetch(self, persona_id: str) -> tuple[str, str]:
        persona_mgr = getattr(self.context, "persona_manager", None)
        if persona_mgr is None:
            raise PersonaUnavailable("persona_manager missing")

        get_persona = getattr(persona_mgr, "get_persona", None)
        if get_persona:
            try:
                persona = await get_persona(persona_id)
                prompt = getattr(persona, "system_prompt", None) if persona else None
                if prompt:
                    return str(prompt), "persona"
            except Exception as exc:
                self.log.debug("get_persona(%s) failed: %s", persona_id, exc)

        default_fn = getattr(persona_mgr, "get_default_persona_v3", None)
        if default_fn:
            try:
                default = await default_fn(umo="")
                if isinstance(default, dict):
                    prompt = default.get("prompt")
                    name = default.get("name") or "default"
                    if prompt and (persona_id == "default" or persona_id == name):
                        return str(prompt), "default-persona"
                elif default is not None:
                    prompt = getattr(default, "prompt", None) or getattr(
                        default, "system_prompt", None
                    )
                    name = getattr(default, "name", "") or "default"
                    if prompt and (persona_id == "default" or persona_id == name):
                        return str(prompt), "default-persona"
            except Exception as exc:
                self.log.debug("default persona failed: %s", exc)

        raise PersonaUnavailable(f"system_prompt for {persona_id} unavailable")