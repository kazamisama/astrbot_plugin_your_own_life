"""Agent-callable life memory query tool (query_life_memory)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from life.config import persona_allowed
from life.db import LifeDB
from life.memory_adapter import MemoryHostError
from life.persona import PersonaService, resolve_persona_id
from life.timeutil import DEFAULT_TIMEZONE, local_now, local_today

try:
    from astrbot.core.agent.run_context import ContextWrapper
    from astrbot.core.agent.tool import FunctionTool, ToolExecResult
    from astrbot.core.astr_agent_context import AstrAgentContext

    _HAS_ASTRBOT_TOOL = True
except Exception:  # unit tests / non-AstrBot environment
    ContextWrapper = Any  # type: ignore[assignment,misc]
    FunctionTool = Any  # type: ignore[assignment,misc]
    ToolExecResult = str  # type: ignore[assignment,misc]
    AstrAgentContext = Any  # type: ignore[assignment,misc]
    _HAS_ASTRBOT_TOOL = False

CATEGORY_HINT = "observation/opinion/event/preference/plan/mood/relationship/other"

TOOL_NAME = "query_life_memory"
TOOL_DESCRIPTION = (
    "Query the current bot persona's own internet-life archive: notes, "
    "diary entries, opinions and tags. Use it when the conversation needs "
    "to recall what this persona saw, wrote or thought earlier. "
    "Returns only the current persona's records. Prefer short keywords; "
    "optionally filter by category or date."
)
TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Search keywords for notes/diaries.",
        },
        "category": {
            "type": "string",
            "description": "Optional category filter: " + CATEGORY_HINT,
            "default": "",
        },
        "date": {
            "type": "string",
            "description": "Optional date filter, YYYY-MM-DD.",
            "default": "",
        },
        "k": {
            "type": "integer",
            "description": "Maximum number of items to return (1-10).",
            "default": 5,
        },
    },
    "required": ["query"],
}

PLANS_TOOL_NAME = "query_life_plans"
PLANS_TOOL_DESCRIPTION = (
    "Query the current bot persona's daily life plan board: scheduled life tasks, "
    "their status (done/pending/skipped/failed), reason and budget used. "
    "Use it before planning today's activities or when checking whether a life task finished."
)
PLANS_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "date": {
            "type": "string",
            "description": "Optional plan date, YYYY-MM-DD; defaults to today.",
            "default": "",
        },
        "status": {
            "type": "string",
            "description": "Optional status filter: done/pending/skipped/failed.",
            "default": "",
        },
    },
    "required": [],
}

EDIT_PLAN_TOOL_NAME = "edit_life_plan"
EDIT_PLAN_TOOL_DESCRIPTION = (
    "Modify the current bot persona's optional life plan tasks. "
    "Actions: add (create a pending optional task), reorder (move an optional task to a 1-based position), "
    "defer (move an optional task to another time), skip (mark an optional task skipped with a reason). "
    "Fixed system tasks cannot be modified."
)
EDIT_PLAN_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["add", "reorder", "defer", "skip"]},
        "date": {
            "type": "string",
            "description": "Plan date, YYYY-MM-DD; defaults to today.",
            "default": "",
        },
        "task_id": {"type": "string", "description": "Task id, e.g. browse-extra-1."},
        "kind": {
            "type": "string",
            "description": "Task kind for add: browse/peek/diary.",
            "default": "",
        },
        "time": {
            "type": "string",
            "description": "Scheduled time HH:MM for add/defer.",
            "default": "",
        },
        "position": {
            "type": "integer",
            "description": "1-based target position for reorder.",
            "default": 1,
        },
        "reason": {"type": "string", "description": "Reason for add/defer/skip.", "default": ""},
    },
    "required": ["action", "task_id"],
}

EDIT_MEMORY_TOOL_NAME = "edit_life_memory"
EDIT_MEMORY_TOOL_DESCRIPTION = (
    "Edit the current bot persona's life memory or interests, or roll back a previous edit. "
    "Allowed fields are whitelisted (e.g. note.summary, note.opinion, interest.weight); "
    "anything outside the whitelist requires owner confirmation in the WebUI and returns "
    "needs_owner_confirmation."
)
EDIT_MEMORY_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "action": {"type": "string", "enum": ["update", "rollback"]},
        "entity": {
            "type": "string",
            "description": "Entity to change: note / interest.",
        },
        "entity_id": {
            "type": "string",
            "description": "Note id or interest key.",
        },
        "field": {
            "type": "string",
            "description": "Field to change: title/summary/opinion (note) or weight/name (interest).",
        },
        "value": {
            "type": "string",
            "description": "New value (JSON string for weight).",
            "default": "",
        },
        "change_id": {
            "type": "integer",
            "description": "change_log id for action=rollback.",
            "default": 0,
        },
        "reason": {"type": "string", "description": "Reason for the edit.", "default": ""},
    },
    "required": ["action"],
}

STATUS_TOOL_NAME = "query_life_status"
STATUS_TOOL_DESCRIPTION = (
    "Query the current bot persona's recent life activity: today's browse/peek "
    "sessions, state snapshots, recent event-chain entries and notes. "
    "Use it when the conversation asks what this persona was doing, what it read, "
    "or how the day went. Returns only the current persona's records."
)
STATUS_TOOL_PARAMETERS: dict[str, Any] = {
    "type": "object",
    "properties": {
        "date": {
            "type": "string",
            "description": "Optional date filter, YYYY-MM-DD; defaults to today.",
            "default": "",
        },
        "limit": {
            "type": "integer",
            "description": "Maximum items per section (1-50).",
            "default": 10,
        },
    },
    "required": [],
}


def _parse_tags(raw: Any) -> list[str]:
    if isinstance(raw, list):
        return [str(t) for t in raw]
    try:
        parsed = json.loads(raw or "[]")
        return [str(t) for t in parsed] if isinstance(parsed, list) else []
    except (ValueError, TypeError):
        return []


def search_life_memory(
    db: LifeDB,
    persona_id: str,
    query: str = "",
    category: str = "",
    date: str = "",
    k: int = 5,
) -> dict[str, Any]:
    """Search the current persona's notes + diaries; pure function for tests."""
    k = max(1, min(int(k or 5), 10))
    notes = db.search_notes(
        persona_id, query, category, date, limit=k, temperature_weighted=True
    )
    diaries = db.search_diary(persona_id, query=query, date=date, limit=3)
    items: list[dict[str, Any]] = []
    for note in notes:
        items.append({
            "kind": "note",
            "id": note.get("id"),
            "date": (note.get("fetched_at") or "")[:10],
            "category": note.get("category") or "other",
            "tags": _parse_tags(note.get("tags")),
            "title": note.get("title") or "",
            "summary": note.get("summary") or "",
            "opinion": note.get("opinion") or "",
            "source": note.get("source") or "",
            "url": note.get("url") or "",
            "temperature": note.get("temperature"),
        })
    for diary in diaries:
        items.append({
            "kind": "diary",
            "date": diary.get("date") or "",
            "mood": diary.get("mood") or "",
            "content": diary.get("content") or "",
        })
    return {"persona_id": persona_id, "count": len(items), "items": items}


