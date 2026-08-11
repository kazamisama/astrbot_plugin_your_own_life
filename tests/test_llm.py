import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.llm import LLMClient, LLMError, extract_json


class _FakeProvider:
    def __init__(self, text):
        self.text = text
        self.calls = 0

    async def text_chat(self, prompt, contexts=None, image_urls=None):
        self.calls += 1
        return _FakeResponse(self.text)


class _FakeResponse:
    def __init__(self, text):
        self.completion_text = text


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


if __name__ == "__main__":
    unittest.main()