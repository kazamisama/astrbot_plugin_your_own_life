"""LLM prompt builders for per-persona browsing, diary and sharing."""
from __future__ import annotations

import json
from typing import Any, Optional, Sequence

MEMORY_CATEGORIES = (
    "observation",
    "opinion",
    "event",
    "preference",
    "plan",
    "mood",
    "relationship",
    "other",
)


def _json_text(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2)


def persona_block(persona_prompt: str, persona_id: str) -> str:
    return (
        f"[人格设定 · {persona_id}]\n{persona_prompt}\n"
        "以上是当前实例的人格设定。你以这个人格过自己的互联网生活，不要自称 AI。"
    )


def _share_sessions_block(share_sessions: Optional[Sequence[str]]) -> str:
    if not share_sessions:
        return "（未配置分享白名单，所有 share.should_share 必须为 false）"
    lines = "\n".join(f"{i + 1}. {sid}" for i, sid in enumerate(share_sessions))
    return f"可分享会话白名单（share.target 只能填其中之一）：\n{lines}"


def build_select_prompt(
    persona_prompt: str,
    persona_id: str,
    candidates: Sequence[dict],
    interests: Sequence[str],
    mood_context: str,
    notes_min: int = 3,
    notes_max: int = 5,
    share_sessions: Optional[Sequence[str]] = None,
) -> str:
    return f"""{persona_block(persona_prompt, persona_id)}

你正在“漫游”互联网，为自己生活，而不是在群里发言。以下是候选内容（JSON）。
请挑选 {notes_min}-{notes_max} 条最值得记进今天生活的条目，像记私人笔记一样写下内容摘要、观点、情绪、感兴趣程度。

规则：
- 摘要 100 字内，用自己的话重写，不要照抄原文。
- 观点要有你自己的角度，真诚即可。
- category 只能从以下分类中选一个：{", ".join(MEMORY_CATEGORIES)}；tags 最多 5 个、每个不超过 20 字。
- share.should_share 表示“这条感悟要不要主动分享出去”；想分享时 target 必须填白名单里的完整 sid。
- 不要输出任何多余文字，只输出一个 JSON 对象。

候选内容：
{_json_text(candidates)}

你当前的高兴趣领域：{", ".join(interests) or "未设定"}

{_share_sessions_block(share_sessions)}

当前状态上下文（可能为空）：
{mood_context or "（无）"}

输出格式：
{{"selected": [{{"index": 数字, "summary": "摘要", "opinion": "观点", "mood": "curious|calm|excited|tired|skeptical", "interest_level": 0.0-1.0, "interest_key": "key", "interest_name": "名称", "category": "见上方分类", "tags": ["标签1"], "share": {{"should_share": false, "reason": "", "target": ""}}}}],
"session_mood": "curious|calm|excited|tired|skeptical",
"energy_change": -0.05}}"""


def build_diary_prompt(
    persona_prompt: str,
    persona_id: str,
    notes: Sequence[dict],
    snapshots: Sequence[dict],
    mood_context: str,
    date: str,
) -> str:
    return f"""{persona_block(persona_prompt, persona_id)}

现在是 {date} 的深夜，你要为今天写一篇私人日记。素材只有下面的短记与状态快照（JSON）。
请用第一人称、自然的口吻写 150-300 字日记：今天在网上看到了什么、你因此想了什么、情绪如何变化、明天想继续关注什么。

规则：
- 日记是私人档案，语气安静、真实、有自己的视角，不要写成新闻摘要。
- 不要复述大段原文，只保留你消化后的理解。
- interest_updates 是可选的兴趣增量：key 对应兴趣，name 是展示名，delta 在 -0.2 到 0.2 之间。
- 只输出一个 JSON 对象。

今天短记：
{_json_text(notes)}

状态快照：
{_json_text(snapshots)}

当前状态上下文（可能为空）：
{mood_context or "（无）"}

输出格式：
{{"diary_text": "日记正文", "mood": "curious|calm|excited|tired|skeptical", "energy_change": -0.05,
"interest_updates": {{"key": {{"name": "名称", "delta": 0.05}}}}}}"""


def build_share_prompt(
    persona_prompt: str,
    persona_id: str,
    note: dict,
    target_sid: str,
    max_chars: int = 200,
    include_link: bool = True,
) -> str:
    link_hint = "；如果合适，可以在末尾附上原文链接" if include_link else ""
    return f"""{persona_block(persona_prompt, persona_id)}

你决定把下面这条感悟分享到会话 {target_sid}。请把它改写成一句自然、克制、像你自己随口说的话{link_hint}。
不要解释你在分享，不要加引号包裹，不要提“感悟”这个词，总字数不超过 {max_chars} 字。

感悟内容：
标题：{note.get("title", "")}
摘要：{note.get("summary", "")}
观点：{note.get("opinion", "")}
来源：{note.get("url", "")}

只输出一个 JSON 对象：{{"message": "分享文本"}}"""