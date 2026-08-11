"""Minimal LLM helper around AstrBot providers."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Callable, Optional

logger = logging.getLogger("your_own_life.llm")


class LLMError(RuntimeError):
    pass


class BudgetExhausted(LLMError):
    """Raised when a daily LLM budget prevents another call."""


def extract_usage_tokens(resp: Any) -> Optional[int]:
    """Best-effort token usage from a provider response; None if unavailable."""
    usage = getattr(resp, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, dict):
        total = usage.get("total_tokens")
        if total is not None:
            try:
                return int(total)
            except (TypeError, ValueError):
                pass
        try:
            return int(usage.get("prompt_tokens") or 0) + int(
                usage.get("completion_tokens") or 0
            )
        except (TypeError, ValueError):
            return None
    total = getattr(usage, "total_tokens", None)
    if total is not None:
        try:
            return int(total)
        except (TypeError, ValueError):
            return None
    return None


def extract_json(text: str) -> Optional[Any]:
    """Parse JSON from a completion, tolerating markdown fences and prose."""
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        return json.loads(stripped)
    except (ValueError, TypeError):
        pass

    decoder = json.JSONDecoder()
    for open_char, close_char in (("{", "}"), ("[", "]")):
        start = stripped.find(open_char)
        while start != -1:
            try:
                obj, _ = decoder.raw_decode(stripped[start:])
                return obj
            except (ValueError, TypeError):
                start = stripped.find(open_char, start + 1)
    return None


class LLMClient:
    """Resolves a provider once per process and exposes chat_json()."""

    def __init__(self, context: Any, provider_id: str = ""):
        self.context = context
        self.provider_id = provider_id or ""
        self._provider: Any = None
        self._resolved = False

    def _resolve(self) -> Any:
        if self._resolved:
            return self._provider
        self._resolved = True
        getter = getattr(self.context, "get_provider_by_id", None)
        if getter and self.provider_id:
            try:
                provider = getter(self.provider_id)
                if provider:
                    self._provider = provider
                    return provider
            except Exception as exc:
                logger.debug("get_provider_by_id(%s) failed: %s", self.provider_id, exc)
        get_using = getattr(self.context, "get_using_provider", None)
        if get_using:
            try:
                provider = get_using()
                if provider:
                    self._provider = provider
                    return provider
            except Exception as exc:
                logger.debug("get_using_provider failed: %s", exc)
        if getter:
            try:
                self._provider = getter(self.provider_id)
            except Exception as exc:
                logger.debug("fallback get_provider_by_id failed: %s", exc)
        return self._provider

    async def chat_json(self, prompt: str, retries: int = 2) -> dict:
        return await self.chat_json_managed(
            prompt, retry_limit=max(0, int(retries)), can_call=None, on_usage=None
        )

    async def chat_json_managed(
        self,
        prompt: str,
        retry_limit: int = 3,
        can_call: Optional[Callable[[], None]] = None,
        on_usage: Optional[Callable[[Optional[int]], None]] = None,
    ) -> dict:
        provider = self._resolve()
        if provider is None:
            raise LLMError("no usable LLM provider")
        last_error: Optional[Exception] = None
        attempts = max(1, int(retry_limit) + 1)
        for attempt in range(attempts):
            if can_call is not None:
                can_call()
            try:
                resp = await provider.text_chat(prompt=prompt, contexts=[], image_urls=[])
                if on_usage is not None:
                    on_usage(extract_usage_tokens(resp))
                content = getattr(resp, "completion_text", None)
                data = extract_json(content)
                if isinstance(data, dict):
                    return data
                last_error = LLMError("LLM response was not a JSON object")
            except Exception as exc:  # provider errors are retried
                last_error = exc
            if attempt < attempts - 1:
                await asyncio.sleep(min(2 ** attempt, 8))
        raise LLMError(f"LLM JSON failed after retries: {last_error}")