def recall_life_memory(
    db: LifeDB,
    persona_id: str,
    query: str = "",
    category: str = "",
    date: str = "",
    k: int = 5,
) -> dict[str, Any]:
    """Search life memory and rehydrate recalled notes back to full warmth."""
    data = search_life_memory(db, persona_id, query=query, category=category,
                              date=date, k=k)
    ids = [
        int(item["id"]) for item in data["items"]
        if item.get("kind") == "note" and item.get("id")
    ]
    db.rehydrate_notes(ids)
    return data


def _merge_unified(
    host_items: list[dict], local_items: list[dict], limit: int = 10
) -> list[dict]:
    """Merge host recall with the local archive, deduplicated and capped."""
    merged: dict[tuple[str, str, str], dict[str, Any]] = {}
    for item in list(local_items) + list(host_items):
        kind = str(item.get("kind") or item.get("memory_type") or "note")
        if kind not in ("note", "diary", "event"):
            kind = "note"
        summary = str(item.get("summary") or "")
        content = str(item.get("content") or "")
        key = (
            kind,
            " ".join(summary.lower().split()),
            " ".join(content.lower().split()),
        )
        if key in merged:
            # 本地条目带 id/url，始终保留；重复的 host 条目只抬高温度。
            merged[key]["temperature"] = max(
                float(merged[key].get("temperature") or 0.5),
                float(item.get("temperature") or 0.5),
            )
            continue
        row = dict(item)
        row["kind"] = kind
        if not row.get("date") and item.get("created_at"):
            try:
                row["date"] = datetime.fromtimestamp(
                    float(item.get("created_at") or 0)
                ).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                row["date"] = ""
        row.setdefault("date", "")
        row.setdefault("source", "unified")
        row.setdefault("url", "")
        row["temperature"] = float(item.get("temperature") or 0.5)
        merged[key] = row
    items = list(merged.values())
    items.sort(
        key=lambda item: float(item.get("temperature") or 0.5), reverse=True
    )
    return items[: max(1, int(limit or 1))]


