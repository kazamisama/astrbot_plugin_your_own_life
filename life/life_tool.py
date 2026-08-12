"""Agent-callable life memory query tool (query_life_memory)."""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from life.db import LifeDB
from life.memory_adapter import MemoryHostError
from life.persona import PersonaService
from life.timeutil import DEFAULT_TIMEZONE, local_today

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
    notes = db.search_notes(persona_id, query, category, date, limit=k)
    diaries = db.search_diary(persona_id, query, category, date, limit=3)
    items: list[dict[str, Any]] = []
    for note in notes:
        items.append({
            "kind": "note",
            "date": (note.get("fetched_at") or "")[:10],
            "category": note.get("category") or "other",
            "tags": _parse_tags(note.get("tags")),
            "title": note.get("title") or "",
            "summary": note.get("summary") or "",
            "opinion": note.get("opinion") or "",
            "source": note.get("source") or "",
            "url": note.get("url") or "",
        })
    for diary in diaries:
        items.append({
            "kind": "diary",
            "date": diary.get("date") or "",
            "mood": diary.get("mood") or "",
            "content": diary.get("content") or "",
        })
    return {"persona_id": persona_id, "count": len(items), "items": items}


async def _execute_tool(tool: Any, context: Any, query: str, category: str,
                        date: str, k: int) -> str:
    persona_id = await tool._resolve_persona(context)
    if not persona_id:
        return json.dumps(
            {"ok": False, "count": 0, "error": "cannot resolve current persona"},
            ensure_ascii=False,
        )
    whitelist = getattr(getattr(tool.personas, "config", None), "life_personas", None)
    if whitelist is not None and persona_id not in whitelist:
        return json.dumps(
            {"ok": False, "count": 0, "error": "persona not whitelisted"},
            ensure_ascii=False,
        )
    data = search_life_memory(
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
        unified = []
        for item in host_items:
            mtype = item.get("memory_type") or "note"
            if mtype == "diary":
                kind = "diary"
            elif mtype == "event":
                kind = "event"
            else:
                kind = "note"
            day = ""
            try:
                day = datetime.fromtimestamp(
                    float(item.get("created_at") or 0)
                ).strftime("%Y-%m-%d")
            except (TypeError, ValueError, OSError):
                day = ""
            unified.append({
                "kind": kind,
                "date": day,
                "summary": item.get("summary") or "",
                "content": item.get("content") or "",
                "source": "unified",
                "url": "",
            })
        data["items"] = unified + data["items"]
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


async def _execute_plans_tool(tool: Any, context: Any, date: str, status: str) -> str:
    persona_id = await tool._resolve_persona(context)
    if not persona_id:
        return json.dumps(
            {"ok": False, "count": 0, "error": "cannot resolve current persona"},
            ensure_ascii=False,
        )
    whitelist = getattr(getattr(tool.personas, "config", None), "life_personas", None)
    if whitelist is not None and persona_id not in whitelist:
        return json.dumps(
            {"ok": False, "count": 0, "error": "persona not whitelisted"},
            ensure_ascii=False,
        )
    data = query_life_plans(tool.db, persona_id, date=date, status=status)
    data["ok"] = True
    data["count"] = len(data["items"])
    return json.dumps(data, ensure_ascii=False)


def _plan_time(plan_date: str, time_str: str) -> str:
    raw = (time_str or "23:59").strip()
    try:
        hour, minute = raw.split(":", 1)
        return f"{plan_date} {int(hour):02d}:{int(minute):02d}:00"
    except (ValueError, AttributeError):
        return f"{plan_date} 23:59:00"


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
) -> dict[str, Any]:
    plan_date = date or local_today(getattr(db, "timezone", DEFAULT_TIMEZONE))
    task_id = str(task_id or "").strip()[:80]
    reason = str(reason or "").strip()[:200]
    if not task_id:
        return {"ok": False, "error": "task_id required"}
    if action == "add":
        kind = str(kind or "").strip().lower()[:20]
        if kind not in ("browse", "peek", "diary"):
            return {"ok": False, "error": "kind must be browse/peek/diary"}
        scheduled_at = _plan_time(plan_date, str(time or ""))
        plan_id = db.add_optional_plan(
            persona_id, plan_date, task_id, kind, scheduled_at, reason=reason,
        )
        if plan_id is None:
            return {"ok": False, "error": "task already exists on this date"}
        return {"ok": True, "action": action, "plan_id": plan_id,
                "plan_date": plan_date, "task_id": task_id, "scheduled_at": scheduled_at}
    if action == "reorder":
        ok = db.reorder_plan(persona_id, plan_date, task_id, int(position or 1))
        return {"ok": ok, "action": action, "plan_date": plan_date,
                "task_id": task_id,
                "error": "" if ok else "cannot reorder fixed or missing task"}
    if action == "defer":
        scheduled_at = _plan_time(plan_date, str(time or ""))
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
    whitelist = getattr(getattr(tool.personas, "config", None), "life_personas", None)
    if whitelist is not None and persona_id not in whitelist:
        return json.dumps(
            {"ok": False, "error": "persona not whitelisted"},
            ensure_ascii=False,
        )
    data = edit_life_plan(
        tool.db, persona_id, action, task_id, date=date, kind=kind,
        time=time, position=position, reason=reason,
    )
    return json.dumps(data, ensure_ascii=False)


