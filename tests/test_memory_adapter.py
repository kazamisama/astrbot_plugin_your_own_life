import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.memory_adapter import LifeMemoryAdapter, MemoryHostError


class _FakeHost:
    def __init__(self):
        self.calls = []

    def store_diary_line(self, persona_id, date, content, **kwargs):
        self.calls.append(("store_diary_line", persona_id, date, content, kwargs))
        return "eid-1"

    def add_note(self, persona_id, note, source="external"):
        self.calls.append(("add_note", persona_id, note, source))
        return "nid-1"

    def store_event(self, persona_id, platform, session_id, ts, kind,
                    payload=None, source="external"):
        self.calls.append(("store_event", persona_id, kind, source))
        return "evid-1"

    def query_recent_memory(self, persona_id, query="", k=5, since=0.0):
        return [{"id": "m1", "persona_id": persona_id}]

    def query_memory(self, persona_id, query, k=5, memory_types=None):
        return [{"id": "m1", "memory_type": "note"}]

    def search(self, persona_id, query, k=5, memory_types=None):
        return [{"id": "m2", "memory_type": "diary"}]

    def upsert_entity(self, persona_id, entity):
        return "ent-1"

    def link_entities(self, persona_id, src, relation, dst, weight=1.0):
        return True

    def list_entities(self, persona_id, limit=500):
        return [{"entity_id": "x"}]

    def list_links(self, persona_id, limit=1000):
        return [{"relation": "appears_on"}]

    def claim_task(self, persona_id, task_kind, holder="", ttl_seconds=300):
        return True

    def renew_task(self, persona_id, task_kind, holder="", ttl_seconds=300):
        return True

    def release_task(self, persona_id, task_kind, holder=""):
        return True

    def task_lease_owner(self, persona_id, task_kind):
        return "instance-a"


class _FakeContext:
    def __init__(self, host):
        self.host = host

    def get_registered_star(self, plugin_id):
        return self.host


class MemoryAdapterTest(unittest.TestCase):
    def test_missing_host_raises_hard_error(self):
        adapter = LifeMemoryAdapter(_FakeContext(None))
        self.assertFalse(adapter.available())
        with self.assertRaises(MemoryHostError):
            adapter.store_diary_line("shelly", "2026-08-12", "x")
        with self.assertRaises(MemoryHostError):
            adapter.query_memory("shelly", "x")

    def test_missing_method_raises(self):
        host = _FakeHost()
        host.store_diary_line = None
        adapter = LifeMemoryAdapter(_FakeContext(host))
        with self.assertRaises(MemoryHostError):
            adapter.store_diary_line("shelly", "2026-08-12", "x")

    def test_forwards_all_contract_methods(self):
        host = _FakeHost()
        adapter = LifeMemoryAdapter(_FakeContext(host), host_id="custom-host")
        self.assertTrue(adapter.available())
        self.assertEqual(
            adapter.store_diary_line(
                "shelly", "2026-08-12", "text", mood="calm",
                signature="sig", source_refs=["ref:1"]),
            "eid-1",
        )
        self.assertEqual(adapter.add_note("shelly", {"summary": "s"}), "nid-1")
        self.assertEqual(
            adapter.store_event("shelly", "internet-life", "s1", 1.0, "observe"),
            "evid-1",
        )
        self.assertEqual(adapter.query_recent_memory("shelly")[0]["id"], "m1")
        self.assertEqual(
            adapter.query_memory("shelly", "q")[0]["memory_type"], "note")
        self.assertEqual(
            adapter.search("shelly", "q")[0]["memory_type"], "diary")
        self.assertEqual(
            adapter.upsert_entity("shelly", {"dimension": "topic"}), "ent-1")
        self.assertTrue(adapter.link_entities("shelly", "a", "appears_on", "b"))
        self.assertEqual(adapter.list_entities("shelly")[0]["entity_id"], "x")
        self.assertEqual(adapter.list_links("shelly")[0]["relation"], "appears_on")
        self.assertTrue(adapter.claim_task("shelly", "diary", "inst"))
        self.assertTrue(adapter.renew_task("shelly", "diary", "inst"))
        self.assertTrue(adapter.release_task("shelly", "diary", "inst"))
        self.assertEqual(
            adapter.task_lease_owner("shelly", "diary"), "instance-a")
        self.assertEqual(host.calls[0][0], "store_diary_line")


if __name__ == "__main__":
    unittest.main()