async def _execute_tool(tool: Any, context: Any, query: str, category: str,
                        date: str, k: int) -> str:
    persona_id = await tool._resolve_persona(context)
    if not persona_id:
        return json.dumps(
            {"ok": False, "count": 0, "error": "cannot resolve current persona"},
            ensure_ascii=False,
        )
    if not persona_allowed(getattr(tool.personas, "config", None), persona_id):
        return json.dumps(
            {"ok": False, "count": 0, "error": "persona not whitelisted"},
            ensure_ascii=False,
        )
    data = recall_life_memory(
        tool.db, persona_id, query=query, category=category, date=date, k=k
    )
    memory = getattr(tool, "memory", None)
    memory_host = getattr(
        getattr(getattr(tool, "personas", None), "config", None),
        "memory_host", "",
    )
    if memory is not None and memory_host:
        try:
            host_items = memory.query_memory(persona_id, query=query or "", k=k)
        except MemoryHostError as exc:
            return json.dumps(
                {"ok": False, "count": 0, "error": f"memory_host: {exc}"},
                ensure_ascii=False,
            )
        data["items"] = _merge_unified(host_items, data["items"], limit=k)
        data["count"] = len(data["items"])
    tool.db.append_event(
        persona_id,
        "recall",
        {"query": query, "category": category, "date": date, "k": k,
         "count": data["count"]},
        [
            {"url": item.get("url")}
            for item in data["items"]
            if item.get("url")
        ],
    )
    data["ok"] = True
    return json.dumps(data, ensure_ascii=False)


def query_life_plans(
    db: LifeDB,
    persona_id: str,
    date: str = "",
    status: str = "",
) -> dict[str, Any]:
    """Read-only plan board query; pure function for tests."""
    plan_date = date or local_today(getattr(db, "timezone", DEFAULT_TIMEZONE))
    return {
        "persona_id": persona_id,
        "plan_date": plan_date,
        "summary": db.plan_summary(persona_id, plan_date),
        "items": db.list_plans(persona_id, plan_date, status or None),
    }


def _json_value(raw: Any, fallback: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw or "{}")
    except (ValueError, TypeError):
        return fallback


