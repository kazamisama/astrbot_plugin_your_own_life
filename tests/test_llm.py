import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.llm import (
    BudgetExhausted,
    LLMClient,
    LLMError,
    extract_json,
    extract_usage_tokens,
)


class _FakeProvider:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    async def text_chat(self, prompt, contexts=None, image_urls=None):
        self.calls += 1
        return _FakeResponse(self.text)


class _FlakyProvider:
    def __init__(self, failures=2, text='{"ok": true}', usage=None):
        self.failures = failures
        self.text = text
        self.usage = usage
        self.calls = 0

    async def text_chat(self, prompt, contexts=None, image_urls=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("boom")
        return _FakeResponse(self.text, usage=self.usage)


class _FakeResponse:
    def __init__(self, text, usage=None):
        self.completion_text = text
        self.usage = usage


async def _noop_sleep(*args, **kwargs):
    return None


class ExtractJsonTest(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(extract_json('{"a": 1}'), {"a": 1})

    def test_fenced_json(self):
        text = "```json\n{\"a\": 1}\n```"
        self.assertEqual(extract_json(text), {"a": 1})

    def test_prose_with_json(self):
        text = '结果是：{"selected": [{"index": 0}]} 完'
        self.assertEqual(extract_json(text)["selected"][0]["index"], 0)

    def test_invalid(self):
        self.assertIsNone(extract_json("no json here"))

    def test_extract_usage_tokens(self):
        self.assertEqual(
            extract_usage_tokens(_FakeResponse("x", {"total_tokens": 42})), 42
        )
        self.assertEqual(
            extract_usage_tokens(
                _FakeResponse("x", {"prompt_tokens": 10, "completion_tokens": 5})
            ),
            15,
        )
        self.assertIsNone(extract_usage_tokens(_FakeResponse("x")))


class LLMClientTest(unittest.IsolatedAsyncioTestCase):
    async def test_chat_json_uses_provider(self):
        context = type("Ctx", (), {
            "get_provider_by_id": lambda self, pid: _FakeProvider('{"ok": true}'),
            "get_using_provider": lambda self: None,
        })()
        client = LLMClient(context, provider_id="p1")
        result = await client.chat_json("prompt")
        self.assertEqual(result, {"ok": True})

    async def test_no_provider_raises(self):
        context = type("Ctx", (), {
            "get_provider_by_id": lambda self, pid: None,
            "get_using_provider": lambda self: None,
        })()
        client = LLMClient(context)
        with self.assertRaises(LLMError):
            await client.chat_json("prompt")


class ManagedLLMTest(unittest.IsolatedAsyncioTestCase):
    async def _client(self, provider):
        context = type("Ctx", (), {
            "get_provider_by_id": lambda self, pid: provider,
            "get_using_provider": lambda self: None,
        })()
        return LLMClient(context, provider_id="p1")

    async def test_managed_retries_then_succeeds(self):
        provider = _FlakyProvider(failures=2)
        client = await self._client(provider)
        seen = []
        with mock.patch("life.llm.asyncio.sleep", new=_noop_sleep):
            result = await client.chat_json_managed(
                "prompt", retry_limit=2,
                on_usage=lambda tokens: seen.append(tokens),
            )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(provider.calls, 3)
        self.assertEqual(seen, [None])

    async def test_managed_budget_blocked(self):
        provider = _FlakyProvider(failures=0)
        client = await self._client(provider)

        def block():
            raise BudgetExhausted("daily_llm_call_limit=1")

        with self.assertRaises(BudgetExhausted):
            await client.chat_json_managed("prompt", retry_limit=2, can_call=block)
        self.assertEqual(provider.calls, 0)

    async def test_managed_exhausted_raises(self):
        provider = _FlakyProvider(failures=99)
        client = await self._client(provider)
        with mock.patch("life.llm.asyncio.sleep", new=_noop_sleep):
            with self.assertRaises(LLMError):
                await client.chat_json_managed("prompt", retry_limit=2)
        self.assertEqual(provider.calls, 3)

    async def test_managed_records_usage_tokens(self):
        provider = _FlakyProvider(failures=0, usage={"total_tokens": 42})
        client = await self._client(provider)
        seen = []
        result = await client.chat_json_managed(
            "prompt", retry_limit=0, on_usage=lambda tokens: seen.append(tokens)
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(seen, [42])


if __name__ == "__main__":
    unittest.main()