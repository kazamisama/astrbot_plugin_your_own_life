"""Per-persona life orchestration: browse sessions, shares and nightly diary."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional, Sequence

import httpx

from life.config import LifeConfig
from life.db import LifeDB
from life.esm_adapter import ESMAdapter
from life.fetchers import FetchedItem, USER_AGENT, fetch_all
from life.interests import InterestStore
from life.llm import LLMClient
from life.persona import PersonaService, PersonaUnavailable
from life.prompts import (
    MEMORY_CATEGORIES,
    build_diary_prompt,
    build_select_prompt,
)
from life.timeutil import local_now, local_today

logger = logging.getLogger("your_own_life.browser")


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


@dataclass
class BrowseResult:
    session_id: Optional[int]
    status: str
    notes_count: int = 0
    reason: str = ""
    error: str = ""


class LifeService:
    def __init__(
        self,
        config: LifeConfig,
        db: LifeDB,
        interests: InterestStore,
        esm: ESMAdapter,
        llm: LLMClient,
        personas: PersonaService,
        share_gate: Optional[Any] = None,
        logger: Optional[logging.Logger] = None,
        now_fn: Optional[Callable[[], datetime]] = None,
        fetcher_fn: Optional[Callable[..., Awaitable[list[FetchedItem]]]] = None,
    ):
        self.config = config
        self.db = db
        self.interests = interests
        self.esm = esm
        self.llm = llm
        self.personas = personas
        self.share_gate = share_gate
        self.log = logger or logging.getLogger("your_own_life")
        self.now_fn = now_fn or datetime.now
        self.fetcher_fn = fetcher_fn or fetch_all

    # ----- persona gate -----

    async def _resolve_persona(self, persona_id: str):
        try:
            return await self.personas.resolve(persona_id)
        except PersonaUnavailable as exc:
            self.personas.mark_error(persona_id, str(exc))
            self.log.error("persona %s unavailable, skipping life task: %s", persona_id, exc)
            raise

    # ----- browse -----

    async def run_browse_session(
        self, persona_id: str, trigger: str = "scheduled", force: bool = False
    ) -> BrowseResult:
        if not self.config.enabled:
            return BrowseResult(None, "disabled", 0, "disabled")
        now = local_now(self.config.timezone, self.now_fn())
        if not force and self.config.sleep_window.contains(now):
            return BrowseResult(None, "skipped", 0, "sleep_window")

        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return BrowseResult(None, "skipped", 0, "persona_unavailable")

        energy_before = self.esm.get_energy()
        if not force:
            blocked, energy, reason = self.esm.gate_energy()
            if blocked:
                sid = self.db.start_browse_session(persona_id, trigger, energy, "")
                self.db.finish_browse_session(sid, "skipped_energy", 0, reason)
                self.db.add_state_snapshot(
                    persona_id, "browse_skipped", energy, "",
                    extra=json.dumps({"trigger": trigger}, ensure_ascii=False),
                )
                return BrowseResult(sid, "skipped_energy", 0, reason)

        mood_before = self.esm.get_mood_context(persona_id)
        sid = self.db.start_browse_session(persona_id, trigger, energy_before, mood_before)
        try:
            async with httpx.AsyncClient(
                timeout=self.config.source_timeout,
                headers={"User-Agent": USER_AGENT},
            ) as client:
                queries = self.interests.pick_topics(
                    persona_id,
                    count=3,
                    explore_probability=self.config.explore_probability,
                )
                candidates = await self.fetcher_fn(self.config, client, queries)

            unseen = [
                item for item in candidates
                if not self.db.is_seen(persona_id, item.url_hash)
            ]
            if not unseen:
                self.db.finish_browse_session(sid, "completed", 0, "nothing_new")
                self.db.add_state_snapshot(
                    persona_id, "browse", energy_before, "",
                    extra=json.dumps({"reason": "nothing_new"}, ensure_ascii=False),
                )
                return BrowseResult(sid, "completed", 0, "nothing_new")

            prompt_candidates = [
                {
                    "index": i,
                    "source": item.source,
                    "title": item.title,
                    "url": item.url,
                    "summary": (item.summary or "")[:300],
                }
                for i, item in enumerate(unseen)
            ]
            share_sessions = self.config.share_sessions.get(persona_id, [])
            payload: dict = {}
            fallback = False
            try:
                payload = await self.llm.chat_json(
                    build_select_prompt(
                        persona.system_prompt,
                        persona_id,
                        prompt_candidates,
                        [row["name"] or row["key"] for row in self.db.get_interests(persona_id, limit=5)],
                        self.esm.get_mood_context(persona_id),
                        self.config.notes_min,
                        self.config.notes_max,
                        share_sessions,
                    )
                )
            except Exception as exc:
                self.log.warning("browse LLM failed, using deterministic fallback: %s", exc)
                fallback = True

            selected = self._validate_selected(payload, unseen)
            if not selected:
                selected = self._fallback_selected(unseen)
                fallback = True

            notes_count = 0
            session_mood = str(payload.get("session_mood") or "curious") if payload else "curious"
            for item, meta in selected:
                note_id = self.db.add_note(
                    persona_id,
                    sid,
                    source=item.source,
                    url=item.url,
                    title=item.title,
                    summary=str(meta.get("summary") or item.summary or item.title)[:600],
                    opinion=str(meta.get("opinion") or ""),
                    mood=str(meta.get("mood") or session_mood),
                    interest_level=_clamp(meta.get("interest_level", 0.5)),
                    interest_key=str(meta.get("interest_key") or "uncategorized"),
                    interest_name=str(meta.get("interest_name") or meta.get("interest_key") or "未分类"),
                    category=self._valid_category(meta.get("category")),
                    tags=self._valid_tags(meta.get("tags")),
                    share_decision=self._valid_share(meta.get("share")),
                    url_hash=item.url_hash,
                )
                if note_id is not None:
                    notes_count += 1
                    self.db.mark_seen(persona_id, item.url_hash)
                    self.interests.apply_note(
                        persona_id,
                        str(meta.get("interest_key") or "uncategorized"),
                        str(meta.get("interest_name") or meta.get("interest_key") or "未分类"),
                        _clamp(meta.get("interest_level", 0.5)),
                        now=now,
                    )
                    if self.share_gate is not None:
                        note_row = self.db.get_note(note_id)
                        await self.share_gate.attempt_share(
                            persona_id, note_row, meta.get("share")
                        )

            status = "completed"
            reason = "llm_fallback" if fallback else ""
            self.db.finish_browse_session(sid, status, notes_count, reason)
            self.esm.apply_browse_signal(persona_id, session_mood, intensity=0.3)
            self.db.add_state_snapshot(
                persona_id,
                "browse",
                energy_before,
                session_mood,
                extra=json.dumps(
                    {"trigger": trigger, "reason": reason, "fallback": fallback},
                    ensure_ascii=False,
                ),
            )
            return BrowseResult(sid, status, notes_count, reason)
        except Exception as exc:
            self.log.exception("browse session failed for %s", persona_id)
            self.db.finish_browse_session(sid, "error", 0, "", repr(exc))
            self.db.add_state_snapshot(
                persona_id, "browse_error", energy_before, "",
                extra=json.dumps({"error": repr(exc)}, ensure_ascii=False),
            )
            return BrowseResult(sid, "error", 0, "", repr(exc))

    def _validate_selected(self, payload: Any, candidates: Sequence[FetchedItem]) -> list:
        if not isinstance(payload, dict):
            return []
        selected = payload.get("selected")
        if not isinstance(selected, list):
            return []
        out: list = []
        used: set[int] = set()
        for entry in selected:
            if not isinstance(entry, dict):
                continue
            try:
                index = int(entry.get("index"))
            except (TypeError, ValueError):
                continue
            if index < 0 or index >= len(candidates) or index in used:
                continue
            used.add(index)
            out.append((candidates[index], entry))
            if len(out) >= self.config.notes_max:
                break
        return out

    def _fallback_selected(self, candidates: Sequence[FetchedItem]) -> list:
        out = []
        for item in candidates[: max(1, self.config.notes_min)]:
            out.append((item, {
                "summary": item.summary or item.title,
                "opinion": "",
                "mood": "neutral",
                "interest_level": 0.5,
                "interest_key": "uncategorized",
                "interest_name": "未分类",
                "category": "observation",
                "tags": [],
                "share": {"should_share": False, "reason": "", "target": ""},
            }))
        return out

    def _valid_category(self, raw: Any) -> str:
        value = str(raw or "").strip().lower()
        return value if value in MEMORY_CATEGORIES else "other"

    def _valid_tags(self, raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        out = []
        for tag in raw:
            text = str(tag or "").strip()
            if text and text not in out and len(text) <= 20:
                out.append(text)
            if len(out) >= 5:
                break
        return out

    def _valid_share(self, raw: Any) -> dict:
        if not isinstance(raw, dict):
            return {"should_share": False, "reason": "", "target": ""}
        return {
            "should_share": bool(raw.get("should_share", False)),
            "reason": str(raw.get("reason") or ""),
            "target": str(raw.get("target") or ""),
        }

    # ----- diary -----

    async def run_nightly_diary(self, persona_id: str) -> dict[str, Any]:
        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return {"date": local_today(self.config.timezone, self.now_fn()),
                    "notes": 0, "fallback": True, "skipped": "persona_unavailable"}

        now = local_now(self.config.timezone, self.now_fn())
        date = now.strftime("%Y-%m-%d")
        if self.share_gate is not None:
            await self.share_gate.recheck_pending(persona_id)
        notes = self.db.list_notes(persona_id, date, limit=200)
        snapshots = self.db.list_state_snapshots(persona_id, since_date=date, limit=200)
        mood_context = self.esm.get_mood_context(persona_id)

        payload: dict = {}
        fallback = True
        if notes:
            try:
                payload = await self.llm.chat_json(
                    build_diary_prompt(
                        persona.system_prompt, persona_id, notes, snapshots, mood_context, date
                    )
                )
                if payload.get("diary_text"):
                    fallback = False
            except Exception as exc:
                self.log.warning("diary LLM failed, using fallback: %s", exc)

        if fallback or not payload.get("diary_text"):
            diary_text = self._fallback_diary(notes, date)
            mood = "calm"
        else:
            diary_text = str(payload["diary_text"]).strip()
            mood = str(payload.get("mood") or "calm")

        energy = self.esm.get_energy()
        top = ",".join(
            row["name"] or row["key"] for row in self.db.get_interests(persona_id, limit=5)
        )
        self.db.add_diary(persona_id, date, diary_text, mood, energy, top)
        if notes and not fallback:
            self.interests.apply_updates(persona_id, payload.get("interest_updates") or {}, now=now)
        self.interests.daily_decay(persona_id)
        self.db.add_state_snapshot(
            persona_id,
            "diary",
            energy,
            mood,
            extra=json.dumps({"fallback": fallback, "notes": len(notes)}, ensure_ascii=False),
        )
        return {"date": date, "notes": len(notes), "fallback": fallback}

    def _fallback_diary(self, notes: Sequence[dict], date: str) -> str:
        if not notes:
            return "今天没出门。没有特别的见闻，只是安静地待着。"
        lines = "\n".join(f"- {n['title']}" for n in notes[:5])
        return f"今天在网上逛了一圈，记下了这几件事：\n{lines}\n\n明天继续看看有什么新动静。"