def query_life_status(
    db: LifeDB,
    persona_id: str,
    date: str = "",
    limit: int = 10,
) -> dict[str, Any]:
    """Read-only recent life activity snapshot; pure function for tests."""
    limit = max(1, min(int(limit or 10), 50))
    plan_date = date or local_today(getattr(db, "timezone", DEFAULT_TIMEZONE))
    sessions = db.list_sessions(persona_id, plan_date, limit=limit)
    snapshots = db.list_state_snapshots(
        persona_id, since_date=plan_date, limit=limit
    )
    notes = db.list_notes(persona_id, plan_date, limit=limit)
    events = db.list_events_on_date(persona_id, plan_date, limit=limit)
    stats = {
        "sessions": db.count_sessions(persona_id, plan_date, exclude_kind="peek"),
        "notes": db.count_notes(persona_id, plan_date),
        "completed": db.count_sessions(
            persona_id, plan_date, exclude_kind="peek", status="completed"
        ),
        "skipped": db.count_sessions(
            persona_id, plan_date, exclude_kind="peek", status="skipped%"
        ),
        "errors": (
            db.count_sessions(
                persona_id, plan_date, exclude_kind="peek", status="error"
            )
            + db.count_sessions(
                persona_id, plan_date, exclude_kind="peek", status="failed"
            )
        ),
    }
    return {
        "persona_id": persona_id,
        "date": plan_date,
        "mood": next(
            (s.get("mood") or "" for s in snapshots if s.get("mood")), ""
        ),
        "energy": next(
            (s.get("energy") for s in snapshots if s.get("energy") is not None),
            None,
        ),
        "stats": stats,
        "sessions": [
            {
                "started_at": s.get("started_at") or "",
                "ended_at": s.get("ended_at") or "",
                "trigger": s.get("trigger") or "",
                "kind": s.get("kind") or "browse",
                "status": s.get("status") or "",
                "notes_count": s.get("notes_count") or 0,
                "reason": s.get("reason") or "",
            }
            for s in sessions
        ],
        "snapshots": [
            {
                "ts": s.get("ts") or "",
                "activity": s.get("activity") or "",
                "energy": s.get("energy"),
                "mood": s.get("mood") or "",
                "extra": _json_value(s.get("extra"), {}),
            }
            for s in snapshots
        ],
        "events": [
            {
                "id": e.get("id"),
                "ts": e.get("ts") or "",
                "kind": e.get("kind") or "",
                "payload": _json_value(e.get("payload"), {}),
                "source_refs": _json_value(e.get("source_refs"), []),
            }
            for e in events
        ],
        "notes": [
            {
                "id": n.get("id"),
                "fetched_at": n.get("fetched_at") or "",
                "source": n.get("source") or "",
                "title": n.get("title") or "",
                "summary": n.get("summary") or "",
                "url": n.get("url") or "",
            }
            for n in notes
        ],
    }


async def _execute_plans_tool(tool: Any, context: Any, date: str, status: str) -> str:
    persona_id = await tool._resolve_persona(context)
    if not persona_id:
        return json.dumps(
            {"ok": False, "count": 0, "error": "cannot resolve current persona"},
            ensure_ascii=False,
        )
    if not persona_allowed(getattr(tool.personas, "config", None), persona_id):
        return json.dumps(
            {"ok": False, "count": 0, "error": "persona not whitelisted"},
            ensure_ascii=False,
        )
    data = query_life_plans(tool.db, persona_id, date=date, status=status)
    data["ok"] = True
    data["count"] = len(data["items"])
    return json.dumps(data, ensure_ascii=False)


async def _execute_status_tool(tool: Any, context: Any, date: str,
                               limit: int) -> str:
    persona_id = await tool._resolve_persona(context)
    if not persona_id:
        return json.dumps(
            {"ok": False, "count": 0, "error": "cannot resolve current persona"},
            ensure_ascii=False,
        )
    if not persona_allowed(getattr(tool.personas, "config", None), persona_id):
        return json.dumps(
            {"ok": False, "count": 0, "error": "persona not whitelisted"},
            ensure_ascii=False,
        )
    data = query_life_status(tool.db, persona_id, date=date, limit=limit)
    count = (
        len(data["sessions"]) + len(data["snapshots"])
        + len(data["events"]) + len(data["notes"])
    )
    tool.db.append_event(
        persona_id,
        "recall",
        {"query": "life_status", "date": data["date"], "limit": limit,
         "count": count},
        [],
    )
    data["ok"] = True
    data["count"] = count
    return json.dumps(data, ensure_ascii=False)


