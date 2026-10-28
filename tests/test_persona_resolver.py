import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.chat_hooks import resolve_event_persona
from life.persona import resolve_persona_id


class _Event:
    def __init__(self, umo="aiocqhttp:GroupMessage:123"):
        self.unified_msg_origin = umo


class _Conversation:
    def __init__(self, persona_id):
        self.persona_id = persona_id


class _ConvManager:
    def __init__(self, persona_id="shelly", raise_error=False):
        self.persona_id = persona_id
        self.raise_error = raise_error

    async def get_curr_conversation_id(self, umo):
        return "c1"

    async def get_conversation(self, umo, conv_id):
        if self.raise_error:
            raise RuntimeError("conversation boom")
        return _Conversation(self.persona_id)


class _PersonaManager:
    def __init__(self, name="fallback"):
        self.name = name
        self.calls = 0

    async def get_default_persona_v3(self, umo=""):
        self.calls += 1
        return {"name": self.name}


class _Context:
    def __init__(self, conversation_manager=None, persona_manager=None, event=None):
        if conversation_manager is not None:
            self.conversation_manager = conversation_manager
        if persona_manager is not None:
            self.persona_manager = persona_manager
        if event is not None:
            self.event = event


class _Wrapper:
    def __init__(self, context):
        self.context = context


class PersonaResolverTest(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_persona_wins(self):
        ctx = _Context(_ConvManager("shelly"), _PersonaManager("fallback"))
        self.assertEqual(await resolve_persona_id(ctx, _Event()), "shelly")

    async def test_default_persona_is_the_fallback(self):
        ctx = _Context(_ConvManager(None), _PersonaManager("fallback"))
        self.assertEqual(await resolve_persona_id(ctx, _Event()), "fallback")

    async def test_explicit_no_persona_does_not_fall_back(self):
        manager = _PersonaManager("fallback")
        ctx = _Context(_ConvManager("[%None]"), manager)
        self.assertEqual(await resolve_persona_id(ctx, _Event()), "")
        self.assertEqual(manager.calls, 0)

    async def test_conversation_error_still_tries_default(self):
        ctx = _Context(_ConvManager(raise_error=True), _PersonaManager("fallback"))
        self.assertEqual(await resolve_persona_id(ctx, _Event()), "fallback")

    async def test_wrapper_and_context_event_are_supported(self):
        ctx = _Context(_ConvManager("shelly"), _PersonaManager("fallback"),
                       event=_Event())
        self.assertEqual(await resolve_persona_id(_Wrapper(ctx)), "shelly")

    async def test_missing_origin_resolves_empty(self):
        ctx = _Context(_ConvManager("shelly"), _PersonaManager("fallback"))
        self.assertEqual(await resolve_persona_id(ctx, _Event("")), "")

    async def test_chat_hook_uses_same_resolver(self):
        ctx = _Context(_ConvManager("shelly"), _PersonaManager("fallback"))
        self.assertEqual(await resolve_event_persona(ctx, _Event()), "shelly")


if __name__ == "__main__":
    unittest.main()
