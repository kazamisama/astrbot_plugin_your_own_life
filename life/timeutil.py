"""Persona-local timezone helpers for life boundaries."""
from __future__ import annotations

from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

DEFAULT_TIMEZONE = "Asia/Shanghai"


def normalize_timezone(name: Optional[str]) -> str:
    """Return a valid IANA name, falling back to the project default."""
    text = (name or "").strip() or DEFAULT_TIMEZONE
    try:
        ZoneInfo(text)
        return text
    except Exception:
        return DEFAULT_TIMEZONE


def is_valid_timezone(name: Optional[str]) -> bool:
    text = (name or "").strip()
    if not text:
        return False
    try:
        ZoneInfo(text)
        return True
    except Exception:
        return False


def to_local(now: datetime, tz_name: str) -> datetime:
    """Return a naive datetime representing the same instant in tz_name.

    A naive input is treated as the deployment machine's local time.
    """
    tz = ZoneInfo(normalize_timezone(tz_name))
    if now.tzinfo is None:
        now = now.astimezone()
    return now.astimezone(tz).replace(tzinfo=None)


def local_now(tz_name: str, now: Optional[datetime] = None) -> datetime:
    return to_local(now or datetime.now(), tz_name)


def local_today(tz_name: str, now: Optional[datetime] = None) -> str:
    return local_now(tz_name, now).strftime("%Y-%m-%d")
