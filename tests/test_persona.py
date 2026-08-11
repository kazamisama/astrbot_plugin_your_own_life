import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.config import load_config
from life.db import LifeDB
from life.persona import PersonaService, PersonaUnavailable


class _Persona:
    def __init__(self, prompt):
        self.system_prompt = prompt


class _FakePersonaManager:
    def __init__(self, persona=None, default=None):
        self.persona = persona
        self.default = default

    async def get_persona(self, persona_id):
        return self.persona

    async def get_default_persona_v3(self, umo=""):
        return self.default


class _FakeContext:
    def __init__(self, persona_manager):
        self.persona_manager = persona_manager


class PersonaServiceTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = LifeDB(Path(self.tmp.name) / "life.db")
        self.config = load_config({"persona_cache_hours": 24})

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    async def test_refresh_and_resolve(self):
        context = _FakeContext(_FakePersonaManager(persona=_Persona("我是雪莉")))
        service = PersonaService(context, self.db, self.config)
        result = await service.refresh("shelly")
        self.assertEqual(result.system_prompt, "我是雪莉")
        self.assertEqual(result.source, "persona")
        resolved = await service.resolve("shelly")
        self.assertEqual(resolved.system_prompt, "我是雪莉")

    async def test_ensure_fresh_uses_cache(self):
        context = _FakeContext(_FakePersonaManager(persona=_Persona("prompt")))
        service = PersonaService(context, self.db, self.config)
        await service.refresh("shelly")
        context.persona_manager.persona = None  # cache should be used
        await service.ensure_fresh("shelly")
        self.assertEqual(service.get_cached("shelly")["status"], "ok")

    async def test_unavailable_and_mark_error(self):
        context = _FakeContext(_FakePersonaManager(persona=None, default=None))
        service = PersonaService(context, self.db, self.config)
        with self.assertRaises(PersonaUnavailable):
            await service.refresh("shelly")
        service.mark_error("shelly", "boom")
        row = service.get_cached("shelly")
        self.assertEqual(row["status"], "error")
        self.assertEqual(row["error"], "boom")


if __name__ == "__main__":
    unittest.main()