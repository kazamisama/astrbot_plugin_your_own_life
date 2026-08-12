"""Per-persona life orchestration: browse sessions, shares and nightly diary."""
from __future__ import annotations

import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional, Sequence

import httpx

from life.config import LifeConfig, current_time_slot
from life.db import LifeDB
from life.esm_adapter import ESMAdapter
from life.fetchers import FetchedItem, USER_AGENT, fetch_all
from life.injection import is_suspicious, sanitize_text
from life.interests import InterestStore
from life.llm import BudgetExhausted, LLMClient, LLMError
from life.memory_adapter import LifeMemoryAdapter, MemoryHostError
from life.persona import PersonaService, PersonaUnavailable
from life.prompts import (
    MEMORY_CATEGORIES,
    PLAN_ACTION_VOCABULARY,
    build_diary_prompt,
    build_plan_prompt,
    build_review_prompt,
    build_select_prompt,
    build_wishlist_eval_prompt,
)
from life.timeutil import local_now, local_today

logger = logging.getLogger("your_own_life.browser")

VALID_MOODS = {"curious", "calm", "excited", "tired", "skeptical"}

ENERGY_COST_BROWSE = 0.15
ENERGY_COST_DIARY = 0.2


def _clamp(value: Any, low: float = 0.0, high: float = 1.0) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return low


