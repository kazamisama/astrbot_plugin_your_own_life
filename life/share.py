"""ShareGate: decides whether an insight becomes an outbound message."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional

from life.config import LifeConfig
from life.db import LifeDB
from life.esm_adapter import ESMAdapter
from life.llm import LLMClient
from life.persona import PersonaService, PersonaUnavailable
from life.prompts import build_share_prompt


@dataclass
class ShareResult:
    status: str  # sent / blocked / not_triggered / error
    reason: str = ""


class ShareGate:
    def __init__(
        self,
        config: LifeConfig,
        db: LifeDB,
        esm: ESMAdapter,
        llm: LLMClient,
        personas: PersonaService,
        sender: Callable[[str, str], Awaitable[bool]],
        logger: Optional[logging.Logger] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
    ):
        self.config = config
        self.db = db
        self.esm = esm
        self.llm = llm
        self.personas = personas
        self.sender = sender
        self.log = logger or logging.getLogger("your_own_life.share")
        self.now_fn = now_fn or datetime.now

    async def attempt_share(
        self, persona_id: str, note: dict, decision: Any
    ) -> ShareResult:
        if not isinstance(decision, dict) or not decision.get("should_share"):
            return ShareResult("not_triggered", "")
        note_id = note.get("id")
        target = str(decision.get("target") or "").strip()
        valid = self.config.share_sessions.get(persona_id, [])

        if not self.config.share_enabled:
            self.db.update_note_share_status(note_id, "dropped")
            self.db.log_share_attempt(persona_id, note_id, "blocked", "share_disabled", target)
            return ShareResult("blocked", "share_disabled")
        if target not in valid:
            self.db.update_note_share_status(note_id, "dropped")
            self.db.log_share_attempt(persona_id, note_id, "blocked", "invalid_target", target)
            return ShareResult("blocked", "invalid_target")

        now = self.now_fn()
        if self.config.sleep_window.contains(now):
            self.db.log_share_attempt(persona_id, note_id, "blocked", "sleep_window", target)
            return ShareResult("blocked", "sleep_window")

        energy = self.esm.get_energy()
        if energy is not None and energy < self.config.energy_gate:
            self.db.log_share_attempt(persona_id, note_id, "blocked", "energy_gate", target)
            return ShareResult("blocked", "energy_gate")

        date = now.strftime("%Y-%m-%d")
        if self.db.count_share_success(persona_id, date) >= self.config.share_daily_cap:
            self.db.log_share_attempt(persona_id, note_id, "blocked", "daily_cap", target)
            return ShareResult("blocked", "daily_cap")

        last = self.db.last_share_success(persona_id, target)
        if last:
            try:
                last_dt = datetime.strptime(last["attempted_at"], "%Y-%m-%d %H:%M:%S")
                cooldown = self.config.share_cooldown_minutes * 60
                if (now - last_dt).total_seconds() < cooldown:
                    self.db.log_share_attempt(persona_id, note_id, "blocked", "cooldown", target)
                    return ShareResult("blocked", "cooldown")
            except ValueError:
                pass

        url_hash = note.get("url_hash") or ""
        if url_hash and url_hash in self.db.shared_url_hashes_since(persona_id, 24):
            self.db.update_note_share_status(note_id, "dropped")
            self.db.log_share_attempt(persona_id, note_id, "blocked", "duplicate", target)
            return ShareResult("blocked", "duplicate")

        message = await self._render_message(persona_id, note, target)
        if not message:
            self.db.log_share_attempt(persona_id, note_id, "error", "render_failed", target)
            return ShareResult("error", "render_failed")
        try:
            sent = await self.sender(target, message)
        except Exception as exc:
            self.log.warning("share send failed: %s", exc)
            self.db.log_share_attempt(persona_id, note_id, "error", f"send_error: {exc}", target, message)
            return ShareResult("error", "send_error")

        if not sent:
            self.db.log_share_attempt(persona_id, note_id, "error", "send_rejected", target, message)
            return ShareResult("error", "send_rejected")

        self.db.update_note_share_status(note_id, "shared")
        self.db.log_share_attempt(persona_id, note_id, "sent", "", target, message)
        self.esm.apply_self_reply_signal(persona_id)
        return ShareResult("sent", "")

    async def recheck_pending(self, persona_id: str) -> int:
        notes = self.db.pending_share_notes(persona_id, limit=50)
        sent = 0
        for note in notes:
            try:
                decision = json.loads(note.get("share_decision") or "{}")
            except (ValueError, TypeError):
                continue
            result = await self.attempt_share(persona_id, note, decision)
            if result.status == "sent":
                sent += 1
        return sent

    async def _render_message(self, persona_id: str, note: dict, target: str) -> str:
        try:
            persona = await self.personas.resolve(persona_id)
            persona_prompt = persona.system_prompt
        except PersonaUnavailable:
            persona_prompt = f"你是名为 {persona_id} 的 Bot。"
        fallback = str(note.get("title") or "").strip()
        if self.config.share_include_link and note.get("url"):
            fallback = f"{fallback} {note['url']}".strip()
        fallback = fallback[: self.config.share_max_chars]
        try:
            payload = await self.llm.chat_json(
                build_share_prompt(
                    persona_prompt,
                    persona_id,
                    note,
                    target,
                    max_chars=self.config.share_max_chars,
                    include_link=self.config.share_include_link,
                )
            )
            message = str(payload.get("message") or "").strip()
            return message[: self.config.share_max_chars] or fallback
        except Exception as exc:
            self.log.debug("share render failed, using fallback: %s", exc)
            return fallback