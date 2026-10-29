"""AstrBot on_llm_request/on_llm_response hooks for life presence."""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timedelta
from typing import Any, Optional

from life.config import persona_allowed
from life.life_tool import query_life_status
from life.persona import resolve_persona_id

try:
    from astrbot.core.agent.message import TextPart
except Exception:  # pragma: no cover - unit tests without AstrBot
    TextPart = None  # type: ignore[assignment,misc]

logger = logging.getLogger("your_own_life.chat")

PRESENCE_TAG = "life-presence"
PRESENCE_MARKER = f"<{PRESENCE_TAG}>"
PRESENCE_END = f"</{PRESENCE_TAG}>"


async def resolve_event_persona(context: Any, event: Any) -> str:
    """Resolve the active persona id for an AstrBot message event."""
    return await resolve_persona_id(context, event)


def build_presence_block(status: dict[str, Any]) -> str:
    """Build the injected text block describing the persona's recent life."""
    lines = [PRESENCE_MARKER, "[最近经历]"]
    for session in (status.get("sessions") or [])[:5]:
        started = str(session.get("started_at") or "")[:16]
        lines.append(
            f"- {started} {session.get('kind') or 'browse'} "
            f"{session.get('status') or ''}"
            f"{(' ' + session.get('reason')) if session.get('reason') else ''}"
        )
    for note in (status.get("notes") or [])[:5]:
        title = note.get("title") or ""
        summary = str(note.get("summary") or "")[:80]
        lines.append(f"- 读了《{title}》：{summary}")
    for event in (status.get("events") or [])[:5]:
        lines.append(
            f"- 事件 {str(event.get('ts') or '')[:16]} {event.get('kind') or ''}"
        )
    lines.append(PRESENCE_END)
    return "\n".join(lines)


def _strip_presence_parts(parts: list[Any]) -> None:
    """Remove our own previously injected blocks from the parts list."""
    kept = []
    for part in parts:
        text = str(getattr(part, "text", "") or "")
        if PRESENCE_MARKER in text or PRESENCE_END in text:
            continue
        kept.append(part)
    parts[:] = kept


def _inject_presence(request: Any, text: str) -> bool:
    if not text:
        return False
    if hasattr(request, "extra_user_content_parts"):
        parts = request.extra_user_content_parts
        _strip_presence_parts(parts)
        if TextPart is not None:
            try:
                part = TextPart(text=text, type="text")
                mark_temp = getattr(part, "mark_as_temp", None)
                if callable(mark_temp):
                    part = mark_temp()
                parts.append(part)
                return True
            except Exception as exc:
                logger.debug("TextPart injection failed: %s", exc)
    if hasattr(request, "system_prompt"):
        request.system_prompt = (
            str(request.system_prompt or "") + "\n\n" + text
        )
        return True
    return False


def _event_message_id(event: Any) -> str:
    obj = getattr(event, "message_obj", None)
    return str(getattr(obj, "message_id", "") or "")


def _event_key(
    prefix: str, persona_id: str, session: str, text: str, message_id: str = ""
) -> str:
    # 不含时间戳：同一会话里的同一条消息重试时仍应命中同一幂等键。
    # 有上游消息 ID 时一并纳入，避免同会话里两次相同文本被当成重试。
    raw = f"{message_id}\n{text}" if message_id else str(text)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"chat/{prefix}/{persona_id}/{session}/{digest}"


async def handle_llm_request(
    context: Any,
    presence: Any,
    db: Any,
    config: Any,
    event: Any,
    request: Any,
    now_fn: Optional[Any] = None,
) -> bool:
    """Record the user message, defer while busy and inject recent life state."""
    persona_id = await resolve_event_persona(context, event)
    if not persona_id or not getattr(config, "life_presence_enabled", True):
        return False
    if not persona_allowed(config, persona_id):
        return False
    text = str(getattr(event, "message_str", "") or "").strip()
    if not text:
        return False
    extra_get = getattr(event, "get_extra", None)
    if callable(extra_get) and extra_get("yol_message_in_recorded"):
        return False
    now = (now_fn or datetime.now)()
    session = str(getattr(event, "unified_msg_origin", "") or "")
    message_id = _event_message_id(event)
    busy = presence.is_busy(persona_id) if presence is not None else None
    db.append_event(
        persona_id,
        "message_in",
        {
            "session": session,
            "text": text[:500],
            "ts": now.isoformat(),
            "deferred": bool(busy),
        },
        [],
        _event_key("in", persona_id, session, text, message_id),
        ts=now.strftime("%Y-%m-%d %H:%M:%S"),
    )
    extra_set = getattr(event, "set_extra", None)
    if callable(extra_set):
        extra_set("yol_message_in_recorded", True)
    if busy and presence is not None:
        max_wait = max(
            0.0,
            float(
                getattr(config, "busy_reply_max_wait_minutes", 30) or 30
            ) * 60,
        )
        await presence.wait_until_free(persona_id, max_wait)
        try:
            status = query_life_status(db, persona_id)
            _inject_presence(request, build_presence_block(status))
        except Exception as exc:
            logger.warning("life presence injection failed: %s", exc)
    return True


async def handle_llm_response(
    context: Any,
    presence: Any,
    db: Any,
    config: Any,
    event: Any,
    response: Any,
    now_fn: Optional[Any] = None,
) -> bool:
    """Record the bot reply and open the conversation wait window."""
    persona_id = await resolve_event_persona(context, event)
    if not persona_id or not getattr(config, "life_presence_enabled", True):
        return False
    if not persona_allowed(config, persona_id):
        return False
    text = str(
        getattr(response, "completion_text", None)
        or getattr(response, "text", None)
        or ""
    ).strip()
    if not text:
        return False
    extra_get = getattr(event, "get_extra", None)
    if callable(extra_get) and extra_get("yol_reply_out_recorded"):
        return False
    now = (now_fn or datetime.now)()
    session = str(getattr(event, "unified_msg_origin", "") or "")
    message_id = _event_message_id(event)
    db.append_event(
        persona_id,
        "reply_out",
        {
            "session": session,
            "text": text[:500],
            "ts": now.isoformat(),
        },
        [],
        _event_key("out", persona_id, session, text, message_id),
        ts=now.strftime("%Y-%m-%d %H:%M:%S"),
    )
    extra_set = getattr(event, "set_extra", None)
    if callable(extra_set):
        extra_set("yol_reply_out_recorded", True)
    if presence is not None:
        wait_minutes = max(
            0.0, float(getattr(config, "conversation_wait_minutes", 5) or 5)
        )
        if wait_minutes > 0:
            presence.set_conversation_window(
                persona_id, now + timedelta(minutes=wait_minutes)
            )
    return True
