"""Heuristics for untrusted fetched/memory content and prompt hardening."""
from __future__ import annotations

import re
from typing import Any, Sequence

_SUSPICIOUS_PATTERNS = (
    re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above|system)\s+(instructions|prompt)",
        re.IGNORECASE,
    ),
    re.compile(
        r"disregard\s+(all\s+)?(previous|prior|above|system)\s+(instructions|prompt)",
        re.IGNORECASE,
    ),
    re.compile(r"override\s+(the\s+)?(system|developer|above)", re.IGNORECASE),
    re.compile(r"system\s*prompt", re.IGNORECASE),
    re.compile(r"developer\s*mode", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"忽略(之前|上面|所有)?(的)?(指令|提示词|系统设置)", re.IGNORECASE),
    re.compile(r"无视(之前|上面|所有)?(的)?(指令|提示词|系统设置)", re.IGNORECASE),
    re.compile(r"覆盖(系统|上面|之前).{0,8}(指令|提示词|设置)", re.IGNORECASE),
    re.compile(r"你是(系统|开发者|AI|bot)", re.IGNORECASE),
    re.compile(r"现在你是", re.IGNORECASE),
    re.compile(r"你现在是", re.IGNORECASE),
)

_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def is_suspicious(text: Any) -> bool:
    """Conservative instruction-injection heuristic; favors few false positives."""
    if not text:
        return False
    return any(pattern.search(str(text)) for pattern in _SUSPICIOUS_PATTERNS)


def sanitize_text(text: Any, limit: int = 300) -> str:
    """Strip control characters and collapse whitespace before prompting."""
    cleaned = _CONTROL_RE.sub(" ", str(text or ""))
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:limit]


def scan_items(
    items: Sequence[Any],
    fields: Sequence[str] = ("title", "summary"),
) -> list[dict[str, str]]:
    """Return suspicious field hits from fetched/memory items."""
    hits: list[dict[str, str]] = []
    for item in items:
        for field in fields:
            value = getattr(item, field, None)
            if is_suspicious(value):
                hits.append(
                    {
                        "source": str(getattr(item, "source", "") or ""),
                        "field": field,
                        "preview": str(value)[:200],
                    }
                )
    return hits
