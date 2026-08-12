"""WebUI API registration for the owner dashboard."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

from life.life_tool import _merge_unified, recall_life_memory
from life.memory_adapter import MemoryHostError
from life.timeutil import DEFAULT_TIMEZONE, local_today

PLUGIN_NAME = "astrbot_plugin_your_own_life"
API_PREFIX = f"/{PLUGIN_NAME}/api"


async def _query_args() -> dict:
    try:
        from quart import request
        return dict(request.args)
    except Exception:
        return {}


async def _json_body() -> dict:
    try:
        from quart import request
        data = await request.get_json(force=True, silent=True)
        if isinstance(data, dict):
            return data
        return dict(request.args)
    except Exception:
        return {}


def _today(config: Any) -> str:
    return local_today(getattr(config, "timezone", DEFAULT_TIMEZONE))


def _first_persona(config: Any) -> str:
    personas = getattr(config, "life_personas", None) or []
    return personas[0] if personas else "default"


def build_handlers(db: Any, service: Any, share_gate: Any, personas: Any,
                   config: Any, memory_adapter: Any = None) -> dict[str, Callable]:
    async def _persona_arg() -> str:
        args = await _query_args()
        return str(args.get("persona") or _first_persona(config))

    async def overview():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        date = args.get("date") or _today(config)
        return db.get_overview(persona, date)

    async def status():
        persona = await _persona_arg()
        return db.get_status(persona)

    async def heatmap():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        month = str(args.get("month") or _today(config)[:7])
        return db.timeline_heatmap(persona, month)

    async def timeline():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        types = [t for t in str(args.get("types") or "").split(",") if t]
        try:
            limit = max(1, min(int(args.get("limit", 50)), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = max(0, int(args.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0
        return db.timeline(persona, types=types or None, limit=limit, offset=offset)

    async def archive():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        date = args.get("date") or _today(config)
        return db.archive_for_date(persona, date)

    async def interests():
        persona = await _persona_arg()
        return {"interests": db.get_interests(persona)}

    async def run():
        args = await _json_body()
        persona = str(args.get("persona") or _first_persona(config))
        asyncio.create_task(service.run_browse_session(persona, "manual", force=True))
        return {"started": True, "persona_id": persona}

    async def memory():
        persona = await _persona_arg()
        return db.memory_overview(persona)

    async def memory_search():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        query = str(args.get("query") or "")
        category = str(args.get("category") or "")
        date = str(args.get("date") or "")
        try:
            k = max(1, min(int(args.get("k", 10)), 10))
        except (TypeError, ValueError):
            k = 10
        result = recall_life_memory(db, persona, query, category, date, k)
        if memory_adapter is not None and getattr(config, "memory_host", ""):
            try:
                host_items = memory_adapter.query_memory(
                    persona, query=query or "", k=k)
            except MemoryHostError as exc:
                result["error"] = f"memory_host: {exc}"
                return result
            result["items"] = _merge_unified(host_items, result["items"])
            result["count"] = len(result["items"])
        return result

    async def capsules():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        rows = db.list_capsules(persona, limit=200)
        notes = {
            note["id"]: note
            for note in db.list_notes(persona, limit=100000)
        }
        items = []
        for row in rows:
            note = notes.get(row["note_id"]) or {}
            items.append({
                **row,
                "title": note.get("title") or "",
                "summary": note.get("summary") or "",
                "url": note.get("url") or "",
            })
        return {"capsules": items}

    async def capsules_open():
        args = await _json_body()
        persona = str(args.get("persona") or _first_persona(config))
        try:
            capsule_id = int(args.get("capsule_id") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "capsule_id required"}
        capsule = db.get_capsule(persona, capsule_id)
        if capsule is None:
            return {"ok": False, "error": "capsule not found"}
        db.open_capsule_now(persona, capsule_id)
        if service is None:
            return {"ok": True, "capsule_id": capsule_id,
                    "status": "unlocked", "reply": ""}
        result = await service.run_capsules(persona)
        row = db.get_capsule(persona, capsule_id)
        return {
            "ok": True, "capsule_id": capsule_id,
            "status": (row or {}).get("status") or "unlocked",
            "reply": (row or {}).get("reply") or "",
            "result": result,
        }

    async def entities():
        persona = await _persona_arg()
        if memory_adapter is None or not getattr(config, "memory_host", ""):
            return {"entities": [], "links": []}
        try:
            return {
                "entities": memory_adapter.list_entities(persona),
                "links": memory_adapter.list_links(persona),
            }
        except MemoryHostError as exc:
            return {"entities": [], "links": [],
                    "error": f"memory_host: {exc}"}

    async def entity_appears_on():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        entity_id = str(args.get("entity_id") or "")
        if (memory_adapter is None
                or not getattr(config, "memory_host", "") or not entity_id):
            return {"platforms": []}
        try:
            entities = memory_adapter.list_entities(persona)
            by_id = {e["id"]: e for e in entities}
            src_ids = {
                e["id"] for e in entities if e.get("entity_id") == entity_id
            }
            platforms = []
            for link in memory_adapter.list_links(persona):
                if (link["src_entity_id"] in src_ids
                        and link["relation"] == "appears_on"):
                    dst = by_id.get(link["dst_entity_id"], {})
                    platforms.append({
                        "name": dst.get("name") or dst.get("entity_id")
                        or link["dst_entity_id"],
                        "dimension": dst.get("dimension") or "",
                    })
            return {"platforms": platforms}
        except MemoryHostError as exc:
            return {"platforms": [], "error": f"memory_host: {exc}"}

    async def usage():
        persona = await _persona_arg()
        return {"persona_id": persona, "usage": db.list_daily_usage(persona)}

    async def personas_list():
        return {"whitelist": getattr(config, "life_personas", None) or [],
                "cache": personas.list_cache()}

    async def persona_refresh():
        args = await _json_body()
        persona = str(args.get("persona") or _first_persona(config))
        try:
            await personas.refresh(persona)
            return {"ok": True, "persona_id": persona, "cached": personas.get_cached(persona)}
        except Exception as exc:
            personas.mark_error(persona, str(exc))
            return {"ok": False, "persona_id": persona, "error": str(exc)}

    async def trash():
        persona = await _persona_arg()
        return db.list_trash(persona)

    async def trash_restore():
        body = await _json_body()
        persona = str(body.get("persona") or _first_persona(config))
        entity = str(body.get("entity") or "")
        actor = str(body.get("actor") or "owner")
        reason = str(body.get("reason") or "")
        if entity == "note":
            try:
                note_id = int(body.get("id") or 0)
            except (TypeError, ValueError):
                return {"ok": False, "error": "invalid note id"}
            ok = db.restore_note(persona, note_id, actor=actor, reason=reason)
        elif entity == "diary":
            ok = db.restore_diary(persona, str(body.get("date") or ""), actor=actor, reason=reason)
        else:
            return {"ok": False, "error": "entity must be note or diary"}
        return {"ok": ok, "persona_id": persona, "entity": entity}

    async def change_log():
        persona = await _persona_arg()
        return {"persona_id": persona, "logs": db.list_change_log(persona)}

    async def plans():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        date = args.get("date") or _today(config)
        status = str(args.get("status") or "")
        return {
            "persona_id": persona,
            "plan_date": date,
            "summary": db.plan_summary(persona, date),
            "items": db.list_plans(persona, date, status or None),
        }

    async def events():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        kinds = [k for k in str(args.get("kinds") or "").split(",") if k]
        try:
            limit = max(1, min(int(args.get("limit", 50)), 200))
        except (TypeError, ValueError):
            limit = 50
        try:
            offset = max(0, int(args.get("offset", 0)))
        except (TypeError, ValueError):
            offset = 0
        return {
            "persona_id": persona,
            "kinds": kinds,
            "limit": limit,
            "offset": offset,
            "total": db.count_events(persona, kinds or None),
            "items": db.list_events(persona, kinds or None, limit, offset),
            "replay": {
                "read_only": True,
                "items": db.replay_events(persona, kinds or None, limit=20),
            },
        }

    async def injection_log():
        persona = await _persona_arg()
        return {"persona_id": persona, "logs": db.list_injection_log(persona)}

    async def wishlist():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        status = str(args.get("status") or "")
        return {"persona_id": persona, "items": db.list_wishlist(persona, status or None)}

    async def wishlist_action():
        body = await _json_body()
        persona = str(body.get("persona") or _first_persona(config))
        try:
            item_id = int(body.get("id") or 0)
        except (TypeError, ValueError):
            return {"ok": False, "error": "invalid wishlist id"}
        action = str(body.get("action") or "")
        if action not in ("promote", "discard", "pending"):
            return {"ok": False, "error": "action must be promote/discard/pending"}
        key = str(body.get("interest_key") or "")
        name = str(body.get("interest_name") or key)
        if action == "promote" and not key:
            return {"ok": False, "error": "promote requires interest_key"}
        reason = str(body.get("reason") or "owner")
        status = "promoted" if action == "promote" else ("discarded" if action == "discard" else "pending")
        ok = db.update_wishlist_status(
            persona, item_id, status, reason,
            interest_key=key, interest_name=name,
        )
        if ok and status == "promoted":
            db.upsert_interest(persona, key, name or key, 0.5, seen_count=0)
        return {"ok": ok, "persona_id": persona, "item_id": item_id, "status": status}

    async def share():
        args = await _query_args()
        persona = str(args.get("persona") or _first_persona(config))
        date = args.get("date") or _today(config)
        return {
            "persona_id": persona,
            "date": date,
            "logs": db.list_share_log(persona, date, limit=100),
            "pending": db.pending_share_notes(persona, limit=50),
            "sessions": getattr(config, "share_sessions", {}).get(persona, []),
        }

    async def share_note():
        body = await _json_body()
        persona = str(body.get("persona") or _first_persona(config))
        note_id = int(body.get("note_id") or 0)
        note = db.get_note(note_id) if note_id else None
        if note is None or note.get("persona_id") != persona:
            return {"ok": False, "error": "note not found"}
        try:
            decision = json.loads(note.get("share_decision") or "{}")
        except (ValueError, TypeError):
            decision = {}
        if not decision.get("should_share"):
            sessions = getattr(config, "share_sessions", {}).get(persona, [])
            decision = {"should_share": True, "reason": "manual",
                        "target": sessions[0] if sessions else ""}
        if share_gate is None:
            return {"ok": False, "error": "share gate disabled"}
        result = await share_gate.attempt_share(persona, note, decision)
        return {"ok": result.status == "sent", "status": result.status, "reason": result.reason}

    return {
        "overview": overview,
        "status": status,
        "heatmap": heatmap,
        "timeline": timeline,
        "archive": archive,
        "interests": interests,
        "run": run,
        "memory": memory,
        "memory_search": memory_search,
        "usage": usage,
        "personas": personas_list,
        "persona_refresh": persona_refresh,
        "trash": trash,
        "trash_restore": trash_restore,
        "change_log": change_log,
        "injection_log": injection_log,
        "plans": plans,
        "events": events,
        "share": share,
        "share_note": share_note,
        "wishlist": wishlist,
        "wishlist_action": wishlist_action,
        "capsules": capsules,
        "capsules_open": capsules_open,
        "entities": entities,
        "entity_appears_on": entity_appears_on,
    }


def register_api(context: Any, db: Any, service: Any, share_gate: Any,
                 personas: Any, config: Any,
                 memory_adapter: Any = None,
                 logger: Optional[logging.Logger] = None) -> bool:
    register = getattr(context, "register_web_api", None)
    if register is None:
        return False
    handlers = build_handlers(db, service, share_gate, personas, config,
                              memory_adapter=memory_adapter)
    routes = (
        (f"{API_PREFIX}/overview", "overview", ["GET"], "Life overview"),
        (f"{API_PREFIX}/status", "status", ["GET"], "Today status card"),
        (f"{API_PREFIX}/timeline/heatmap", "heatmap", ["GET"], "Monthly heatmap"),
        (f"{API_PREFIX}/timeline", "timeline", ["GET"], "Merged life timeline"),
        (f"{API_PREFIX}/archive", "archive", ["GET"], "Life archive"),
        (f"{API_PREFIX}/interests", "interests", ["GET"], "Life interests"),
        (f"{API_PREFIX}/run", "run", ["POST"], "Trigger a browse session"),
        (f"{API_PREFIX}/memory", "memory", ["GET"], "Memory categories overview"),
        (f"{API_PREFIX}/memory_search", "memory_search", ["GET"], "Search life memory"),
        (f"{API_PREFIX}/capsules", "capsules", ["GET"], "Time capsules"),
        (f"{API_PREFIX}/capsules_open", "capsules_open", ["POST"], "Open a time capsule"),
        (f"{API_PREFIX}/entities", "entities", ["GET"], "Life entity graph"),
        (f"{API_PREFIX}/entity_appears_on", "entity_appears_on", ["GET"], "Where an entity appears"),
        (f"{API_PREFIX}/usage", "usage", ["GET"], "Daily LLM usage"),
        (f"{API_PREFIX}/trash", "trash", ["GET"], "Trash list"),
        (f"{API_PREFIX}/trash_restore", "trash_restore", ["POST"], "Restore a trashed item"),
        (f"{API_PREFIX}/change_log", "change_log", ["GET"], "Change log"),
        (f"{API_PREFIX}/injection_log", "injection_log", ["GET"], "Injection audit log"),
        (f"{API_PREFIX}/plans", "plans", ["GET"], "Daily plan board"),
        (f"{API_PREFIX}/events", "events", ["GET"], "Event chain stream"),
        (f"{API_PREFIX}/personas", "personas", ["GET"], "Persona cache list"),
        (f"{API_PREFIX}/persona_refresh", "persona_refresh", ["POST"], "Refresh persona cache"),
        (f"{API_PREFIX}/share", "share", ["GET"], "Share log and pending"),
        (f"{API_PREFIX}/share_note", "share_note", ["POST"], "Manually share a note"),
        (f"{API_PREFIX}/wishlist", "wishlist", ["GET"], "Wishlist items"),
        (f"{API_PREFIX}/wishlist_action", "wishlist_action", ["POST"], "Promote/discard wishlist item"),
    )
    try:
        for route, handler_name, methods, desc in routes:
            register(route, handlers[handler_name], methods, desc)
        return True
    except Exception as exc:
        if logger:
            logger.warning("register_web_api failed: %s", exc)
        return False