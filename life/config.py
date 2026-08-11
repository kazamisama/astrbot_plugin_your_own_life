"""Typed config access for astrbot_plugin_your_own_life."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any, Mapping, Sequence

from life.timeutil import DEFAULT_TIMEZONE, is_valid_timezone


def _as_str(value: Any, default: str = "") -> str:
    if value is None:
        return default
    text = str(value).strip()
    return text if text else default


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_float(value: Any, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _as_int(value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _as_list(value: Any, default: Sequence[str]) -> list[str]:
    if value is None:
        return list(default)
    if isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        parts = re.split(r"[\n,，]", str(value))
    return [str(p).strip() for p in parts if str(p).strip()]


def _as_dict_of_lists(value: Any) -> dict[str, list[str]]:
    """Parse share_sessions: dict of persona -> sids, or flat 'persona:sid' lines."""
    out: dict[str, list[str]] = {}
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{"):
            try:
                import json
                parsed = json.loads(text)
                if isinstance(parsed, Mapping):
                    value = parsed
            except (ValueError, TypeError):
                pass
    if isinstance(value, Mapping):
        for key, items in value.items():
            out[str(key)] = _as_list(items, [])
        return out
    for raw in _as_list(value, []):
        text = str(raw).strip()
        if not text:
            continue
        if ":" in text:
            persona, sid = text.split(":", 1)
            if sid.strip():
                out.setdefault(persona.strip(), []).append(sid.strip())
        else:
            out.setdefault("default", []).append(text)
    return out


def _get(cfg: Any, key: str, default: Any = None) -> Any:
    if cfg is None:
        return default
    if isinstance(cfg, Mapping):
        return cfg.get(key, default)
    return getattr(cfg, key, default)


def parse_interest_line(raw: str) -> tuple[str, str]:
    """Parse 'key' or 'key:display name' into (key, display_name)."""
    text = _as_str(raw, "")
    if not text:
        return "", ""
    for sep in (":", "="):
        if sep in text:
            key, name = text.split(sep, 1)
            return key.strip(), name.strip()
    return text, text


@dataclass(frozen=True)
class SleepWindow:
    """Inclusive-start / exclusive-end sleep window, supports overnight spans."""

    start: time
    end: time

    @classmethod
    def parse(cls, raw: Any) -> "SleepWindow":
        text = _as_str(raw, "00:00-07:00")
        match = re.match(
            r"^\s*(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})\s*$", text
        )
        if not match:
            return cls(time(0, 0), time(7, 0))
        try:
            start = time(int(match.group(1)), int(match.group(2)))
            end = time(int(match.group(3)), int(match.group(4)))
            return cls(start, end)
        except ValueError:
            return cls(time(0, 0), time(7, 0))

    def contains(self, moment: datetime) -> bool:
        now = moment.time().replace(second=0, microsecond=0)
        if self.start <= self.end:
            return self.start <= now < self.end
        return now >= self.start or now < self.end


@dataclass
class LifeConfig:
    enabled: bool = True
    browse_times: list[str] = field(default_factory=lambda: ["10:00", "15:00"])
    diary_time: str = "23:00"
    sleep_window: SleepWindow = field(
        default_factory=lambda: SleepWindow(time(0, 0), time(7, 0))
    )
    timezone: str = DEFAULT_TIMEZONE
    timezone_error: bool = False
    owner_ids: list[str] = field(default_factory=list)
    life_llm: str = ""
    energy_gate: float = 0.3
    explore_probability: float = 0.2
    interest_decay: float = 0.98
    interests_initial: list[tuple[str, str]] = field(default_factory=list)
    hn_enabled: bool = True
    github_enabled: bool = True
    reddit_enabled: bool = True
    reddit_subreddits: list[str] = field(
        default_factory=lambda: ["programming", "artificial", "MachineLearning", "technology"]
    )
    rss_feeds: list[str] = field(default_factory=list)
    tavily_api_key: str = ""
    db_path: str = ""
    source_timeout: float = 10.0
    notes_min: int = 3
    notes_max: int = 5
    life_personas: list[str] = field(default_factory=list)
    browse_jitter_minutes: int = 120
    diary_jitter_minutes: int = 60
    daily_llm_call_limit: int = 0
    daily_token_budget: int = 0
    llm_retry_limit: int = 3
    trash_retention_days: int = 30
    injection_log_enabled: bool = True
    lease_ttl_seconds: int = 300
    share_enabled: bool = True
    share_daily_cap: int = 2
    share_cooldown_minutes: int = 360
    share_include_link: bool = True
    share_max_chars: int = 200
    share_sessions: dict[str, list[str]] = field(default_factory=dict)
    persona_prompt_max_chars: int = 6000
    persona_cache_hours: float = 24.0
    esm_scope_prefix: str = "internet-life"
    life_tool_enabled: bool = True


def load_config(cfg: Any) -> LifeConfig:
    initial_lines = _as_list(_get(cfg, "interests_initial"), [])
    initial = [
        parse_interest_line(line)
        for line in initial_lines
        if parse_interest_line(line)[0]
    ]
    notes_min = max(1, _as_int(_get(cfg, "notes_min"), 3))
    notes_max = max(notes_min, _as_int(_get(cfg, "notes_max"), 5))
    raw_timezone = _as_str(_get(cfg, "timezone"), DEFAULT_TIMEZONE)
    timezone_valid = is_valid_timezone(raw_timezone)
    return LifeConfig(
        enabled=_as_bool(_get(cfg, "enabled"), True),
        timezone=raw_timezone if timezone_valid else DEFAULT_TIMEZONE,
        timezone_error=not timezone_valid,
        browse_times=_as_list(
            _get(cfg, "browse_times"), ["10:00", "15:00"]
        ),
        diary_time=_as_str(_get(cfg, "diary_time"), "23:00"),
        sleep_window=SleepWindow.parse(_get(cfg, "sleep_window")),
        owner_ids=_as_list(_get(cfg, "owner_ids"), []),
        life_llm=_as_str(_get(cfg, "life_llm"), ""),
        energy_gate=_as_float(_get(cfg, "energy_gate"), 0.3),
        explore_probability=_as_float(_get(cfg, "explore_probability"), 0.2),
        interest_decay=_as_float(_get(cfg, "interest_decay"), 0.98),
        interests_initial=initial,
        hn_enabled=_as_bool(_get(cfg, "hn_enabled"), True),
        github_enabled=_as_bool(_get(cfg, "github_enabled"), True),
        reddit_enabled=_as_bool(_get(cfg, "reddit_enabled"), True),
        reddit_subreddits=_as_list(
            _get(cfg, "reddit_subreddits"),
            ["programming", "artificial", "MachineLearning", "technology"],
        ),
        rss_feeds=_as_list(_get(cfg, "rss_feeds"), []),
        tavily_api_key=_as_str(_get(cfg, "tavily_api_key"), ""),
        db_path=_as_str(_get(cfg, "db_path"), ""),
        esm_scope_prefix=_as_str(_get(cfg, "esm_scope_prefix"), "internet-life"),
        source_timeout=_as_float(_get(cfg, "source_timeout"), 10.0),
        notes_min=notes_min,
        notes_max=notes_max,
        life_personas=_as_list(_get(cfg, "life_personas"), []),
        browse_jitter_minutes=_as_int(_get(cfg, "browse_jitter_minutes"), 120),
        diary_jitter_minutes=_as_int(_get(cfg, "diary_jitter_minutes"), 60),
        daily_llm_call_limit=max(0, _as_int(_get(cfg, "daily_llm_call_limit"), 0)),
        daily_token_budget=max(0, _as_int(_get(cfg, "daily_token_budget"), 0)),
        llm_retry_limit=max(1, _as_int(_get(cfg, "llm_retry_limit"), 3)),
        trash_retention_days=max(0, _as_int(_get(cfg, "trash_retention_days"), 30)),
        injection_log_enabled=_as_bool(_get(cfg, "injection_log_enabled"), True),
        lease_ttl_seconds=max(1, _as_int(_get(cfg, "lease_ttl_seconds"), 300)),
        share_enabled=_as_bool(_get(cfg, "share_enabled"), True),
        share_daily_cap=_as_int(_get(cfg, "share_daily_cap"), 2),
        share_cooldown_minutes=_as_int(_get(cfg, "share_cooldown_minutes"), 360),
        share_include_link=_as_bool(_get(cfg, "share_include_link"), True),
        share_max_chars=_as_int(_get(cfg, "share_max_chars"), 200),
        share_sessions=_as_dict_of_lists(_get(cfg, "share_sessions")),
        persona_prompt_max_chars=_as_int(_get(cfg, "persona_prompt_max_chars"), 6000),
        persona_cache_hours=_as_float(_get(cfg, "persona_cache_hours"), 24.0),
        life_tool_enabled=_as_bool(_get(cfg, "life_tool_enabled"), True),
    )