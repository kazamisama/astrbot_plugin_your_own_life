"""Per-persona life orchestration: browse sessions, shares and nightly diary."""
from __future__ import annotations

import hashlib
import json
import logging
import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Optional, Sequence

import httpx

from life.config import LifeConfig, current_time_slot, persona_allowed
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
    build_capsule_reply_prompt,
    build_diary_prompt,
    build_plan_prompt,
    build_quarterly_prompt,
    build_review_prompt,
    build_revisit_prompt,
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


def _watched_digest(item: FetchedItem) -> str:
    """Content fingerprint for stable watchlist URLs.

    A watched blog/repo keeps the same URL forever. Comparing only the URL
    would hide every later change, so the digest covers title, summary and
    publish time and is stored in seen_items.
    """
    raw = "\n".join(
        [str(item.title or ""), str(item.summary or ""), str(item.published_at or "")]
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


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
        presence: Optional[Any] = None,
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
        self.presence = presence
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
        elif kind == "capsules":
            self.db.add_state_snapshot(persona_id, "capsules_skipped", extra=extra)
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
        if not persona_allowed(self.config, persona_id):
            return BrowseResult(None, "skipped", 0, "persona_not_whitelisted")
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

            unseen = []
            for item in candidates:
                watched = item.source.startswith("watchlist/")
                digest = _watched_digest(item) if watched else None
                # 普通来源按 URL 去重；关注列表的 URL 固定，只有内容变化才重新入选。
                if self.db.is_seen(persona_id, item.url_hash, digest):
                    continue
                unseen.append(item)
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
            selected = self._pad_selected(selected, unseen)

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
                self.db.stage_seen(
                    persona_id, sid, item.url_hash,
                    _watched_digest(item) if item.source.startswith("watchlist/") else "",
                )
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
                                "watched": bool(item.source.startswith("watchlist/")),
                            },
                        )
                except MemoryHostError as exc:
                    self.log.error(
                        "browse unified memory write failed for %s: %s",
                        persona_id, exc,
                    )
                    self.db.discard_staged(persona_id, sid, f"memory_host: {exc}")
                    self.interests.clear_staging(persona_id, sid)
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
            await self._after_browse_commit(
                persona_id, sid, notes,
                energy_before=energy_before,
                session_mood=session_mood,
                trigger=trigger,
                now=now,
            )
            return BrowseResult(sid, "completed", len(notes), "")
        except Exception as exc:
            self.log.exception("browse session failed for %s", persona_id)
            self.db.discard_staged(persona_id, sid, repr(exc))
            self.interests.clear_staging(persona_id, sid)
            self.db.add_state_snapshot(
                persona_id, "browse_error", energy_before, "",
                extra=json.dumps({"error": repr(exc)}, ensure_ascii=False),
            )
            return BrowseResult(sid, "error", 0, "", repr(exc))

    async def _after_browse_commit(
        self,
        persona_id: str,
        sid: int,
        notes: list[dict],
        *,
        energy_before: Optional[float],
        session_mood: str,
        trigger: str,
        now: datetime,
    ) -> None:
        try:
            self.interests.clear_staging(persona_id, sid)
        except Exception as exc:
            self.log.warning(
                "browse staging clear failed after commit for %s: %s",
                persona_id, exc,
            )
        note_refs = [
            {"note_id": note["id"], "url": note.get("url") or ""}
            for note in notes
        ]
        try:
            self.db.append_event(
                persona_id, "observe",
                {"entity": "browse", "session_id": sid,
                 "notes_count": len(notes)},
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
        except Exception as exc:
            self.log.warning(
                "browse event write failed after commit for %s: %s",
                persona_id, exc,
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
            except Exception as exc:
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
                        url_entity = {
                            "dimension": "url",
                            "entity_id": str(note.get("url_hash") or url),
                            "name": str(note.get("title") or "")[:120] or url,
                            "canonical_url": url,
                        }
                        if str(note.get("source") or "").startswith("watchlist/"):
                            url_entity["watched"] = True
                        url_ent = self.memory.upsert_entity(
                            persona_id, url_entity
                        )
                        if src and url_ent and platform_ids.get(src):
                            self.memory.link_entities(
                                persona_id, url_ent, "appears_on",
                                platform_ids[src], weight=1.0,
                            )
            except Exception as exc:
                self.log.warning(
                    "entity sync failed for %s: %s", persona_id, exc
                )
        try:
            _, energy_mode = self._consume_energy(
                persona_id, ENERGY_COST_BROWSE, "internet_life:browse"
            )
            if energy_mode == "local_estimate":
                self.db.add_state_snapshot(
                    persona_id, "browse_energy_fallback", energy_before,
                    session_mood,
                    extra=json.dumps(
                        {"trigger": trigger, "energy_mode": "local_estimate"},
                        ensure_ascii=False,
                    ),
                )
        except Exception as exc:
            # 短记已提交，后置副作用失败不能把整个 session 标成 error。
            self.log.warning(
                "browse energy bookkeeping failed after commit for %s: %s",
                persona_id, exc,
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
        value = raw.get("should_share", False)
        if isinstance(value, str):
            shared = value.strip().lower() in ("1", "true", "yes", "on")
        else:
            shared = bool(value)
        return {
            "should_share": shared,
            "reason": str(raw.get("reason") or ""),
            "target": str(raw.get("target") or ""),
        }

    def _pad_selected(
        self, selected: list, candidates: Sequence[FetchedItem]
    ) -> list:
        """Fill the LLM's selection up to notes_min with deterministic picks."""
        minimum = max(0, int(self.config.notes_min or 0))
        if len(selected) >= minimum:
            return selected
        out = list(selected)
        used = {item.url_hash for item, _ in out}
        for item in candidates:
            if len(out) >= minimum:
                break
            if item.url_hash in used:
                continue
            used.add(item.url_hash)
            out.append((
                item,
                {
                    "summary": item.summary or item.title,
                    "interest_level": 0.5,
                    "share": {"should_share": False},
                },
            ))
        return out

    async def run_peek(self, persona_id: str) -> BrowseResult:
        if not self.config.enabled:
            return BrowseResult(None, "disabled", 0, "disabled")
        if not persona_allowed(self.config, persona_id):
            return BrowseResult(None, "skipped", 0, "persona_not_whitelisted")
        now = local_now(self.config.timezone, self.now_fn())
        if self.config.sleep_window.contains(now):
            return BrowseResult(None, "skipped", 0, "sleep_window")
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

    async def run_nightly_diary(
        self, persona_id: str, plan_date: Optional[str] = None
    ) -> dict[str, Any]:
        date = plan_date or local_today(self.config.timezone, self.now_fn())
        try:
            datetime.strptime(date, "%Y-%m-%d")
        except (TypeError, ValueError):
            date = local_today(self.config.timezone, self.now_fn())
        if not self.config.enabled:
            return {"date": date, "notes": 0, "fallback": False,
                    "skipped": "disabled"}
        if not persona_allowed(self.config, persona_id):
            return {"date": date, "notes": 0, "fallback": False,
                    "skipped": "persona_not_whitelisted"}
        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return {"date": date, "notes": 0, "fallback": False,
                    "skipped": "persona_unavailable"}

        now = local_now(self.config.timezone, self.now_fn())
        if self.config.sleep_window.contains(now):
            return {"date": date, "notes": 0, "fallback": False,
                    "skipped": "sleep_window"}
        run_token = -random.randrange(1, 2**62)
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
            self.db.stage_diary(persona_id, run_token, date, diary_text, mood, energy, top, signature=signature)
            self.db.stage_snapshot(
                persona_id, run_token, "diary", energy, mood,
                extra=json.dumps(
                    {"notes": len(notes), "revisit_day": revisit_day,
                     "revisit_notes": len(raw_revisit_notes)},
                    ensure_ascii=False,
                ),
            )
            for candidate in wishlist_candidates:
                self.db.stage_wishlist(
                    persona_id, run_token, candidate["text"],
                    interest_key=candidate["interest_key"],
                    source=candidate["source"],
                )
            if notes and interest_updates:
                self.interests.stage_updates(persona_id, run_token, interest_updates, now=now)
            self.db.commit_staged(persona_id, run_token, status="completed")
            self._after_diary_commit(
                persona_id, date, notes, raw_revisit_notes,
                run_token=run_token,
                mood=mood, signature=signature, memory_ref=memory_ref,
                energy=energy, revisit_day=revisit_day, now=now,
            )
        except Exception as exc:
            self.log.exception("nightly diary failed for %s", persona_id)
            self.db.discard_staged(persona_id, run_token, repr(exc))
            self.interests.clear_staging(persona_id, run_token)
            self.db.add_state_snapshot(
                persona_id, "diary_error", self.esm.get_energy(persona_id), "",
                extra=json.dumps({"error": repr(exc), "notes": len(notes)}, ensure_ascii=False),
            )
            return {"date": date, "notes": len(notes), "fallback": False, "error": repr(exc)}

        followups = await self._after_diary_followups(
            persona_id, notes, date, persona
        )
        return {
            "date": date,
            "notes": len(notes),
            "fallback": False,
            "revisit_day": revisit_day,
            "revisit_notes": len(raw_revisit_notes),
            **followups,
        }

    def _after_diary_commit(
        self,
        persona_id: str,
        date: str,
        notes: list[dict],
        revisit_notes: list[dict],
        *,
        run_token: int,
        mood: str,
        signature: str,
        memory_ref: str,
        energy: Optional[float],
        revisit_day: int,
        now: datetime,
    ) -> None:
        try:
            self.interests.clear_staging(persona_id, run_token)
        except Exception as exc:
            self.log.warning(
                "diary staging clear failed after commit for %s: %s",
                persona_id, exc,
            )
        if notes or revisit_notes:
            try:
                _, energy_mode = self._consume_energy(
                    persona_id, ENERGY_COST_DIARY, "internet_life:diary"
                )
                if energy_mode == "local_estimate":
                    self.db.add_state_snapshot(
                        persona_id, "diary_energy_fallback", energy, mood,
                        extra=json.dumps(
                            {"energy_mode": "local_estimate"},
                            ensure_ascii=False,
                        ),
                    )
            except Exception as exc:
                self.log.warning(
                    "diary energy bookkeeping failed after commit for %s: %s",
                    persona_id, exc,
                )
        source_refs = [
            {"note_id": note["id"], "url": note.get("url") or ""}
            for note in notes
        ]
        source_refs += [
            {"note_id": note["id"], "url": note.get("url") or ""}
            for note in revisit_notes
        ]
        try:
            self.db.append_event(
                persona_id, "think",
                {"entity": "diary", "date": date, "mood": mood,
                 "signature": signature, "notes_count": len(notes),
                 "revisit_day": revisit_day,
                 "revisit_notes": len(revisit_notes),
                 "unified_memory_id": memory_ref},
                source_refs,
                f"diary/{date}",
            )
        except Exception as exc:
            self.log.warning(
                "diary event write failed after commit for %s: %s",
                persona_id, exc,
            )
        if self.memory is not None and self.config.memory_host:
            try:
                self.memory.store_event(
                    persona_id, "internet-life", "", now.timestamp(), "think",
                    {"entity": "diary", "date": date,
                     "notes_count": len(notes),
                     "unified_memory_id": memory_ref},
                )
            except Exception as exc:
                self.log.warning(
                    "diary event mirror failed for %s: %s", persona_id, exc
                )
        try:
            self.interests.daily_decay(persona_id)
        except Exception as exc:
            self.log.warning(
                "interest decay failed after diary commit for %s: %s",
                persona_id, exc,
            )

    async def _after_diary_followups(
        self,
        persona_id: str,
        notes: list[dict],
        date: str,
        persona: Any,
    ) -> dict[str, Any]:
        aux_errors: list[str] = []
        capsules_sealed = 0
        wishlist_eval = {"promoted": 0, "discarded": 0}
        capsule_result = {"opened": 0, "replied": 0}
        revisit_result = {"candidates": 0, "revisited": 0, "failed": 0}
        purged_trash = 0
        # 这几个动作彼此独立：任何一个失败都不能阻断后面的胶囊/重访/清理。
        try:
            capsules_sealed = self._seal_daily_capsule(persona_id, notes, date)
        except Exception as exc:
            self.log.warning("capsule seal failed for %s: %s", persona_id, exc)
            aux_errors.append(f"capsule_seal: {exc!r}")
        try:
            wishlist_eval = await self._evaluate_wishlist(
                persona_id, persona.system_prompt
            )
        except Exception as exc:
            self.log.warning("wishlist eval failed for %s: %s", persona_id, exc)
            aux_errors.append(f"wishlist: {exc!r}")
        try:
            capsule_result = await self.run_capsules(persona_id)
        except Exception as exc:
            self.log.warning("capsule run failed for %s: %s", persona_id, exc)
            aux_errors.append(f"capsules: {exc!r}")
        try:
            revisit_result = await self.run_revisit(persona_id)
        except Exception as exc:
            self.log.warning("revisit failed for %s: %s", persona_id, exc)
            aux_errors.append(f"revisit: {exc!r}")
        try:
            purged_trash = self.db.purge_trash(
                persona_id, self.config.trash_retention_days
            )
        except Exception as exc:
            self.log.warning(
                "nightly trash purge failed for %s: %s", persona_id, exc
            )
            aux_errors.append(f"purge_trash: {exc!r}")
        return {
            "wishlist_promoted": wishlist_eval["promoted"],
            "wishlist_discarded": wishlist_eval["discarded"],
            "capsules_sealed": capsules_sealed,
            "capsules_opened": capsule_result["opened"],
            "capsules_replied": capsule_result["replied"],
            "purged_trash": purged_trash,
            "revisit_candidates": revisit_result.get("candidates", 0),
            "revisited": revisit_result.get("revisited", 0),
            "revisit_failed": revisit_result.get("failed", 0),
            "aux_error": "; ".join(aux_errors),
        }

    # ----- reviews -----

    def _review_range(self, now: datetime, period: str) -> tuple[str, str]:
        if period == "yearly":
            start = datetime(now.year - 1, 1, 1)
            end = datetime(now.year - 1, 12, 31, 23, 59, 59)
        elif period == "quarterly":
            quarter_start_month = ((now.month - 1) // 3) * 3 + 1
            if quarter_start_month == 1:
                year = now.year - 1
                start_month = 10
            else:
                year = now.year
                start_month = quarter_start_month - 3
            start = datetime(year, start_month, 1)
            next_month = start_month + 3
            if next_month > 12:
                end = datetime(year + 1, next_month - 12, 1) - timedelta(days=1)
            else:
                end = datetime(year, next_month, 1) - timedelta(days=1)
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
        browse_count = self.db.count_completed_sessions_between(
            persona_id, period_start, period_end
        )
        browse_days = self.db.count_session_days_between(
            persona_id, period_start, period_end
        )
        start_dt = datetime.strptime(period_start, "%Y-%m-%d")
        end_dt = datetime.strptime(period_end, "%Y-%m-%d")
        total_days = (end_dt - start_dt).days + 1
        diaries = self.db.list_diaries_between(
            persona_id, period_start, period_end
        )
        share_count = self.db.count_sent_shares_between(
            persona_id, period_start, period_end
        )
        interest_start = diaries[0].get("interest_top") if diaries else ""
        interest_end = diaries[-1].get("interest_top") if diaries else ""
        return {
            "period": period,
            "period_start": period_start,
            "period_end": period_end,
            "browse_count": browse_count,
            "browse_days": browse_days,
            "days_without_browse": max(0, total_days - browse_days),
            "note_count": self.db.count_notes_between(
                persona_id, period_start, period_end
            ),
            "diary_count": len(diaries),
            "share_count": share_count,
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
        diaries = self.db.list_diaries_between(
            persona_id, period_start, period_end
        )
        refs: list[dict[str, Any]] = [
            {"note_id": note["id"], "url": note.get("url") or ""}
            for note in notes
        ]
        refs += [{"diary_date": diary["date"]} for diary in diaries[:10]]
        return refs

    @staticmethod
    def _fallback_review_text(stats: dict[str, Any]) -> str:
        period = stats.get("period")
        label = "这一年" if period == "yearly" else (
            "这个季度" if period == "quarterly" else "这个月")
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

    async def _run_review_common(
        self,
        persona_id: str,
        persona: Any,
        period: str,
        plan_date: Optional[str],
        *,
        with_confidence: bool = False,
    ) -> dict[str, Any]:
        """Shared body for monthly/yearly and quarterly reviews.

        The two public entry points keep their own enable/whitelist checks and
        error envelopes; everything after a persona has been resolved is the
        same review lifecycle.  The with_confidence flag selects the quarterly
        prompt/stats/result shape.
        """
        now = local_now(self.config.timezone, self.now_fn())
        anchor = now
        if plan_date:
            try:
                anchor = datetime.strptime(plan_date, "%Y-%m-%d")
            except (TypeError, ValueError):
                anchor = now
        period_start, period_end = self._review_range(anchor, period)
        idem = f"review/{period}/{period_start}"
        existing = self.db.find_event(persona_id, idem)
        if existing is not None:
            rows = self.db.list_reviews(persona_id, limit=100)
            row = next(
                (r for r in rows
                 if r["period"] == period and r["period_start"] == period_start),
                None,
            )
            result = {
                "period": period, "period_start": period_start,
                "period_end": period_end, "ok": True,
                "content": row["content"] if row else "",
                "status": row["status"] if row else "done",
                "duplicate": True,
            }
            if with_confidence:
                result["confidence"] = (
                    float(row["confidence"] or 0) if row else 0.0
                )
            return result

        stats = self._review_stats(
            persona_id, period_start, period_end, period
        )
        if with_confidence:
            stats["mood_distribution"] = self._mood_distribution(
                persona_id, period_start, period_end
            )
        source_refs = self._review_source_refs(
            persona_id, period_start, period_end
        )
        if with_confidence:
            prompt = build_quarterly_prompt(
                persona.system_prompt, persona_id, period_start,
                period_end, stats, source_refs,
            )
        else:
            prompt = build_review_prompt(
                persona.system_prompt, persona_id, period, period_start,
                period_end, stats, source_refs,
            )
        fallback = False
        confidence = 0.0
        try:
            payload = await self._llm_call(persona_id, prompt)
            content = str(payload.get("review_text") or "").strip()
            if not content:
                if with_confidence:
                    raise LLMError("quarterly LLM 未返回评估正文")
                raise LLMError("review LLM 未返回回顾正文")
            status = "done"
            if with_confidence:
                try:
                    confidence = max(
                        0.0,
                        min(1.0, float(payload.get("confidence") or 0.0)),
                    )
                except (TypeError, ValueError):
                    confidence = 0.5
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
            label = "quarterly review" if with_confidence else "review"
            self.log.warning("%s LLM failed for %s: %s", label, persona_id, exc)
            content = self._fallback_review_text(stats)
            status = "fallback"
            fallback = True
            confidence = 0.5 if with_confidence else 0.0

        event_payload = {
            "period": period, "period_start": period_start,
            "period_end": period_end, "status": status,
            "fallback": fallback, "content": content[:500],
        }
        if with_confidence:
            event_payload["confidence"] = confidence
        self.db.upsert_review(
            persona_id, period, period_start, period_end, content,
            status=status, confidence=confidence, source_refs=source_refs,
        )
        self.db.append_event(
            persona_id, "review", event_payload, source_refs, idem,
        )
        if self.memory is not None and self.config.memory_host:
            mirror = {
                "period": period, "period_start": period_start,
                "period_end": period_end, "status": status,
            }
            if with_confidence:
                mirror["confidence"] = confidence
            try:
                self.memory.store_event(
                    persona_id, "internet-life", "", now.timestamp(), "review",
                    mirror,
                )
            except MemoryHostError as exc:
                label = "quarterly review" if with_confidence else "review"
                self.log.warning(
                    "%s event mirror failed for %s: %s", label, persona_id, exc
                )
        result = {
            "period": period, "period_start": period_start,
            "period_end": period_end, "ok": True,
            "content": content, "status": status, "fallback": fallback,
        }
        if with_confidence:
            result["confidence"] = confidence
        return result

    async def run_review(
        self, persona_id: str, period: str, plan_date: Optional[str] = None
    ) -> dict[str, Any]:
        period = "yearly" if period == "yearly" else "monthly"
        if not self.config.enabled:
            return {"period": period, "ok": False, "skipped": "disabled"}
        if not persona_allowed(self.config, persona_id):
            return {"period": period, "ok": False,
                    "error": "persona_not_whitelisted"}
        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return {"period": period, "ok": False, "error": "persona_unavailable"}
        return await self._run_review_common(
            persona_id, persona, period, plan_date
        )

    # ----- quarterly self review -----

    def _mood_distribution(
        self, persona_id: str, period_start: str, period_end: str
    ) -> list[dict[str, Any]]:
        counts: dict[str, int] = {}
        for diary in self.db.list_diaries(persona_id, limit=100000):
            if period_start <= diary.get("date", "") <= period_end:
                mood = diary.get("mood") or "unknown"
                counts[mood] = counts.get(mood, 0) + 1
        return [
            {"mood": mood, "count": count}
            for mood, count in sorted(
                counts.items(), key=lambda item: (-item[1], item[0])
            )
        ]

    async def run_quarterly_review(
        self, persona_id: str, plan_date: Optional[str] = None
    ) -> dict[str, Any]:
        if not self.config.enabled:
            return {"persona_id": persona_id, "ok": False, "skipped": "disabled"}
        if not self.config.quarterly_review_enabled:
            return {"persona_id": persona_id, "ok": False,
                    "skipped": "disabled"}
        if not persona_allowed(self.config, persona_id):
            return {"persona_id": persona_id, "ok": False,
                    "error": "persona_not_whitelisted"}
        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return {"persona_id": persona_id, "ok": False,
                    "error": "persona_unavailable"}
        return await self._run_review_common(
            persona_id, persona, "quarterly", plan_date,
            with_confidence=True,
        )

    # ----- time capsules -----

    def _capsule_unlock_at(self, sealed_at: str, days: int) -> str:
        try:
            sealed = datetime.strptime(sealed_at, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            sealed = datetime.now()
        return (sealed + timedelta(days=max(1, int(days)))).strftime("%Y-%m-%d %H:%M:%S")

    def seal_capsule_for_note(
        self,
        persona_id: str,
        note: dict,
        sealed_at: Optional[str] = None,
    ) -> Optional[int]:
        sealed = sealed_at or local_now(
            self.config.timezone, self.now_fn()
        ).strftime("%Y-%m-%d %H:%M:%S")
        unlock_at = self._capsule_unlock_at(sealed, self.config.capsule_days)
        return self.db.seal_capsule(
            persona_id,
            int(note["id"]),
            unlock_at,
            sealed_at=sealed,
            source_refs=[{"note_id": note["id"], "url": note.get("url") or ""}],
        )

    def _seal_daily_capsule(
        self, persona_id: str, notes: list[dict], date: str
    ) -> int:
        """Nightly: seal at most one note per day, preferring the day's hottest one."""
        if not self.config.enabled or not notes:
            return 0
        if self.db.capsules_sealed_on(persona_id, date) > 0:
            return 0
        candidate = max(
            notes,
            key=lambda note: (
                float(note.get("interest_level") or 0.0),
                int(note.get("id") or 0),
            ),
        )
        sealed_id = self.seal_capsule_for_note(persona_id, candidate)
        if sealed_id is None:
            return 0
        capsule = self.db.get_capsule(persona_id, sealed_id) or {}
        self.db.append_event(
            persona_id,
            "capsule",
            {"capsule_id": sealed_id, "note_id": candidate["id"],
             "status": "sealed",
             "sealed_at": capsule.get("sealed_at") or "",
             "unlock_at": capsule.get("unlock_at") or ""},
            [{"note_id": candidate["id"], "url": candidate.get("url") or ""}],
            f"capsule/{sealed_id}/seal",
        )
        return 1

    async def run_capsules(self, persona_id: str) -> dict[str, Any]:
        if not self.config.enabled:
            return {"persona_id": persona_id, "ok": False, "error": "disabled"}
        if not persona_allowed(self.config, persona_id):
            return {"persona_id": persona_id, "ok": False,
                    "error": "persona_not_whitelisted"}
        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return {"persona_id": persona_id, "ok": False,
                    "error": "persona_unavailable"}
        now = local_now(self.config.timezone, self.now_fn())
        due = self.db.capsules_due(
            persona_id, now.strftime("%Y-%m-%d %H:%M:%S")
        )
        opened = 0
        replied = 0
        failed = 0
        for capsule in due:
            note = self.db.get_note(capsule["note_id"])
            if not note:
                # 短记已软删/清除：不要把胶囊提前 unlock 成永远无法回信的僵尸。
                # 保留 sealed，等短记恢复或 purge_trash 级联删除。
                continue
            if self.db.unlock_capsule(
                persona_id, capsule["id"],
                now_str=now.strftime("%Y-%m-%d %H:%M:%S"),
            ):
                opened += 1
            prompt = build_capsule_reply_prompt(
                persona.system_prompt, persona_id, note,
                capsule["sealed_at"], capsule["unlock_at"],
            )
            try:
                payload = await self._llm_call(persona_id, prompt)
                reply = str(payload.get("reply_text") or "").strip()
                if not reply:
                    raise LLMError("capsule LLM 未返回回信")
                self.db.save_capsule_reply(persona_id, capsule["id"], reply)
                replied += 1
                self.db.append_event(
                    persona_id, "capsule",
                    {"capsule_id": capsule["id"], "note_id": capsule["note_id"],
                     "status": "replied", "reply": reply[:500],
                     "sealed_at": capsule["sealed_at"],
                     "unlock_at": capsule["unlock_at"]},
                    [{"note_id": note["id"], "url": note.get("url") or ""}],
                    f"capsule/{capsule['id']}/reply",
                )
            except BudgetExhausted:
                failed += 1
                self.db.append_event(
                    persona_id, "capsule",
                    {"capsule_id": capsule["id"], "note_id": capsule["note_id"],
                     "status": "reply_failed", "reason": "budget_exhausted"},
                    [{"note_id": capsule["note_id"]}],
                    f"capsule/{capsule['id']}/reply_failed",
                )
                self.db.add_state_snapshot(
                    persona_id, "capsules_skipped", self.esm.get_energy(persona_id), "",
                    extra=json.dumps(
                        {"reason": "budget_exhausted", "capsule_id": capsule["id"]},
                        ensure_ascii=False,
                    ),
                )
                break
            except LLMError as exc:
                failed += 1
                self.log.warning("capsule reply failed for %s: %s", persona_id, exc)
                self.db.append_event(
                    persona_id, "capsule",
                    {"capsule_id": capsule["id"], "note_id": capsule["note_id"],
                     "status": "reply_failed", "reason": str(exc)},
                    [{"note_id": capsule["note_id"]}],
                    f"capsule/{capsule['id']}/reply_failed",
                )
        return {
            "persona_id": persona_id, "ok": True,
            "opened": opened, "replied": replied, "failed": failed,
        }

    async def run_revisit(self, persona_id: str) -> dict[str, Any]:
        """Nightly light action: revisit old links and write a "what happened next" note."""
        if not self.config.enabled:
            return {"persona_id": persona_id, "ok": False, "error": "disabled"}
        if not persona_allowed(self.config, persona_id):
            return {"persona_id": persona_id, "ok": False,
                    "error": "persona_not_whitelisted"}
        try:
            persona = await self._resolve_persona(persona_id)
        except PersonaUnavailable:
            return {"persona_id": persona_id, "ok": False,
                    "error": "persona_unavailable"}
        now = local_now(self.config.timezone, self.now_fn())
        run_date = now.strftime("%Y-%m-%d")
        run_token = -random.randrange(1, 2**62)
        threshold = (
            now - timedelta(days=max(1, int(self.config.revisit_interval_days)))
        ).strftime("%Y-%m-%d")
        candidates = self.db.list_revisit_candidates(
            persona_id, threshold, limit=50
        )
        # 固定取最旧 5 条会让少数一直失败的候选堵住队列；按天确定性打乱，
        # 失败者下一晚仍有机会被轮到。
        random.Random(f"revisit:{persona_id}:{run_date}").shuffle(candidates)
        candidates = candidates[:5]
        if not candidates:
            return {"persona_id": persona_id, "ok": True,
                    "candidates": 0, "revisited": 0, "failed": 0}
        staged: list[tuple[dict, dict]] = []
        revisited = 0
        failed = 0
        for original in candidates:
            follow_ups = self.db.list_notes_by_url_hash(
                persona_id,
                str(original.get("url_hash") or ""),
                exclude_id=int(original["id"]),
                limit=10,
            )
            prompt = build_revisit_prompt(
                persona.system_prompt, persona_id,
                {
                    "title": sanitize_text(original.get("title"), 300),
                    "summary": sanitize_text(original.get("summary"), 600),
                    "opinion": sanitize_text(original.get("opinion"), 600),
                    "url": original.get("url") or "",
                    "fetched_at": original.get("fetched_at") or "",
                },
                [
                    {
                        "title": sanitize_text(note.get("title"), 300),
                        "summary": sanitize_text(note.get("summary"), 600),
                        "opinion": sanitize_text(note.get("opinion"), 600),
                        "url": note.get("url") or "",
                        "fetched_at": note.get("fetched_at") or "",
                    }
                    for note in follow_ups
                ],
            )
            try:
                payload = await self._llm_call(persona_id, prompt)
                summary = str(payload.get("summary") or "").strip()
                title = str(payload.get("title") or "").strip()
                if not summary or not title:
                    raise LLMError("revisit LLM 未返回标题或正文")
                staged.append((original, payload))
            except BudgetExhausted:
                failed += 1
                self.db.add_state_snapshot(
                    persona_id, "revisit_skipped", self.esm.get_energy(persona_id), "",
                    extra=json.dumps(
                        {"reason": "budget_exhausted",
                         "original_id": int(original["id"])},
                        ensure_ascii=False,
                    ),
                )
                break
            except LLMError as exc:
                failed += 1
                self.log.warning("revisit failed for %s: %s", persona_id, exc)
                self.db.append_event(
                    persona_id, "revisit",
                    {"original_id": int(original["id"]),
                     "status": "failed", "reason": str(exc),
                     "date": run_date},
                    [{"note_id": int(original["id"]),
                      "url": original.get("url") or ""}],
                    f"revisit/{int(original['id'])}/failed/{run_date}",
                )
        if not staged:
            return {"persona_id": persona_id, "ok": True,
                    "candidates": len(candidates), "revisited": 0,
                    "failed": failed}
        self.db.stage_snapshot(
            persona_id, run_token, "revisit", self.esm.get_energy(persona_id),
            extra=json.dumps({"count": len(staged)}, ensure_ascii=False),
        )
        for original, payload in staged:
            key = str(original.get("interest_key") or "uncategorized")
            name = str(original.get("interest_name") or key)
            self.db.stage_note(
                persona_id,
                run_token,
                source="revisit/" + str(original.get("source") or "archive"),
                url=str(original.get("url") or ""),
                title=sanitize_text(payload.get("title"), 300),
                summary=sanitize_text(payload.get("summary"), 600),
                opinion=sanitize_text(payload.get("opinion"), 600),
                mood=self._valid_mood(payload.get("mood"), "calm"),
                interest_level=_clamp(payload.get("interest_level", 0.5)),
                interest_key=key,
                interest_name=name,
                category=self._valid_category(original.get("category")),
                tags=self._valid_tags(payload.get("tags")),
                url_hash=str(original.get("url_hash") or ""),
            )
            self.db.stage_seen(persona_id, run_token, str(original.get("url_hash") or ""))
        committed = self.db.commit_staged(
            persona_id,
            run_token,
            status="completed",
            revisit_of=[int(original["id"]) for original, _ in staged],
        )
        self.interests.clear_staging(persona_id, run_token)
        for (original, payload), note in zip(staged, committed, strict=True):
            self.db.append_event(
                persona_id, "revisit",
                {"original_id": int(original["id"]),
                 "note_id": int(note["id"]),
                 "url": original.get("url") or "",
                 "title": sanitize_text(payload.get("title"), 300),
                 "source": "revisit/" + str(original.get("source") or "archive")},
                [{"note_id": int(original["id"]),
                  "url": original.get("url") or ""}],
                f"revisit/{int(original['id'])}",
            )
            if self.memory is not None and self.config.memory_host:
                try:
                    self.memory.add_note(
                        persona_id,
                        {
                            "summary": sanitize_text(payload.get("summary"), 600),
                            "opinion": sanitize_text(payload.get("opinion"), 600),
                            "url": original.get("url") or "",
                            "url_hash": original.get("url_hash") or "",
                            "category": self._valid_category(original.get("category")),
                            "revisit_of": int(original["id"]),
                        },
                    )
                except MemoryHostError as exc:
                    self.log.warning(
                        "revisit unified memory write failed for %s: %s",
                        persona_id, exc,
                    )
        if self.memory is not None and self.config.memory_host:
            try:
                self.memory.store_event(
                    persona_id, "internet-life", "", now.timestamp(),
                    "revisit", {"entity": "revisit", "count": len(staged)},
                )
            except MemoryHostError as exc:
                self.log.warning(
                    "revisit event mirror failed for %s: %s", persona_id, exc
                )
        revisited = len(committed)
        return {"persona_id": persona_id, "ok": True,
                "candidates": len(candidates), "revisited": revisited,
                "failed": failed}

    # ----- plan -----

    async def generate_plan(self, persona_id: str) -> dict[str, Any]:
        date = local_today(self.config.timezone, self.now_fn())
        if not self.config.enabled:
            return {"date": date, "accepted": [], "rejected": [],
                    "error": "disabled"}
        if not persona_allowed(self.config, persona_id):
            return {"date": date, "accepted": [], "rejected": [],
                    "error": "persona_not_whitelisted"}
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
        existing_optional = 0
        if cap > 0:
            existing_optional = sum(
                1 for row in self.db.list_plans(persona_id, date)
                if not row.get("fixed")
            )
        energy_blocked, _, energy_reason = self.esm.gate_energy(persona_id)
        now_local = local_now(self.config.timezone, self.now_fn())

        def reject(index: int, action: str, reason: str) -> None:
            rejected.append({"action": action, "reason": reason})
            self._record_plan_rejection(persona_id, date, action, index, reason)

        for index, entry in enumerate(raw_actions):
            if not isinstance(entry, dict):
                reject(index, str(entry)[:40] or "unknown", "invalid_entry")
                continue
            action = str(entry.get("action") or "").strip().lower()
            if action not in PLAN_ACTION_VOCABULARY:
                reject(index, action or "unknown", "unknown_action")
                continue
            if action not in ("browse", "diary"):
                reject(index, action, "not_supported_yet")
                continue
            if cap > 0 and existing_optional + len(accepted) >= cap:
                reject(index, action, "daily_action_cap")
                continue
            if not self._plan_dependency_ok(persona_id, date, action):
                reject(index, action, "dependency_not_met")
                continue
            scheduled = self._plan_window_time(date, entry)
            if scheduled is None:
                reject(index, action, "invalid_window")
                continue
            scheduled_dt = datetime.strptime(scheduled, "%Y-%m-%d %H:%M:%S")
            if scheduled_dt <= now_local:
                reject(index, action, "past_window")
                continue
            if self.config.sleep_window.contains(scheduled_dt):
                reject(index, action, "sleep_window")
                continue
            if energy_blocked:
                reject(index, action, f"energy_gate: {energy_reason}")
                continue
            plan_reason = sanitize_text(entry.get("reason"), 200)
            task_id = f"{action}-plan-{index + 1}"
            plan_id = self.db.add_optional_plan(
                persona_id, date, task_id, action, scheduled, reason=plan_reason,
            )
            if plan_id is None:
                reject(index, action, "duplicate")
                continue
            accepted.append({"action": action, "task_id": task_id,
                             "scheduled_at": scheduled, "reason": plan_reason})
        return {"date": date, "accepted": accepted, "rejected": rejected}

    def _record_plan_rejection(
        self, persona_id: str, plan_date: str, action: str, index: int, reason: str
    ) -> None:
        self.db.append_event(
            persona_id,
            "reject",
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
            start_raw = str(entry.get("window_start") or "").strip()
            end_raw = str(entry.get("window_end") or "").strip()
            start = datetime.strptime(f"{date} {start_raw}", "%Y-%m-%d %H:%M")
            if end_raw == "24:00":
                end = datetime.strptime(f"{date} 00:00", "%Y-%m-%d %H:%M") + timedelta(days=1)
            else:
                end = datetime.strptime(f"{date} {end_raw}", "%Y-%m-%d %H:%M")
        except (ValueError, TypeError, AttributeError):
            return None
        if end <= start:
            return None
        mid = start + (end - start) / 2
        return mid.strftime("%Y-%m-%d %H:%M:%S")
