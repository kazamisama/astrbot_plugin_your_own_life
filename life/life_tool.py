"""Agent-callable life memory query tool (query_life_memory)."""
from __future__ import annotations

import json
from typing import Any, Optional

from life.db import LifeDB
from life.persona import PersonaService

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


class _LifeMemoryToolMixin:
    def _init(self, db: LifeDB, personas: PersonaService) -> None:
        self.db = db
        self.personas = personas

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

        def __init__(self, db: LifeDB, personas: PersonaService):
            super().__init__(
                name=TOOL_NAME,
                description=TOOL_DESCRIPTION,
                parameters=TOOL_PARAMETERS,
                handler=None,
            )
            self._init(db, personas)

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

        def __init__(self, db: LifeDB, personas: PersonaService):
            self._init(db, personas)

        async def call(self, context: Any, query: str = "", category: str = "",
                       date: str = "", k: int = 5) -> str:
            return await _execute_tool(self, context, query, category, date, k)