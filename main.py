"""AstrBot plugin entry: Your Own Life - per-persona internet life archive."""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from typing import Any

_PLUGIN_DIR = os.path.dirname(os.path.abspath(__file__))
if _PLUGIN_DIR not in sys.path:
    sys.path.insert(0, _PLUGIN_DIR)


def _purge_stale_life_modules() -> None:
    """Drop previously cached copies of this plugin's life.* modules.

    AstrBot plugin reloads may keep stale sys.modules entries from an older
    version of this plugin; purging them forces a fresh read from disk.
    """
    for name in list(sys.modules):
        if name == "life" or name.startswith("life."):
            mod = sys.modules.get(name)
            path = getattr(mod, "__file__", "") or ""
            if path.startswith(_PLUGIN_DIR):
                del sys.modules[name]


_purge_stale_life_modules()

from astrbot.api import logger  # noqa: E402
from astrbot.api.event import AstrMessageEvent, filter  # noqa: E402
from astrbot.api.star import Context, Star  # noqa: E402
from astrbot.core.config.astrbot_config import AstrBotConfig  # noqa: E402
from astrbot.core.message.components import Plain  # noqa: E402
from astrbot.core.message.message_event_result import MessageChain  # noqa: E402

from life.browser import LifeService  # noqa: E402
from life.config import LifeConfig, load_config  # noqa: E402
from life.db import LifeDB  # noqa: E402
from life.esm_adapter import ESMAdapter  # noqa: E402
from life.memory_adapter import LifeMemoryAdapter  # noqa: E402
from life.interests import InterestStore  # noqa: E402
from life.life_tool import (  # noqa: E402
    LifeEditTool,
    LifeMemoryTool,
    LifePlanEditTool,
    LifePlansTool,
    LifeStatusTool,
)
from life.chat_hooks import handle_llm_request, handle_llm_response  # noqa: E402
from life.llm import LLMClient  # noqa: E402
from life.persona import PersonaService, PersonaUnavailable  # noqa: E402
from life.presence import LifePresence  # noqa: E402
from life.scheduler import LifeScheduler  # noqa: E402
from life.share import ShareGate  # noqa: E402
from life.timeutil import DEFAULT_TIMEZONE, local_today  # noqa: E402
from life import webui  # noqa: E402