def _plan_time(plan_date: str, time_str: str) -> Optional[str]:
    raw = (time_str or "23:59").strip()
    try:
        parsed = datetime.strptime(f"{plan_date} {raw}", "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None
    return parsed.strftime("%Y-%m-%d %H:%M:%S")


def edit_life_plan(
    db: LifeDB,
    persona_id: str,
    action: str,
    task_id: str,
    date: str = "",
    kind: str = "",
    time: str = "",
    position: int = 1,
    reason: str = "",
    config: Optional[Any] = None,
    esm: Optional[Any] = None,
) -> dict[str, Any]:
    plan_date = date or local_today(getattr(db, "timezone", DEFAULT_TIMEZONE))
    try:
        datetime.strptime(plan_date, "%Y-%m-%d")
    except (TypeError, ValueError):
        return {"ok": False, "error": "date must be YYYY-MM-DD"}
    task_id = str(task_id or "").strip()[:80]
    reason = str(reason or "").strip()[:200]
    if not task_id:
        return {"ok": False, "error": "task_id required"}

    def slot_error(scheduled_at: str) -> str:
        if config is None:
            return ""
        try:
            slot_dt = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M:%S")
        except (TypeError, ValueError):
            return "invalid_time"
        tz = getattr(config, "timezone", DEFAULT_TIMEZONE)
        if slot_dt <= local_now(tz):
            return "past_window"
        window = getattr(config, "sleep_window", None)
        if window is not None and window.contains(slot_dt):
            return "sleep_window"
        return ""

    if action == "add":
        kind = str(kind or "").strip().lower()[:20]
        if kind not in ("browse", "peek", "diary"):
            return {"ok": False, "error": "kind must be browse/peek/diary"}
        scheduled_at = _plan_time(plan_date, str(time or ""))
        if scheduled_at is None:
            return {"ok": False, "error": "time must be HH:MM within the day"}
        invalid = slot_error(scheduled_at)
        if invalid:
            return {"ok": False, "error": invalid}
        if esm is not None:
            blocked, _energy, gate_reason = esm.gate_energy(persona_id)
            if blocked:
                return {"ok": False, "error": gate_reason or "energy_gate"}
        if config is not None:
            cap = int(getattr(config, "plan_daily_action_cap", 0) or 0)
            optional = [
                row for row in db.list_plans(persona_id, plan_date)
                if not row.get("fixed")
            ]
            if cap > 0 and len(optional) >= cap:
                return {"ok": False, "error": "daily_action_cap"}
            if kind == "diary" and not db.list_notes(persona_id, plan_date, limit=1):
                return {"ok": False, "error": "dependency_not_met"}
        plan_id = db.add_optional_plan(
            persona_id, plan_date, task_id, kind, scheduled_at, reason=reason,
        )
        if plan_id is None:
            return {"ok": False, "error": "task already exists on this date"}
        return {"ok": True, "action": action, "plan_id": plan_id,
                "plan_date": plan_date, "task_id": task_id, "scheduled_at": scheduled_at}
    if action == "reorder":
        try:
            new_position = int(position or 1)
        except (TypeError, ValueError):
            return {"ok": False, "error": "position must be an integer"}
        ok = db.reorder_plan(persona_id, plan_date, task_id, new_position)
        return {"ok": ok, "action": action, "plan_date": plan_date,
                "task_id": task_id,
                "error": "" if ok else "cannot reorder fixed or missing task"}
    if action == "defer":
        scheduled_at = _plan_time(plan_date, str(time or ""))
        if scheduled_at is None:
            return {"ok": False, "error": "time must be HH:MM within the day"}
        invalid = slot_error(scheduled_at)
        if invalid:
            return {"ok": False, "error": invalid}
        ok = db.defer_plan(persona_id, plan_date, task_id, scheduled_at, reason=reason)
        return {"ok": ok, "action": action, "plan_date": plan_date,
                "task_id": task_id, "scheduled_at": scheduled_at,
                "error": "" if ok else "cannot defer fixed or missing task"}
    if action == "skip":
        ok = db.skip_plan(persona_id, plan_date, task_id, reason=reason or "llm_skip")
        return {"ok": ok, "action": action, "plan_date": plan_date,
                "task_id": task_id,
                "error": "" if ok else "cannot skip fixed or missing task"}
    return {"ok": False, "error": "action must be add/reorder/defer/skip"}


async def _execute_edit_plan_tool(
    tool: Any, context: Any, action: str, task_id: str,
    date: str, kind: str, time: str, position: int, reason: str,
) -> str:
    persona_id = await tool._resolve_persona(context)
    if not persona_id:
        return json.dumps(
            {"ok": False, "error": "cannot resolve current persona"},
            ensure_ascii=False,
        )
    if not persona_allowed(getattr(tool.personas, "config", None), persona_id):
        return json.dumps(
            {"ok": False, "error": "persona not whitelisted"},
            ensure_ascii=False,
        )
    data = edit_life_plan(
        tool.db, persona_id, action, task_id, date=date, kind=kind,
        time=time, position=position, reason=reason,
        config=getattr(tool.personas, "config", None),
        esm=getattr(tool, "esm", None),
    )
    return json.dumps(data, ensure_ascii=False)


_NOTE_FIELD_LIMITS = {"title": 300, "summary": 600, "opinion": 600}


def _interest_current(db: LifeDB, persona_id: str, key: str) -> Optional[dict]:
    for row in db.get_interests(persona_id):
        if row["key"] == key:
            return row
    return None


def edit_life_memory(
    db: LifeDB,
    persona_id: str,
    action: str,
    entity: str = "",
    entity_id: str = "",
    field: str = "",
    value: str = "",
    change_id: int = 0,
    allowed: Optional[list] = None,
    reason: str = "",
    actor: str = "llm",
) -> dict[str, Any]:
    action = str(action or "").strip().lower()
    entity = str(entity or "").strip().lower()
    field = str(field or "").strip().lower()
    allowed = set(str(item) for item in (allowed or []))
    reason = str(reason or "").strip()[:200]

    if action == "rollback":
        try:
            log_id = int(change_id or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "change_id required"}
        row = db.get_change_log_entry(persona_id, log_id)
        if row is None or row.get("status") != "applied":
            return {"ok": False,
                    "error": "cannot rollback (missing or not applied)"}
        if str(row.get("actor") or "") != actor:
            return {"ok": False,
                    "error": "cannot rollback another actor's change"}
        row = db.rollback_change(persona_id, log_id, actor=actor)
        if row is None:
            return {"ok": False,
                    "error": "cannot rollback (missing or not applied)"}
        return {"ok": True, "action": "rollback", "change_id": log_id,
                "status": "rolled_back"}
    if action != "update":
        return {"ok": False, "error": "action must be update/rollback"}

    if entity == "note":
        try:
            note_id = int(entity_id or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "note_id required"}
        note = db.get_note(note_id)
        if note is None or note.get("persona_id") != persona_id:
            return {"ok": False, "error": "note not found"}
        if field not in ("title", "summary", "opinion"):
            return {"ok": False, "error": "field must be title/summary/opinion"}
        old = str(note.get(field) or "")
        new = str(value or "")[:_NOTE_FIELD_LIMITS[field]]
        old_payload = json.dumps({"field": field, "value": old}, ensure_ascii=False)
        new_payload = json.dumps({"field": field, "value": new}, ensure_ascii=False)
        key = f"note.{field}"
        if key not in allowed:
            log_id = db.log_change(
                persona_id, "note", note_id, old_payload, new_payload,
                actor=actor, reason=reason, status="pending_owner",
            )
            return {"ok": False, "needs_owner_confirmation": True,
                    "change_id": log_id, "error": "requires owner confirmation"}
        db.update_note_field(persona_id, note_id, field, new)
        log_id = db.log_change(
            persona_id, "note", note_id, old_payload, new_payload,
            actor=actor, reason=reason, status="applied",
        )
        return {"ok": True, "action": "update", "entity": "note",
                "entity_id": note_id, "field": field, "change_id": log_id}

    if entity == "interest":
        key = str(entity_id or "").strip()
        current = _interest_current(db, persona_id, key)
        if current is None:
            return {"ok": False, "error": "interest not found"}
        if field not in ("weight", "name"):
            return {"ok": False, "error": "field must be weight/name"}
        old_weight = float(current["weight"] or 0)
        old_name = str(current["name"] or key)
        if field == "weight":
            try:
                new_weight = max(0.0, min(1.0, float(value)))
            except (TypeError, ValueError):
                return {"ok": False, "error": "weight must be numeric"}
            new_name = old_name
        else:
            new_name = str(value or "").strip()[:40] or key
            new_weight = old_weight
        old_payload = json.dumps(
            {"key": key, "name": old_name, "weight": old_weight},
            ensure_ascii=False,
        )
        new_payload = json.dumps(
            {"key": key, "name": new_name, "weight": new_weight},
            ensure_ascii=False,
        )
        edit_key = f"interest.{field}"
        if edit_key not in allowed:
            log_id = db.log_change(
                persona_id, "interest", key, old_payload, new_payload,
                actor=actor, reason=reason, status="pending_owner",
            )
            return {"ok": False, "needs_owner_confirmation": True,
                    "change_id": log_id, "error": "requires owner confirmation"}
        db.upsert_interest(
            persona_id, key, new_name, new_weight,
            seen_count=int(current.get("seen_count") or 0),
        )
        log_id = db.log_change(
            persona_id, "interest", key, old_payload, new_payload,
            actor=actor, reason=reason, status="applied",
        )
        return {"ok": True, "action": "update", "entity": "interest",
                "entity_id": key, "field": field, "change_id": log_id}

    return {"ok": False, "error": "entity must be note/interest"}


async def _execute_edit_memory_tool(
    tool: Any, context: Any, action: str, entity: str, entity_id: str,
    field: str, value: str, change_id: int, reason: str,
) -> str:
    persona_id = await tool._resolve_persona(context)
    if not persona_id:
        return json.dumps(
            {"ok": False, "error": "cannot resolve current persona"},
            ensure_ascii=False,
        )
    if not persona_allowed(getattr(tool.personas, "config", None), persona_id):
        return json.dumps(
            {"ok": False, "error": "persona not whitelisted"},
            ensure_ascii=False,
        )
    data = edit_life_memory(
        tool.db, persona_id, action, entity=entity, entity_id=entity_id,
        field=field, value=value, change_id=int(change_id or 0),
        allowed=getattr(tool, "allowed", None) or [],
        reason=reason, actor="llm",
    )
    change_id = data.get("change_id")
    if data.get("ok"):
        status = "applied" if action == "update" else "rolled_back"
    elif data.get("needs_owner_confirmation"):
        status = "pending_owner"
    else:
        status = "rejected"
    if change_id:
        tool.db.append_event(
            persona_id, "change",
            {"entity": "memory", "action": action, "status": status,
             "detail": data},
            [],
            f"llm_edit/{action}/{change_id}/{status}",
        )
    return json.dumps(data, ensure_ascii=False)


class _LifeMemoryToolMixin:
    def _init(self, db: LifeDB, personas: PersonaService,
              memory: Optional[Any] = None,
              esm: Optional[Any] = None) -> None:
        self.db = db
        self.personas = personas
        self.memory = memory
        self.esm = esm

    async def _resolve_persona(self, context: Any) -> Optional[str]:
        persona_id = await resolve_persona_id(context)
        return persona_id or None

    def register(self, context: Any) -> bool:
        for method_name in ("add_llm_tools", "register_tool"):
            fn = getattr(context, method_name, None)
            if callable(fn):
                try:
                    fn(self)
                    return True
                except Exception:
                    continue
        return False


_ToolBase = FunctionTool[AstrAgentContext] if _HAS_ASTRBOT_TOOL else object


class _LifeToolBase(_LifeMemoryToolMixin, _ToolBase):
    """Shared FunctionTool/fallback base for the five life tools.

    AstrBot needs the FunctionTool dataclass fields at construction time;
    unit tests and non-AstrBot environments only need the duck-typed call
    surface.  Keeping the conditional here removes the ten near-identical
    class definitions that used to sit below.
    """

    name = ""
    description = ""
    parameters: dict[str, Any] = {}

    def __init__(self, db: LifeDB, personas: PersonaService,
                 esm: Optional[Any] = None) -> None:
        if _HAS_ASTRBOT_TOOL:
            super().__init__(
                name=self.name,
                description=self.description,
                parameters=self.parameters,
                handler=None,
            )
        self._init(db, personas, esm=esm)


class LifeMemoryTool(_LifeToolBase):
    """Query the current persona's life archive."""

    name = TOOL_NAME
    description = TOOL_DESCRIPTION
    parameters = TOOL_PARAMETERS

    def __init__(self, db: LifeDB, personas: PersonaService,
                 memory: Optional[Any] = None):
        super().__init__(db, personas)
        self.memory = memory

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        query: str = "",
        category: str = "",
        date: str = "",
        k: int = 5,
    ) -> ToolExecResult:
        return await _execute_tool(self, context, query, category, date, k)