class _LifeMemoryToolMixin:
    def _init(self, db: LifeDB, personas: PersonaService,
              memory: Optional[Any] = None) -> None:
        self.db = db
        self.personas = personas
        self.memory = memory

    async def _resolve_persona(self, context: Any) -> Optional[str]:
        ctx = getattr(context, "context", context)
        event = getattr(ctx, "event", None)
        umo = ""
        if event is not None:
            umo = str(getattr(event, "unified_msg_origin", "") or "")
        if not umo:
            return None

        conv_mgr = getattr(ctx, "conversation_manager", None)
        persona_mgr = getattr(ctx, "persona_manager", None)
        if conv_mgr is not None and persona_mgr is not None:
            try:
                conv_id = await conv_mgr.get_curr_conversation_id(umo)
                if conv_id:
                    conversation = await conv_mgr.get_conversation(umo, conv_id)
                    persona_id = getattr(conversation, "persona_id", None) if conversation else None
                    if persona_id and persona_id != "[%None]":
                        return str(persona_id)
                default = await persona_mgr.get_default_persona_v3(umo=umo)
                if isinstance(default, dict):
                    name = default.get("name")
                else:
                    name = getattr(default, "name", None)
                if name:
                    return str(name)
            except Exception:
                return None
        return None

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


if _HAS_ASTRBOT_TOOL:

    class LifeMemoryTool(_LifeMemoryToolMixin, FunctionTool[AstrAgentContext]):
        """AstrBot-native FunctionTool: handler field + call(context, **kwargs)."""

        def __init__(self, db: LifeDB, personas: PersonaService,
                     memory: Optional[Any] = None):
            super().__init__(
                name=TOOL_NAME,
                description=TOOL_DESCRIPTION,
                parameters=TOOL_PARAMETERS,
                handler=None,
            )
            self._init(db, personas, memory)

        async def call(
            self,
            context: ContextWrapper[AstrAgentContext],
            query: str = "",
            category: str = "",
            date: str = "",
            k: int = 5,
        ) -> ToolExecResult:
            return await _execute_tool(self, context, query, category, date, k)

else:

    class LifeMemoryTool(_LifeMemoryToolMixin):
        """Duck-typed fallback used by unit tests outside AstrBot."""

        name = TOOL_NAME
        description = TOOL_DESCRIPTION
        parameters = TOOL_PARAMETERS

        def __init__(self, db: LifeDB, personas: PersonaService,
                     memory: Optional[Any] = None):
            self._init(db, personas, memory)

        async def call(self, context: Any, query: str = "", category: str = "",
                       date: str = "", k: int = 5) -> str:
            return await _execute_tool(self, context, query, category, date, k)


if _HAS_ASTRBOT_TOOL:

    class LifePlansTool(_LifeMemoryToolMixin, FunctionTool[AstrAgentContext]):
        """AstrBot-native read-only plan board tool."""

        def __init__(self, db: LifeDB, personas: PersonaService):
            super().__init__(
                name=PLANS_TOOL_NAME,
                description=PLANS_TOOL_DESCRIPTION,
                parameters=PLANS_TOOL_PARAMETERS,
                handler=None,
            )
            self._init(db, personas)

        async def call(
            self,
            context: ContextWrapper[AstrAgentContext],
            date: str = "",
            status: str = "",
        ) -> ToolExecResult:
            return await _execute_plans_tool(self, context, date, status)

else:

    class LifePlansTool(_LifeMemoryToolMixin):
        """Duck-typed fallback used by unit tests outside AstrBot."""

        name = PLANS_TOOL_NAME
        description = PLANS_TOOL_DESCRIPTION
        parameters = PLANS_TOOL_PARAMETERS

        def __init__(self, db: LifeDB, personas: PersonaService):
            self._init(db, personas)

        async def call(self, context: Any, date: str = "", status: str = "") -> str:
            return await _execute_plans_tool(self, context, date, status)


if _HAS_ASTRBOT_TOOL:

    class LifePlanEditTool(_LifeMemoryToolMixin, FunctionTool[AstrAgentContext]):
        """AstrBot-native optional plan mutation tool."""

        def __init__(self, db: LifeDB, personas: PersonaService):
            super().__init__(
                name=EDIT_PLAN_TOOL_NAME,
                description=EDIT_PLAN_TOOL_DESCRIPTION,
                parameters=EDIT_PLAN_TOOL_PARAMETERS,
                handler=None,
            )
            self._init(db, personas)

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

else:

    class LifePlanEditTool(_LifeMemoryToolMixin):
        """Duck-typed fallback used by unit tests outside AstrBot."""

        name = EDIT_PLAN_TOOL_NAME
        description = EDIT_PLAN_TOOL_DESCRIPTION
        parameters = EDIT_PLAN_TOOL_PARAMETERS

        def __init__(self, db: LifeDB, personas: PersonaService):
            self._init(db, personas)

        async def call(
            self, context: Any, action: str, task_id: str,
            date: str = "", kind: str = "", time: str = "", position: int = 1,
            reason: str = "",
        ) -> str:
            return await _execute_edit_plan_tool(
                self, context, action, task_id, date, kind, time, position, reason,
            )