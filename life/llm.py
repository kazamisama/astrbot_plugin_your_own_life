"""Minimal LLM helper around AstrBot providers."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

logger = logging.getLogger("your_own_life.llm")


class LLMError(RuntimeError):
    pass


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
        provider = self._resolve()
        if provider is None:
            raise LLMError("no usable LLM provider")
        last_error: Optional[Exception] = None
        for _ in range(max(1, retries + 1)):
            try:
                resp = await provider.text_chat(prompt=prompt, contexts=[], image_urls=[])
                content = getattr(resp, "completion_text", None)
                data = extract_json(content)
                if isinstance(data, dict):
                    return data
                last_error = LLMError("LLM response was not a JSON object")
            except Exception as exc:  # provider errors are retried
                last_error = exc
        raise LLMError(f"LLM JSON failed after retries: {last_error}")