class LifePlansTool(_LifeToolBase):
    """Read the current persona's daily plan board."""

    name = PLANS_TOOL_NAME
    description = PLANS_TOOL_DESCRIPTION
    parameters = PLANS_TOOL_PARAMETERS

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        date: str = "",
        status: str = "",
    ) -> ToolExecResult:
        return await _execute_plans_tool(self, context, date, status)


class LifeStatusTool(_LifeToolBase):
    """Read the current persona's recent life activity."""

    name = STATUS_TOOL_NAME
    description = STATUS_TOOL_DESCRIPTION
    parameters = STATUS_TOOL_PARAMETERS

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        date: str = "",
        limit: int = 10,
    ) -> ToolExecResult:
        return await _execute_status_tool(self, context, date, limit)


class LifePlanEditTool(_LifeToolBase):
    """Add, reorder, defer or skip optional plan tasks."""

    name = EDIT_PLAN_TOOL_NAME
    description = EDIT_PLAN_TOOL_DESCRIPTION
    parameters = EDIT_PLAN_TOOL_PARAMETERS

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        action: str,
        task_id: str,
        date: str = "",
        kind: str = "",
        time: str = "",
        position: int = 1,
        reason: str = "",
    ) -> ToolExecResult:
        return await _execute_edit_plan_tool(
            self, context, action, task_id, date, kind, time, position, reason,
        )


class LifeEditTool(_LifeToolBase):
    """Edit or roll back the current persona's memory/interests."""

    name = EDIT_MEMORY_TOOL_NAME
    description = EDIT_MEMORY_TOOL_DESCRIPTION
    parameters = EDIT_MEMORY_TOOL_PARAMETERS

    def __init__(self, db: LifeDB, personas: PersonaService,
                 allowed: Optional[list] = None):
        super().__init__(db, personas)
        self.allowed = list(allowed or [])

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        action: str,
        entity: str = "",
        entity_id: str = "",
        field: str = "",
        value: str = "",
        change_id: int = 0,
        reason: str = "",
    ) -> ToolExecResult:
        return await _execute_edit_memory_tool(
            self, context, action, entity, entity_id, field, value,
            change_id, reason,
        )