def _first_topic(raw: str) -> str:
    for part in str(raw or "").split(","):
        part = part.strip()
        if part:
            return part
    return "未记录"


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
        memory: Optional[LifeMemoryAdapter] = None,
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
        self.memory = memory
        self.log = logger or logging.getLogger("your_own_life")
        self.now_fn = now_fn or datetime.now
        self.fetcher_fn = fetcher_fn or fetch_all
        self.rng = random.Random()

    # ----- persona gate -----

    async def _resolve_persona(self, persona_id: str):
        try:
            return await self.personas.resolve(persona_id)
        except PersonaUnavailable as exc:
            self.personas.mark_error(persona_id, str(exc))
            self.log.error("persona %s unavailable, skipping life task: %s", persona_id, exc)
            raise

    # ----- energy budget -----

    def _energy_used(self, persona_id: str, date: str) -> float:
        row = self.db.get_daily_usage(persona_id, date)
        return float(row["energy_used"] or 0) if row else 0.0

    def _energy_budget_exhausted(self, persona_id: str, date: str) -> bool:
        budget = float(self.config.energy_budget or 0)
        if budget <= 0:
            return False
        return self._energy_used(persona_id, date) >= budget

    def _consume_energy(self, persona_id: str, amount: float,
                        reason: str) -> tuple[Optional[float], str]:
        """Consume energy via ESM and mirror into local daily usage.

        Returns (remaining, mode); mode is "esm" or "local_estimate".
        """
        remaining = self.esm.consume_energy(persona_id, amount, reason)
        date = local_today(self.config.timezone, self.now_fn())
        self.db.increment_energy_usage(persona_id, date, amount)
        if remaining is None:
            self.log.warning(
                "ESM consume_energy unavailable for %s; recorded local estimate %s",
                persona_id, amount,
            )
            return None, "local_estimate"
        return remaining, "esm"

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
        elif kind == "review":
            self.db.add_state_snapshot(persona_id, "review_skipped", extra=extra)
        else:
            self.db.add_state_snapshot(persona_id, "diary_skipped", extra=extra)
        slot_key = slot.strftime("%Y-%m-%d %H:%M") if slot else None
        self.db.append_event(
            persona_id,
            "change",
            {"entity": "task", "kind": kind, "action": "skip",
             "reason": "skipped_duplicate", "slot": slot_key or ""},
            [],
            f"task/{kind}/{slot_key}" if slot_key else None,
        )

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
        if not force and trigger == "scheduled" and self.config.rest_probability > 0:
            if self.rng.random() < self.config.rest_probability:
                self.db.add_state_snapshot(
                    persona_id, "skipped_rest", self.esm.get_energy(persona_id), "",
                    extra=json.dumps({"trigger": trigger}, ensure_ascii=False),
                )
                return BrowseResult(None, "rest", 0, "rest_probability")

        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return BrowseResult(None, "skipped", 0, "persona_unavailable")

        date = local_today(self.config.timezone, self.now_fn())
        if self._energy_budget_exhausted(persona_id, date):
            sid = self.db.start_browse_session(persona_id, trigger, None, "")
            self.db.finish_browse_session(sid, "skipped", 0, "energy_budget_exhausted")
            self.db.add_state_snapshot(
                persona_id, "browse_skipped", None, "",
                extra=json.dumps(
                    {"trigger": trigger, "reason": "energy_budget_exhausted"},
                    ensure_ascii=False,
                ),
            )
            self.db.append_event(
                persona_id, "change",
                {"entity": "task", "kind": "browse", "action": "skip",
                 "reason": "energy_budget_exhausted", "slot": ""},
                [],
                f"task/browse/{date}/energy_budget_exhausted",
            )
            return BrowseResult(sid, "skipped", 0, "energy_budget_exhausted")

        energy_before = self.esm.get_energy(persona_id)
        if not force:
            blocked, energy, reason = self.esm.gate_energy(persona_id)
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
                self.db.append_event(
                    persona_id, "observe",
                    {"entity": "browse", "session_id": sid, "notes_count": 0,
                     "reason": "nothing_new"},
                    [],
                    f"session/{sid}/observe",
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
                        time_slot=self.config.time_slots.get(
                            current_time_slot(self.config.time_slots, now), {}
                        ),
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
            if self.memory is not None and self.config.memory_host:
                try:
                    for item, meta in selected:
                        self.memory.add_note(
                            persona_id,
                            {
                                "summary": sanitize_text(
                                    meta.get("summary") or item.summary or item.title, 600),
                                "opinion": sanitize_text(meta.get("opinion"), 600),
                                "url": item.url,
                                "url_hash": item.url_hash,
                                "category": self._valid_category(meta.get("category")),
                                "tags": self._valid_tags(meta.get("tags")),
                                "importance": _clamp(meta.get("interest_level", 0.5)),
                            },
                        )
                except MemoryHostError as exc:
                    self.log.error(
                        "browse unified memory write failed for %s: %s",
                        persona_id, exc,
                    )
                    self.db.discard_staged(persona_id, sid, f"memory_host: {exc}")
                    self.db.add_state_snapshot(
                        persona_id, "browse_error", energy_before, "",
                        extra=json.dumps(
                            {"error": f"memory_host: {exc}"}, ensure_ascii=False
                        ),
                    )
                    return BrowseResult(sid, "error", 0, "", f"memory_host: {exc}")
            self.db.stage_snapshot(
                persona_id, sid, "browse", energy_before, session_mood,
                extra=json.dumps({"trigger": trigger}, ensure_ascii=False),
            )
            notes = self.db.commit_staged(
                persona_id, sid, status="completed",
                notes_count=len(selected), reason="",
            )
            note_refs = [
                {"note_id": note["id"], "url": note.get("url") or ""}
                for note in notes
            ]
            self.db.append_event(
                persona_id, "observe",
                {"entity": "browse", "session_id": sid, "notes_count": len(notes)},
                note_refs,
                f"session/{sid}/observe",
            )
            self.db.append_event(
                persona_id, "change",
                {"entity": "note", "session_id": sid,
                 "note_ids": [note["id"] for note in notes]},
                note_refs,
                f"session/{sid}/commit",
            )
            if self.memory is not None and self.config.memory_host:
                try:
                    self.memory.store_event(
                        persona_id, "internet-life", str(sid), now.timestamp(),
                        "observe",
                        {"entity": "browse", "session_id": sid,
                         "notes_count": len(notes)},
                    )
                    self.memory.store_event(
                        persona_id, "internet-life", str(sid), now.timestamp(),
                        "change",
                        {"entity": "note", "session_id": sid,
                         "note_ids": [note["id"] for note in notes]},
                    )
                except MemoryHostError as exc:
                    self.log.warning(
                        "browse event mirror failed for %s: %s", persona_id, exc
                    )
            if self.memory is not None and self.config.memory_host:
                try:
                    platform_ids: dict[str, str] = {}
                    for note in notes:
                        src = str(note.get("source") or "").strip()
                        url = str(note.get("url") or "").strip()
                        if src and src not in platform_ids:
                            platform_ids[src] = self.memory.upsert_entity(
                                persona_id,
                                {"dimension": "platform", "entity_id": src,
                                 "name": src, "canonical_url": ""},
                            )
                        if url:
                            url_ent = self.memory.upsert_entity(
                                persona_id,
                                {"dimension": "url",
                                 "entity_id": str(note.get("url_hash") or url),
                                 "name": str(note.get("title") or "")[:120] or url,
                                 "canonical_url": url},
                            )
                            if src and url_ent and platform_ids.get(src):
                                self.memory.link_entities(
                                    persona_id, url_ent, "appears_on",
                                    platform_ids[src], weight=1.0,
                                )
                except MemoryHostError as exc:
                    self.log.warning(
                        "entity sync failed for %s: %s", persona_id, exc
                    )
            _, energy_mode = self._consume_energy(
                persona_id, ENERGY_COST_BROWSE, "internet_life:browse"
            )
            if energy_mode == "local_estimate":
                self.db.add_state_snapshot(
                    persona_id, "browse_energy_fallback", energy_before, session_mood,
                    extra=json.dumps(
                        {"trigger": trigger, "energy_mode": "local_estimate"},
                        ensure_ascii=False,
                    ),
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

    async def run_peek(self, persona_id: str) -> BrowseResult:
        if not self.config.enabled:
            return BrowseResult(None, "disabled", 0, "disabled")
        now = local_now(self.config.timezone, self.now_fn())
        date = now.strftime("%Y-%m-%d")
        if self.config.peek_daily_cap > 0:
            done = self.db.count_sessions_by_kind(persona_id, date, "peek")
            if done >= self.config.peek_daily_cap:
                return BrowseResult(None, "skipped", 0, "peek_daily_cap")
        energy = self.esm.get_energy(persona_id)
        mood = self.esm.get_mood_context(persona_id)
        sid = self.db.start_browse_session(
            persona_id, "scheduled", energy, mood, kind="peek"
        )
        self.db.add_state_snapshot(
            persona_id, "peek", energy, "",
            extra=json.dumps({"trigger": "scheduled"}, ensure_ascii=False),
        )
        self.db.finish_browse_session(sid, "completed", 0, "peek")
        self.db.append_event(
            persona_id, "observe",
            {"entity": "peek", "session_id": sid},
            [],
            f"session/{sid}/peek",
        )
        return BrowseResult(sid, "completed", 0, "peek")

    def _wishlist_candidates(self, payload: Any) -> list[dict]:
        if not self.config.wishlist_enabled:
            return []
        raw = payload.get("wishlist_candidates") if isinstance(payload, dict) else None
        if not isinstance(raw, list):
            return []
        out: list[dict] = []
        for entry in raw:
            if not isinstance(entry, dict):
                continue
            text = sanitize_text(entry.get("text"), 400)
            if not text:
                continue
            out.append({
                "text": text,
                "interest_key": sanitize_text(entry.get("interest_key"), 40),
                "source": "diary",
            })
        return out

    async def _evaluate_wishlist(
        self, persona_id: str, persona_prompt: str
    ) -> dict[str, int]:
        pending = self.db.list_wishlist(persona_id, status="pending", limit=50)
        if not pending or not self.config.wishlist_enabled:
            return {"promoted": 0, "discarded": 0}
        try:
            payload = await self._llm_call(
                persona_id,
                build_wishlist_eval_prompt(persona_prompt, persona_id, pending),
            )
        except (BudgetExhausted, LLMError):
            return {"promoted": 0, "discarded": 0}
        decisions = payload.get("decisions") if isinstance(payload, dict) else None
        if not isinstance(decisions, list):
            return {"promoted": 0, "discarded": 0}
        promoted = 0
        discarded = 0
        for decision in decisions:
            if not isinstance(decision, dict):
                continue
            try:
                item_id = int(decision.get("id") or 0)
            except (TypeError, ValueError):
                continue
            action = str(decision.get("action") or "").strip().lower()
            reason = sanitize_text(decision.get("reason"), 200)
            if action == "promote":
                key = sanitize_text(decision.get("interest_key"), 40)
                if not key:
                    continue
                name = sanitize_text(decision.get("interest_name"), 40) or key
                if self.db.update_wishlist_status(
                    persona_id, item_id, "promoted", reason, key, name
                ):
                    self.interests.apply_updates(
                        persona_id,
                        {key: {"name": name, "delta": 0.0}},
                    )
                    promoted += 1
            elif action == "discard":
                if self.db.update_wishlist_status(
                    persona_id, item_id, "discarded", reason
                ):
                    discarded += 1
        return {"promoted": promoted, "discarded": discarded}

    def _pick_revisit(self, persona_id: str, date: str) -> tuple[Optional[int], list[dict]]:
        """Randomly pick notes from revisit_days ago for the nightly diary."""
        if not self.config.revisit_days or self.rng.random() >= self.config.revisit_probability:
            return None, []
        day = int(self.rng.choice(self.config.revisit_days))
        if day <= 0:
            return None, []
        revisit_date = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=day)).strftime("%Y-%m-%d")
        return day, self.db.list_notes(persona_id, revisit_date, limit=20)

    # ----- diary -----

    async def run_nightly_diary(self, persona_id: str) -> dict[str, Any]:
        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return {"date": local_today(self.config.timezone, self.now_fn()),
                    "notes": 0, "fallback": False, "skipped": "persona_unavailable"}

        now = local_now(self.config.timezone, self.now_fn())
        date = now.strftime("%Y-%m-%d")
        self.db.decay_note_temperature(
            persona_id, self.config.memory_temperature_decay
        )
        if self._energy_budget_exhausted(persona_id, date):
            self.db.add_state_snapshot(
                persona_id, "diary_skipped", None, "",
                extra=json.dumps(
                    {"reason": "energy_budget_exhausted"}, ensure_ascii=False
                ),
            )
            self.db.append_event(
                persona_id, "change",
                {"entity": "task", "kind": "diary", "action": "skip",
                 "reason": "energy_budget_exhausted", "slot": ""},
                [],
                f"task/diary/{date}/energy_budget_exhausted",
            )
            return {"date": date, "notes": 0, "fallback": False,
                    "skipped": "energy_budget_exhausted"}
        notes: list[dict] = []
        try:
            if self.share_gate is not None:
                await self.share_gate.recheck_pending(persona_id)
            notes = self.db.list_notes(persona_id, date, limit=200)
            snapshots = self.db.list_state_snapshots(persona_id, since_date=date, limit=200)
            mood_context = self.esm.get_mood_context(persona_id)
            revisit_day, raw_revisit_notes = self._pick_revisit(persona_id, date)

            if self.config.injection_log_enabled:
                for note in notes:
                    for field in ("title", "summary", "opinion"):
                        value = note.get(field)
                        if is_suspicious(value):
                            self.db.log_injection(
                                persona_id, source=note.get("source") or "memory",
                                context="diary", field=field, preview=str(value)[:200],
                            )

            wishlist_candidates: list[dict] = []
            if not notes and not raw_revisit_notes:
                diary_text = "今天没出门。没有特别的见闻，只是安静地待着。"
                mood = "calm"
                signature = ""
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
                safe_revisit_notes = [
                    {
                        **note,
                        "title": sanitize_text(note.get("title"), 300),
                        "summary": sanitize_text(note.get("summary"), 600),
                        "opinion": sanitize_text(note.get("opinion"), 600),
                    }
                    for note in raw_revisit_notes
                ]
                try:
                    payload = await self._llm_call(
                        persona_id,
                        build_diary_prompt(
                            persona.system_prompt, persona_id, safe_notes, snapshots, mood_context,
                            date, revisit=safe_revisit_notes, revisit_day=revisit_day,
                        ),
                    )
                except BudgetExhausted as exc:
                    self.log.warning("diary budget exhausted for %s: %s", persona_id, exc)
                    self.db.add_state_snapshot(
                        persona_id, "diary_skipped", self.esm.get_energy(persona_id), "",
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
                signature = (
                    str(payload.get("signature") or "").strip()[:20]
                    if self.config.signature_enabled else ""
                )
                wishlist_candidates = self._wishlist_candidates(payload)

            memory_ref = ""
            if self.memory is not None and self.config.memory_host:
                try:
                    memory_ref = self.memory.store_diary_line(
                        persona_id, date, diary_text, mood=mood,
                        signature=signature,
                        source_refs=[f"note:{note['id']}" for note in notes],
                    )
                except MemoryHostError as exc:
                    self.log.error(
                        "diary unified memory write failed for %s: %s",
                        persona_id, exc,
                    )
                    self.db.add_state_snapshot(
                        persona_id, "diary_error", None, "",
                        extra=json.dumps(
                            {"error": f"memory_host: {exc}"}, ensure_ascii=False
                        ),
                    )
                    return {"date": date, "notes": len(notes), "fallback": False,
                            "error": f"memory_host: {exc}"}

            energy = self.esm.get_energy(persona_id)
            top = ",".join(
                row["name"] or row["key"] for row in self.db.get_interests(persona_id, limit=5)
            )
            self.db.stage_diary(persona_id, None, date, diary_text, mood, energy, top, signature=signature)
            self.db.stage_snapshot(
                persona_id, None, "diary", energy, mood,
                extra=json.dumps(
                    {"notes": len(notes), "revisit_day": revisit_day,
                     "revisit_notes": len(raw_revisit_notes)},
                    ensure_ascii=False,
                ),
            )
            for candidate in wishlist_candidates:
                self.db.stage_wishlist(
                    persona_id, None, candidate["text"],
                    interest_key=candidate["interest_key"],
                    source=candidate["source"],
                )
            if notes and interest_updates:
                self.interests.stage_updates(persona_id, None, interest_updates, now=now)
            self.db.commit_staged(persona_id, None, status="completed")
            if notes or raw_revisit_notes:
                _, energy_mode = self._consume_energy(
                    persona_id, ENERGY_COST_DIARY, "internet_life:diary"
                )
                if energy_mode == "local_estimate":
                    self.db.add_state_snapshot(
                        persona_id, "diary_energy_fallback", energy, mood,
                        extra=json.dumps(
                            {"energy_mode": "local_estimate"}, ensure_ascii=False
                        ),
                    )
            source_refs = [
                {"note_id": note["id"], "url": note.get("url") or ""}
                for note in notes
            ]
            source_refs += [
                {"note_id": note["id"], "url": note.get("url") or ""}
                for note in raw_revisit_notes
            ]
            self.db.append_event(
                persona_id, "think",
                {"entity": "diary", "date": date, "mood": mood,
                 "signature": signature, "notes_count": len(notes),
                 "revisit_day": revisit_day,
                 "revisit_notes": len(raw_revisit_notes),
                 "unified_memory_id": memory_ref},
                source_refs,
                f"diary/{date}",
            )
            if self.memory is not None and self.config.memory_host:
                try:
                    self.memory.store_event(
                        persona_id, "internet-life", "", now.timestamp(), "think",
                        {"entity": "diary", "date": date,
                         "notes_count": len(notes),
                         "unified_memory_id": memory_ref},
                    )
                except MemoryHostError as exc:
                    self.log.warning(
                        "diary event mirror failed for %s: %s", persona_id, exc
                    )
            self.interests.daily_decay(persona_id)
            wishlist_eval = await self._evaluate_wishlist(persona_id, persona.system_prompt)
            return {"date": date, "notes": len(notes), "fallback": False,
                    "revisit_day": revisit_day, "revisit_notes": len(raw_revisit_notes),
                    "wishlist_promoted": wishlist_eval["promoted"],
                    "wishlist_discarded": wishlist_eval["discarded"]}
        except Exception as exc:
            self.log.exception("nightly diary failed for %s", persona_id)
            self.db.discard_staged(persona_id, None, repr(exc))
            self.db.add_state_snapshot(
                persona_id, "diary_error", self.esm.get_energy(persona_id), "",
                extra=json.dumps({"error": repr(exc), "notes": len(notes)}, ensure_ascii=False),
            )
            return {"date": date, "notes": len(notes), "fallback": False, "error": repr(exc)}

    # ----- reviews -----

    def _review_range(self, now: datetime, period: str) -> tuple[str, str]:
        if period == "yearly":
            start = datetime(now.year - 1, 1, 1)
            end = datetime(now.year - 1, 12, 31, 23, 59, 59)
        else:
            first_this_month = now.replace(day=1)
            end = first_this_month - timedelta(days=1)
            start = end.replace(day=1)
        return start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")

    def _review_stats(
        self,
        persona_id: str,
        period_start: str,
        period_end: str,
        period: str,
    ) -> dict[str, Any]:
        sessions = [
            session for session in self.db.list_sessions(persona_id, limit=100000)
            if (session.get("kind") or "browse") == "browse"
            and period_start <= (session.get("started_at") or "")[:10] <= period_end
        ]
        completed = [s for s in sessions if s.get("status") == "completed"]
        browse_days = len({s["started_at"][:10] for s in completed})
        start_dt = datetime.strptime(period_start, "%Y-%m-%d")
        end_dt = datetime.strptime(period_end, "%Y-%m-%d")
        total_days = (end_dt - start_dt).days + 1
        diaries = sorted(
            (
                d for d in self.db.list_diaries(persona_id, limit=100000)
                if period_start <= d.get("date", "") <= period_end
            ),
            key=lambda d: d["date"],
        )
        share_logs = [
            log for log in self.db.list_share_log(persona_id, limit=100000)
            if log.get("status") == "sent"
            and period_start <= (log.get("attempted_at") or "")[:10] <= period_end
        ]
        interest_start = diaries[0].get("interest_top") if diaries else ""
        interest_end = diaries[-1].get("interest_top") if diaries else ""
        return {
            "period": period,
            "period_start": period_start,
            "period_end": period_end,
            "browse_count": len(completed),
            "browse_days": browse_days,
            "days_without_browse": max(0, total_days - browse_days),
            "note_count": self.db.count_notes_between(
                persona_id, period_start, period_end
            ),
            "diary_count": len(diaries),
            "share_count": len(share_logs),
            "interest_start": _first_topic(interest_start),
            "interest_end": _first_topic(interest_end),
            "top_categories": [
                {"category": row["category"], "count": int(row["n"] or 0)}
                for row in self.db.category_counts_between(
                    persona_id, period_start, period_end
                )
            ],
        }

    def _review_source_refs(
        self, persona_id: str, period_start: str, period_end: str
    ) -> list[dict[str, Any]]:
        notes = self.db.list_notes_between(
            persona_id, period_start, period_end, limit=20
        )
        diaries = sorted(
            (
                d for d in self.db.list_diaries(persona_id, limit=100000)
                if period_start <= d.get("date", "") <= period_end
            ),
            key=lambda d: d["date"],
        )
        refs: list[dict[str, Any]] = [
            {"note_id": note["id"], "url": note.get("url") or ""}
            for note in notes
        ]
        refs += [{"diary_date": diary["date"]} for diary in diaries[:10]]
        return refs

    @staticmethod
    def _fallback_review_text(stats: dict[str, Any]) -> str:
        label = "这一年" if stats.get("period") == "yearly" else "这个月"
        interest_start = stats.get("interest_start") or "未记录"
        interest_end = stats.get("interest_end") or "未记录"
        lines = [
            f"{label}我漫游了 {stats.get('browse_count', 0)} 次，"
            f"有 {stats.get('browse_days', 0)} 天出门、"
            f"{stats.get('days_without_browse', 0)} 天没出门；"
            f"写下了 {stats.get('note_count', 0)} 条短记、"
            f"{stats.get('diary_count', 0)} 篇日记，分享过 "
            f"{stats.get('share_count', 0)} 次。",
        ]
        if interest_start != interest_end:
            lines.append(
                f"兴趣从「{interest_start}」慢慢转向「{interest_end}」。"
            )
        return "".join(lines)

    async def run_review(self, persona_id: str, period: str) -> dict[str, Any]:
        period = "yearly" if period == "yearly" else "monthly"
        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return {"period": period, "ok": False, "error": "persona_unavailable"}
        now = local_now(self.config.timezone, self.now_fn())
        period_start, period_end = self._review_range(now, period)
        idem = f"review/{period}/{period_start}"
        existing = self.db.find_event(persona_id, idem)
        if existing is not None:
            rows = self.db.list_reviews(persona_id, limit=100)
            row = next(
                (r for r in rows
                 if r["period"] == period and r["period_start"] == period_start),
                None,
            )
            return {
                "period": period, "period_start": period_start,
                "period_end": period_end, "ok": True,
                "content": row["content"] if row else "",
                "status": row["status"] if row else "done",
                "duplicate": True,
            }
        stats = self._review_stats(
            persona_id, period_start, period_end, period
        )
        source_refs = self._review_source_refs(
            persona_id, period_start, period_end
        )
        prompt = build_review_prompt(
            persona.system_prompt, persona_id, period, period_start,
            period_end, stats, source_refs,
        )
        fallback = False
        try:
            payload = await self._llm_call(persona_id, prompt)
            content = str(payload.get("review_text") or "").strip()
            if not content:
                raise LLMError("review LLM 未返回回顾正文")
            status = "done"
        except BudgetExhausted as exc:
            self.db.add_state_snapshot(
                persona_id, "review_skipped", self.esm.get_energy(persona_id), "",
                extra=json.dumps(
                    {"reason": "budget_exhausted", "period": period},
                    ensure_ascii=False,
                ),
            )
            return {
                "period": period, "period_start": period_start,
                "period_end": period_end, "ok": False,
                "skipped": "budget_exhausted", "error": str(exc),
            }
        except LLMError as exc:
            self.log.warning("review LLM failed for %s: %s", persona_id, exc)
            content = self._fallback_review_text(stats)
            status = "fallback"
            fallback = True
        self.db.upsert_review(
            persona_id, period, period_start, period_end, content,
            status=status, source_refs=source_refs,
        )
        self.db.append_event(
            persona_id, "review",
            {"period": period, "period_start": period_start,
             "period_end": period_end, "status": status,
             "fallback": fallback, "content": content[:500]},
            source_refs, idem,
        )
        if self.memory is not None and self.config.memory_host:
            try:
                self.memory.store_event(
                    persona_id, "internet-life", "", now.timestamp(), "review",
                    {"period": period, "period_start": period_start,
                     "period_end": period_end, "status": status},
                )
            except MemoryHostError as exc:
                self.log.warning(
                    "review event mirror failed for %s: %s", persona_id, exc
                )
        return {
            "period": period, "period_start": period_start,
            "period_end": period_end, "ok": True,
            "content": content, "status": status, "fallback": fallback,
        }

    # ----- plan -----

    async def generate_plan(self, persona_id: str) -> dict[str, Any]:
        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return {"date": local_today(self.config.timezone, self.now_fn()),
                    "accepted": [], "rejected": [], "error": "persona_unavailable"}
        date = local_today(self.config.timezone, self.now_fn())
        summary = self.db.plan_summary(persona_id, date)
        pending = self.db.list_plans(persona_id, date, status="pending")
        board_lines = [
            f"总数 {summary['total']}，已完成 {summary['done']}，"
            f"待执行 {summary['pending']}，跳过 {summary['skipped']}，"
            f"失败 {summary['failed']}"
        ]
        for row in pending[:20]:
            board_lines.append(
                f"- {row['task_id']} ({row['kind']}) {row['scheduled_at']} "
                f"{'固定' if row.get('fixed') else '可选'}"
            )
        sleep = self.config.sleep_window
        sleep_text = f"{sleep.start.strftime('%H:%M')}-{sleep.end.strftime('%H:%M')}"
        try:
            payload = await self._llm_call(
                persona_id,
                build_plan_prompt(
                    persona.system_prompt, persona_id, date,
                    "\n".join(board_lines), sleep_text,
                    action_cap=int(self.config.plan_daily_action_cap or 0),
                ),
            )
        except BudgetExhausted as exc:
            return {"date": date, "accepted": [], "rejected": [],
                    "error": f"budget_exhausted: {exc}"}
        except LLMError as exc:
            return {"date": date, "accepted": [], "rejected": [],
                    "error": f"llm_error: {exc}"}
        return self._apply_plan_payload(persona_id, date, payload)

    def _apply_plan_payload(self, persona_id: str, date: str, payload: Any) -> dict[str, Any]:
        accepted: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        raw_actions = payload.get("actions") if isinstance(payload, dict) else None
        if not isinstance(raw_actions, list):
            return {"date": date, "accepted": accepted, "rejected": rejected,
                    "error": "invalid_payload"}
        cap = int(self.config.plan_daily_action_cap or 0)
        energy_blocked = False
        energy_reason = ""
        try:
            energy_blocked, _, energy_reason = self.esm.gate_energy(persona_id)
        except Exception:
            energy_blocked = False
        usage = self.db.get_daily_usage(persona_id, date)
        calls = int(usage["llm_calls"] or 0) if usage else 0
        tokens = int(usage["tokens"] or 0) if usage else 0
        call_limit = int(self.config.daily_llm_call_limit or 0)
        token_budget = int(self.config.daily_token_budget or 0)
        budget_exhausted = (call_limit > 0 and calls >= call_limit) or (
            token_budget > 0 and tokens >= token_budget
        )
        for index, entry in enumerate(raw_actions):
            if not isinstance(entry, dict):
                action = str(entry)[:40] or "unknown"
                reason = "invalid_entry"
                rejected.append({"action": action, "reason": reason})
                self._record_plan_rejection(persona_id, date, action, index, reason)
                continue
            action = str(entry.get("action") or "").strip().lower()
            if budget_exhausted:
                reason = "budget_exhausted"
                rejected.append({"action": action or "unknown", "reason": reason})
                self._record_plan_rejection(
                    persona_id, date, action or "unknown", index, reason,
                )
                continue
            if action not in PLAN_ACTION_VOCABULARY:
                reason = "unknown_action"
                rejected.append({"action": action or "unknown", "reason": reason})
                self._record_plan_rejection(
                    persona_id, date, action or "unknown", index, reason,
                )
                continue
            if action not in ("browse", "diary"):
                reason = "not_supported_yet"
                rejected.append({"action": action, "reason": reason})
                self._record_plan_rejection(persona_id, date, action, index, reason)
                continue
            if cap > 0 and len(accepted) >= cap:
                reason = "daily_action_cap"
                rejected.append({"action": action, "reason": reason})
                self._record_plan_rejection(persona_id, date, action, index, reason)
                continue
            if not self._plan_dependency_ok(persona_id, date, action):
                reason = "dependency_not_met"
                rejected.append({"action": action, "reason": reason})
                self._record_plan_rejection(persona_id, date, action, index, reason)
                continue
            scheduled = self._plan_window_time(date, entry)
            if scheduled is None:
                reason = "invalid_window"
                rejected.append({"action": action, "reason": reason})
                self._record_plan_rejection(persona_id, date, action, index, reason)
                continue
            if self.config.sleep_window.contains(
                datetime.strptime(scheduled, "%Y-%m-%d %H:%M:%S")
            ):
                reason = "sleep_window"
                rejected.append({"action": action, "reason": reason})
                self._record_plan_rejection(persona_id, date, action, index, reason)
                continue
            if energy_blocked:
                reason = f"energy_gate: {energy_reason}"
                rejected.append({"action": action, "reason": reason})
                self._record_plan_rejection(persona_id, date, action, index, reason)
                continue
            plan_reason = sanitize_text(entry.get("reason"), 200)
            task_id = f"{action}-plan-{index + 1}"
            plan_id = self.db.add_optional_plan(
                persona_id, date, task_id, action, scheduled, reason=plan_reason,
            )
            if plan_id is None:
                reason = "duplicate"
                rejected.append({"action": action, "reason": reason})
                self._record_plan_rejection(persona_id, date, action, index, reason)
                continue
            accepted.append({"action": action, "task_id": task_id,
                             "scheduled_at": scheduled, "reason": plan_reason})
        return {"date": date, "accepted": accepted, "rejected": rejected}

    def _record_plan_rejection(
        self, persona_id: str, plan_date: str, action: str, index: int, reason: str
    ) -> None:
        self.db.append_event(
            persona_id,
            "change",
            {"entity": "plan", "action": "reject", "plan_date": plan_date,
             "plan_action": action, "reason": reason},
            [{"entity": "plan", "plan_date": plan_date}],
            f"plan/{plan_date}/reject/{action}/{index + 1}",
        )

    def _plan_dependency_ok(self, persona_id: str, plan_date: str, action: str) -> bool:
        if action == "diary":
            return bool(self.db.list_notes(persona_id, plan_date, limit=1))
        return True

    def _plan_window_time(self, date: str, entry: dict) -> Optional[str]:
        try:
            start_h, start_m = str(entry.get("window_start") or "").split(":", 1)
            end_h, end_m = str(entry.get("window_end") or "").split(":", 1)
            start_min = int(start_h) * 60 + int(start_m)
            end_min = int(end_h) * 60 + int(end_m)
        except (ValueError, TypeError, AttributeError):
            return None
        if end_min <= start_min or not (0 <= start_min < 24 * 60) or not (0 <= end_min <= 24 * 60):
            return None
        mid = (start_min + end_min) // 2
        return f"{date} {mid // 60:02d}:{mid % 60:02d}:00"