PLUGIN_NAME = "astrbot_plugin_your_own_life"
_DEFAULT_DB = f"data/plugin_data/{PLUGIN_NAME}/life.db"
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LifeStar(Star):
    def __init__(self, context: Context, config: AstrBotConfig):
        super().__init__(context)
        self._cfg: LifeConfig = load_config(config)
        if self._cfg.timezone_error:
            logger.warning("timezone 配置非法，已回退默认时区 %s", DEFAULT_TIMEZONE)
        db_path = self._cfg.db_path or _DEFAULT_DB
        self.db = LifeDB(db_path, timezone=self._cfg.timezone)
        self.personas = PersonaService(context, self.db, self._cfg, logger=logger)
        self.esm = ESMAdapter(
            context,
            scope_prefix=self._cfg.esm_scope_prefix,
            energy_gate=self._cfg.energy_gate,
        )
        self.memory = (
            LifeMemoryAdapter(context, host_id=self._cfg.memory_host)
            if self._cfg.memory_host else None
        )
        self.llm = LLMClient(context, provider_id=self._cfg.life_llm)
        self.presence = LifePresence()
        self.interests = InterestStore(
            self.db,
            initial=self._cfg.interests_initial,
            decay=self._cfg.interest_decay,
        )
        for persona_id in self._cfg.life_personas:
            self.interests.seed(persona_id)
        self.share_gate = ShareGate(
            self._cfg, self.db, self.esm, self.llm, self.personas,
            sender=self._send_message, logger=logger, now_fn=datetime.now,
        )
        self.service = LifeService(
            self._cfg, self.db, self.interests, self.esm, self.llm,
            self.personas, share_gate=self.share_gate, memory=self.memory,
            logger=logger, now_fn=datetime.now, presence=self.presence,
        )
        self.scheduler = LifeScheduler(
            self.service, self._cfg, logger=logger, now_fn=datetime.now,
            presence=self.presence,
        )
        self.scheduler.start()
        self.life_tool = LifeMemoryTool(self.db, self.personas, memory=self.memory)
        self.life_plans_tool = LifePlansTool(self.db, self.personas)
        self.life_status_tool = LifeStatusTool(self.db, self.personas)
        self.life_plan_edit_tool = LifePlanEditTool(self.db, self.personas)
        self.life_edit_tool = LifeEditTool(
            self.db, self.personas, allowed=self._cfg.life_edit_allowed
        )
        if self._cfg.life_tool_enabled:
            self.life_tool.register(context)
            self.life_plans_tool.register(context)
            self.life_status_tool.register(context)
            self.life_plan_edit_tool.register(context)
            self.life_edit_tool.register(context)
        webui.register_api(context, self.db, self.service, self.share_gate,
                           self.personas, self._cfg, self.memory, logger)

    async def terminate(self):
        try:
            await self.scheduler.stop()
        except Exception as exc:
            logger.warning("scheduler stop failed: %s", exc)
        try:
            self.db.close()
        except Exception as exc:
            logger.warning("db close failed: %s", exc)

    # ----- helpers -----

    async def _send_message(self, session_id: str, text: str) -> bool:
        try:
            sent = await self.context.send_message(
                session_id, MessageChain([Plain(text=text)])
            )
            return bool(sent)
        except Exception as exc:
            logger.warning("send_message to %s failed: %s", session_id, exc)
            return False

    def _default_persona(self) -> str:
        personas = self._cfg.life_personas
        return personas[0] if personas else "default"

    def _event_text(self, event: AstrMessageEvent) -> str:
        value = getattr(event, "message_str", None)
        if value is None:
            getter = getattr(event, "get_message_str", None)
            if getter:
                value = getter()
        return str(value or "")

    def _command_args(self, event: AstrMessageEvent, prefix: str) -> list[str]:
        text = self._event_text(event).strip()
        lowered = text.lower()
        for token in (f"/{prefix}", f"！{prefix}", f"!{prefix}", prefix):
            if lowered.startswith(token.lower()):
                rest = text[len(token):].strip()
                return [part for part in rest.split() if part]
        return text.split()

    def _is_owner(self, event: AstrMessageEvent) -> bool:
        if not self._cfg.owner_ids:
            return True
        sender = str(event.get_sender_id() or "")
        return sender in {str(uid) for uid in self._cfg.owner_ids}

    def _deny(self, event: AstrMessageEvent) -> None:
        event.set_result(event.plain_result("该命令仅限主人使用。"))

    # ----- platform chat presence hooks -----

    @filter.on_llm_request()
    async def life_on_llm_request(
        self, event: AstrMessageEvent, request: Any
    ) -> None:
        try:
            await handle_llm_request(
                self.context, self.presence, self.db, self._cfg,
                event, request, now_fn=datetime.now,
            )
        except Exception:
            logger.exception("life on_llm_request hook failed")

    @filter.on_llm_response()
    async def life_on_llm_response(
        self, event: AstrMessageEvent, response: Any
    ) -> None:
        try:
            await handle_llm_response(
                self.context, self.presence, self.db, self._cfg,
                event, response, now_fn=datetime.now,
            )
        except Exception:
            logger.exception("life on_llm_response hook failed")

    # ----- commands -----

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("life")
    async def cmd_life(self, event: AstrMessageEvent):
        if not self._is_owner(event):
            self._deny(event)
            return
        args = self._command_args(event, "life")
        persona = args[0] if args else self._default_persona()
        overview = self.db.get_overview(persona)
        date = overview["date"]
        diary = overview.get("diary")
        stats = overview["stats"]
        lines = [f"生活档案 · {persona} · {date}", ""]
        if diary and diary.get("content"):
            lines.append("【今日日记】")
            if diary.get("signature"):
                lines.append(f"签名：{diary['signature']}")
            lines.append(diary["content"])
            lines.append("")
        lines.append(
            f"【状态】漫游 {stats['sessions']} 次，短记 {stats['notes']} 条，"
            f"成功 {stats['completed']}，跳过 {stats['skipped']}，异常 {stats['errors']}，"
            f"分享 {stats['shares_sent']}，被拦 {stats['shares_blocked']}"
        )
        sessions = overview.get("sessions") or []
        if sessions:
            lines.append("")
            lines.append("【漫游记录】")
            for session in sessions[:8]:
                lines.append(
                    f"- {session['started_at']} {session['status']} "
                    f"({session['notes_count']} 条) {session.get('reason') or ''}"
                )
        else:
            lines.append("今天还没有漫游记录，可用 /life_now 立即漫游。")
        event.set_result(event.plain_result("\n".join(lines)))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("life_today")
    async def cmd_life_today(self, event: AstrMessageEvent):
        if not self._is_owner(event):
            self._deny(event)
            return
        args = self._command_args(event, "life_today")
        persona = args[0] if args else self._default_persona()
        status = self.db.get_status(persona)
        lines = [
            f"生活状态 · {persona} · {status['date']}",
            f"心情：{status['mood'] or '未知'}",
            f"精力：{status['energy'] if status['energy'] is not None else '未知'}",
            f"今日漫游：{status['browse_count']} 次 · 短记 {status['notes_count']} 条",
        ]
        diary = status.get("diary")
        if diary:
            lines.append(f"日记：已写（{diary.get('signature') or '无签名'}）")
        else:
            lines.append("日记：未写")
        recent = status.get("recent_notes") or []
        if recent:
            lines.append("最近见闻：")
            lines.extend(f"- {n['title']}" for n in recent)
        event.set_result(event.plain_result("\n".join(lines)))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("life_now")
    async def cmd_life_now(self, event: AstrMessageEvent):
        if not self._is_owner(event):
            self._deny(event)
            return
        args = self._command_args(event, "life_now")
        persona = args[0] if args else self._default_persona()
        result = await self.service.run_browse_session(persona, "manual", force=True)
        status_text = {
            "completed": f"漫游完成，记下 {result.notes_count} 条见闻。",
            "skipped": "已跳过漫游。",
            "skipped_energy": "精力不足，今天先不出门。",
            "error": "漫游失败，请查看日志。",
            "failed": "漫游失败，请查看日志。",
            "disabled": "插件已停用。",
        }.get(result.status, f"状态：{result.status}")
        if result.reason:
            status_text += f"（{result.reason}）"
        event.set_result(event.plain_result(f"[{persona}] {status_text}"))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("life_plan")
    async def cmd_life_plan(self, event: AstrMessageEvent):
        if not self._is_owner(event):
            self._deny(event)
            return
        args = self._command_args(event, "life_plan")
        persona = args[0] if args else self._default_persona()
        result = await self.service.generate_plan(persona)
        if result.get("error"):
            event.set_result(event.plain_result(
                f"[{persona}] 计划生成失败：{result['error']}"
            ))
            return
        lines = [f"今日计划 · {persona} · {result['date']}", ""]
        accepted = result.get("accepted") or []
        rejected = result.get("rejected") or []
        if accepted:
            lines.append("【新增可选任务】")
            lines.extend(
                f"- {item['action']} {item['scheduled_at']}"
                for item in accepted
            )
        else:
            lines.append("本次没有新增可选任务，沿用默认固定计划。")
        if rejected:
            lines.append("")
            lines.append("【被系统裁决拒绝】")
            lines.extend(
                f"- {item['action']}：{item.get('reason') or ''}"
                for item in rejected
            )
        event.set_result(event.plain_result("\n".join(lines)))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("life_archive")
    async def cmd_life_archive(self, event: AstrMessageEvent):
        if not self._is_owner(event):
            self._deny(event)
            return
        args = self._command_args(event, "life_archive")
        if args and not _DATE_RE.match(args[0]) and ("-" in args[0] or "/" in args[0]):
            event.set_result(event.plain_result("日期格式应为 YYYY-MM-DD，例如 /life_archive 2026-08-10"))
            return
        persona = self._default_persona()
        date = local_today(self._cfg.timezone)
        if args and _DATE_RE.match(args[0]):
            date = args[0]
            if len(args) > 1:
                persona = args[1]
        elif args:
            persona = args[0]
        archive = self.db.archive_for_date(persona, date)
        diary = archive.get("diary")
        notes = archive.get("notes") or []
        lines = [f"生活档案 · {persona} · {date}", ""]
        if diary and diary.get("content"):
            lines.append("【日记】")
            if diary.get("signature"):
                lines.append(f"签名：{diary['signature']}")
            lines.append(diary["content"])
            lines.append("")
        if notes:
            lines.append(f"【见闻 · {len(notes)} 条】")
            for note in notes[:20]:
                lines.append(f"- {note['title']} [{note['source']}]")
                if note.get("summary"):
                    lines.append(f"  {note['summary']}")
                if note.get("opinion"):
                    lines.append(f"  想法：{note['opinion']}")
        else:
            lines.append("这一天没有见闻记录。")
        event.set_result(event.plain_result("\n".join(lines)))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("life_interest")
    async def cmd_life_interest(self, event: AstrMessageEvent):
        if not self._is_owner(event):
            self._deny(event)
            return
        args = self._command_args(event, "life_interest")
        persona = args[0] if args else self._default_persona()
        rows = self.db.get_interests(persona, limit=15)
        if not rows:
            event.set_result(event.plain_result(f"[{persona}] 还没有兴趣数据。"))
            return
        lines = [f"兴趣排行 · {persona}", ""]
        for row in rows:
            name = row.get("name") or row.get("key") or "?"
            lines.append(f"- {name} {float(row['weight']):.2f}（见过 {row['seen_count']} 次）")
        event.set_result(event.plain_result("\n".join(lines)))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("life_personas")
    async def cmd_life_personas(self, event: AstrMessageEvent):
        if not self._is_owner(event):
            self._deny(event)
            return
        args = self._command_args(event, "life_personas")
        if args and args[0].lower() == "refresh":
            persona = args[1] if len(args) > 1 else self._default_persona()
            try:
                await self.personas.refresh(persona)
                event.set_result(event.plain_result(f"[{persona}] 人格缓存已刷新。"))
            except PersonaUnavailable as exc:
                self.personas.mark_error(persona, str(exc))
                event.set_result(event.plain_result(f"[{persona}] 刷新失败：{exc}"))
            return
        lines = [f"persona 白名单：{', '.join(self._cfg.life_personas) or '（空，未运行）'}", ""]
        for row in self.personas.list_cache():
            status = row.get("status") or "?"
            error = f" · {row.get('error')}" if row.get("error") else ""
            lines.append(f"- {row['persona_id']} [{status}]{error}")
        if not self.personas.list_cache():
            lines.append("还没有缓存记录。")
        event.set_result(event.plain_result("\n".join(lines)))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("life_share")
    async def cmd_life_share(self, event: AstrMessageEvent):
        if not self._is_owner(event):
            self._deny(event)
            return
        args = self._command_args(event, "life_share")
        if not args:
            event.set_result(event.plain_result("用法：/life_share <note_id>"))
            return
        try:
            note_id = int(args[0])
        except ValueError:
            event.set_result(event.plain_result("note_id 需要是数字。"))
            return
        note = self.db.get_note(note_id)
        if note is None:
            event.set_result(event.plain_result("没有找到这条见闻。"))
            return
        persona = note["persona_id"]
        try:
            decision = json.loads(note.get("share_decision") or "{}")
        except (ValueError, TypeError):
            decision = {}
        if not decision.get("should_share"):
            sessions = self._cfg.share_sessions.get(persona, [])
            decision = {"should_share": True, "reason": "manual",
                        "target": sessions[0] if sessions else ""}
        result = await self.share_gate.attempt_share(persona, note, decision, force=True)
        text = {
            "sent": f"[{persona}] 已分享见闻 {note_id}。",
            "blocked": f"[{persona}] 分享被拦：{result.reason}",
            "error": f"[{persona}] 分享失败：{result.reason}",
            "not_triggered": f"[{persona}] 该见闻未标记为分享。",
        }.get(result.status, f"[{persona}] 状态：{result.status}")
        event.set_result(event.plain_result(text))

    @filter.permission_type(filter.PermissionType.ADMIN)
    @filter.command("life_reset")
    async def cmd_life_reset(self, event: AstrMessageEvent):
        if not self._is_owner(event):
            self._deny(event)
            return
        args = self._command_args(event, "life_reset")
        if not args or args[0].lower() != "confirm":
            event.set_result(event.plain_result("这会清空该 persona 的全部生活档案且不可恢复。确认请执行 /life_reset confirm [persona_id]"))
            return
        persona = args[1] if len(args) > 1 else self._default_persona()
        self.db.reset_all(persona)
        self.interests.seed(persona)
        event.set_result(event.plain_result(f"[{persona}] 生活档案已清空。"))