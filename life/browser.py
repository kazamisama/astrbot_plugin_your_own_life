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
from life.injection import is_suspicious, sanitize_text
from life.interests import InterestStore
from life.llm import BudgetExhausted, LLMClient, LLMError
from life.persona import PersonaService, PersonaUnavailable
from life.prompts import (
    MEMORY_CATEGORIES,
    build_diary_prompt,
    build_select_prompt,
)
from life.timeutil import local_now, local_today

logger = logging.getLogger("your_own_life.browser")

VALID_MOODS = {"curious", "calm", "excited", "tired", "skeptical"}


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

    def record_skipped_duplicate(
        self, persona_id: str, kind: str, slot: Optional[datetime] = None
    ) -> None:
        extra = json.dumps(
            {
                "reason": "skipped_duplicate",
                "slot": slot.strftime("%Y-%m-%d %H:%M") if slot else "",
            },
            ensure_ascii=False,
        )
        if kind == "browse":
            sid = self.db.start_browse_session(persona_id, "scheduled")
            self.db.finish_browse_session(sid, "skipped", 0, "skipped_duplicate")
            self.db.add_state_snapshot(persona_id, "browse_skipped", extra=extra)
        else:
            self.db.add_state_snapshot(persona_id, "diary_skipped", extra=extra)

    async def _llm_call(self, persona_id: str, prompt: str) -> dict:
        """Budget-checked, retried LLM call with daily usage accounting."""
        date = local_today(self.config.timezone, self.now_fn())
        usage = self.db.get_daily_usage(persona_id, date)
        calls = int(usage["llm_calls"] or 0) if usage else 0
        tokens = int(usage["tokens"] or 0) if usage else 0

        def check_budget() -> None:
            nonlocal calls, tokens
            limit = int(self.config.daily_llm_call_limit or 0)
            if limit > 0 and calls >= limit:
                raise BudgetExhausted(f"daily_llm_call_limit={limit}")
            token_budget = int(self.config.daily_token_budget or 0)
            if token_budget > 0 and tokens >= token_budget:
                raise BudgetExhausted(f"daily_token_budget={token_budget}")

        def record_usage(tokens_used: Optional[int]) -> None:
            nonlocal calls, tokens
            calls += 1
            tokens += int(tokens_used or 0)
            self.db.increment_llm_usage(
                persona_id, date, calls=1, tokens=int(tokens_used or 0)
            )

        return await self.llm.chat_json_managed(
            prompt,
            retry_limit=int(self.config.llm_retry_limit or 3),
            can_call=check_budget,
            on_usage=record_usage,
        )

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

            if self.config.injection_log_enabled:
                for item in unseen:
                    for field in ("title", "summary"):
                        value = getattr(item, field, None)
                        if is_suspicious(value):
                            self.db.log_injection(
                                persona_id, source=item.source, context="browse",
                                field=field, preview=str(value)[:200],
                            )

            prompt_candidates = [
                {
                    "index": i,
                    "source": item.source,
                    "title": sanitize_text(item.title, 300),
                    "url": item.url,
                    "summary": sanitize_text(item.summary, 300),
                }
                for i, item in enumerate(unseen)
            ]
            share_sessions = self.config.share_sessions.get(persona_id, [])
            try:
                payload = await self._llm_call(
                    persona_id,
                    build_select_prompt(
                        persona.system_prompt,
                        persona_id,
                        prompt_candidates,
                        [row["name"] or row["key"] for row in self.db.get_interests(persona_id, limit=5)],
                        self.esm.get_mood_context(persona_id),
                        self.config.notes_min,
                        self.config.notes_max,
                        share_sessions,
                    ),
                )
            except BudgetExhausted as exc:
                self.log.warning("browse budget exhausted for %s: %s", persona_id, exc)
                self.db.finish_browse_session(
                    sid, "skipped", 0, "budget_exhausted", repr(exc)
                )
                self.db.add_state_snapshot(
                    persona_id, "browse_skipped", energy_before, "",
                    extra=json.dumps(
                        {"trigger": trigger, "reason": "budget_exhausted"},
                        ensure_ascii=False,
                    ),
                )
                return BrowseResult(sid, "skipped", 0, "budget_exhausted", repr(exc))

            selected = self._validate_selected(payload, unseen)
            if not selected:
                raise LLMError("LLM 未返回有效短记选择")

            session_mood = self._valid_mood(payload.get("session_mood"))
            for item, meta in selected:
                key = str(meta.get("interest_key") or "uncategorized")
                name = str(meta.get("interest_name") or key)
                self.db.stage_note(
                    persona_id,
                    sid,
                    source=item.source,
                    url=item.url,
                    title=sanitize_text(item.title, 300),
                    summary=sanitize_text(meta.get("summary") or item.summary or item.title, 600),
                    opinion=sanitize_text(meta.get("opinion"), 600),
                    mood=self._valid_mood(meta.get("mood"), session_mood),
                    interest_level=_clamp(meta.get("interest_level", 0.5)),
                    interest_key=key,
                    interest_name=name,
                    category=self._valid_category(meta.get("category")),
                    tags=self._valid_tags(meta.get("tags")),
                    share_decision=self._valid_share(meta.get("share")),
                    url_hash=item.url_hash,
                )
                self.db.stage_seen(persona_id, sid, item.url_hash)
                self.interests.stage_note(
                    persona_id, sid, key, name,
                    _clamp(meta.get("interest_level", 0.5)), now=now,
                )
            self.db.stage_snapshot(
                persona_id, sid, "browse", energy_before, session_mood,
                extra=json.dumps({"trigger": trigger}, ensure_ascii=False),
            )
            notes = self.db.commit_staged(
                persona_id, sid, status="completed",
                notes_count=len(selected), reason="",
            )
            try:
                self.esm.apply_browse_signal(persona_id, session_mood, intensity=0.3)
            except Exception as exc:
                self.log.warning("browse signal failed for %s: %s", persona_id, exc)
            for note in notes:
                try:
                    decision = json.loads(note.get("share_decision") or "{}")
                except (ValueError, TypeError):
                    decision = {}
                if self.share_gate is not None and decision.get("should_share"):
                    try:
                        await self.share_gate.attempt_share(persona_id, note, decision)
                    except Exception as exc:
                        self.log.warning("share attempt failed for note %s: %s", note.get("id"), exc)
            return BrowseResult(sid, "completed", len(notes), "")
        except Exception as exc:
            self.log.exception("browse session failed for %s", persona_id)
            self.db.discard_staged(persona_id, sid, repr(exc))
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

    def _valid_mood(self, raw: Any, default: str = "curious") -> str:
        value = str(raw or "").strip().lower()
        return value if value in VALID_MOODS else default

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
                    "notes": 0, "fallback": False, "skipped": "persona_unavailable"}

        now = local_now(self.config.timezone, self.now_fn())
        date = now.strftime("%Y-%m-%d")
        notes: list[dict] = []
        try:
            if self.share_gate is not None:
                await self.share_gate.recheck_pending(persona_id)
            notes = self.db.list_notes(persona_id, date, limit=200)
            snapshots = self.db.list_state_snapshots(persona_id, since_date=date, limit=200)
            mood_context = self.esm.get_mood_context(persona_id)

            if self.config.injection_log_enabled:
                for note in notes:
                    for field in ("title", "summary", "opinion"):
                        value = note.get(field)
                        if is_suspicious(value):
                            self.db.log_injection(
                                persona_id, source=note.get("source") or "memory",
                                context="diary", field=field, preview=str(value)[:200],
                            )

            if not notes:
                diary_text = "今天没出门。没有特别的见闻，只是安静地待着。"
                mood = "calm"
                interest_updates: dict = {}
            else:
                safe_notes = [
                    {
                        **note,
                        "title": sanitize_text(note.get("title"), 300),
                        "summary": sanitize_text(note.get("summary"), 600),
                        "opinion": sanitize_text(note.get("opinion"), 600),
                    }
                    for note in notes
                ]
                try:
                    payload = await self._llm_call(
                        persona_id,
                        build_diary_prompt(
                            persona.system_prompt, persona_id, safe_notes, snapshots, mood_context, date
                        ),
                    )
                except BudgetExhausted as exc:
                    self.log.warning("diary budget exhausted for %s: %s", persona_id, exc)
                    self.db.add_state_snapshot(
                        persona_id, "diary_skipped", self.esm.get_energy(), "",
                        extra=json.dumps(
                            {"reason": "budget_exhausted", "notes": len(notes)},
                            ensure_ascii=False,
                        ),
                    )
                    return {"date": date, "notes": len(notes), "fallback": False,
                            "skipped": "budget_exhausted"}
                if not payload.get("diary_text"):
                    raise LLMError("diary LLM 未返回日记正文")
                diary_text = str(payload["diary_text"]).strip()
                mood = self._valid_mood(payload.get("mood"), "calm")
                interest_updates = payload.get("interest_updates") or {}

            energy = self.esm.get_energy()
            top = ",".join(
                row["name"] or row["key"] for row in self.db.get_interests(persona_id, limit=5)
            )
            self.db.stage_diary(persona_id, None, date, diary_text, mood, energy, top)
            self.db.stage_snapshot(
                persona_id, None, "diary", energy, mood,
                extra=json.dumps({"notes": len(notes)}, ensure_ascii=False),
            )
            if notes and interest_updates:
                self.interests.stage_updates(persona_id, None, interest_updates, now=now)
            self.db.commit_staged(persona_id, None, status="completed")
            self.interests.daily_decay(persona_id)
            return {"date": date, "notes": len(notes), "fallback": False}
        except Exception as exc:
            self.log.exception("nightly diary failed for %s", persona_id)
            self.db.discard_staged(persona_id, None, repr(exc))
            self.db.add_state_snapshot(
                persona_id, "diary_error", self.esm.get_energy(), "",
                extra=json.dumps({"error": repr(exc), "notes": len(notes)}, ensure_ascii=False),
            )
            return {"date": date, "notes": len(notes), "fallback": False, "error": repr(exc)}