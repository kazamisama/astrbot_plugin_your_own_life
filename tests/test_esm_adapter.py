import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from life.esm_adapter import ESMAdapter


class _FakeStar:
    def __init__(self, energy=0.9, signals=("curiosity", "arousal", "self_reply"),
                 methods=None):
        self.energy = energy
        self.signals = signals
        self.applied = []
        self.energy_scopes = []
        self.consumed = []
        self.methods = methods or {"energy"}

    def get_bot_energy(self, scope=None):
        if "energy" not in self.methods:
            raise AttributeError("no energy")
        self.energy_scopes.append(scope)
        return self.energy

    def consume_energy(self, amount, reason, scope=None):
        if "consume" not in self.methods:
            raise AttributeError("no consume_energy")
        self.consumed.append((amount, reason, scope))
        self.energy = max(0.0, self.energy - amount)
        return self.energy

    def list_signals(self):
        return list(self.signals)

    def try_apply_signal(self, scope, user_id, signal, intensity=1.0, reason=""):
        self.applied.append((scope, user_id, signal, intensity, reason))
        return None

    def get_combined_state(self, scope):
        class View:
            combined_label = "平静"
        return View()


class _FakeContext:
    def __init__(self, star=None):
        self.star = star

    def get_registered_star(self, plugin_id):
        return self.star


class ESMAdapterTest(unittest.TestCase):
    def test_missing_esm_degrades(self):
        adapter = ESMAdapter(_FakeContext(None), scope_prefix="internet-life")
        self.assertFalse(adapter.available())
        self.assertIsNone(adapter.get_energy())
        self.assertEqual(adapter.get_mood_context("shelly"), "")
        blocked, energy, reason = adapter.gate_energy()
        self.assertFalse(blocked)
        self.assertIsNone(energy)

    def test_energy_gate(self):
        adapter = ESMAdapter(_FakeContext(_FakeStar(energy=0.2)), energy_gate=0.3)
        blocked, energy, reason = adapter.gate_energy()
        self.assertTrue(blocked)
        self.assertEqual(energy, 0.2)
        self.assertEqual(reason, "energy_gate")

    def test_scope_and_signals(self):
        star = _FakeStar(signals=("curiosity", "self_reply"))
        adapter = ESMAdapter(_FakeContext(star), scope_prefix="internet-life")
        self.assertEqual(adapter.scope_for("shelly"), "internet-life:shelly")
        self.assertIn("平静", adapter.get_mood_context("shelly"))
        self.assertTrue(adapter.apply_browse_signal("shelly", "curious", 0.3))
        self.assertEqual(star.applied[0][0], "internet-life:shelly")
        self.assertEqual(star.applied[0][2], "curiosity")
        self.assertTrue(adapter.apply_self_reply_signal("shelly"))
        self.assertEqual(star.applied[1][2], "self_reply")

    def test_unknown_signals_noop(self):
        star = _FakeStar(signals=("only_weird",))
        adapter = ESMAdapter(_FakeContext(star))
        self.assertFalse(adapter.apply_browse_signal("shelly", "curious"))
        self.assertFalse(adapter.apply_self_reply_signal("shelly"))

    def test_energy_read_uses_persona_scope(self):
        star = _FakeStar(energy=0.8)
        adapter = ESMAdapter(_FakeContext(star), scope_prefix="internet-life")
        self.assertEqual(adapter.get_energy("shelly"), 0.8)
        self.assertEqual(star.energy_scopes[-1], "internet-life:shelly")

    def test_consume_energy_forwards_scope_and_reason(self):
        star = _FakeStar(energy=0.5, methods={"energy", "consume"})
        adapter = ESMAdapter(_FakeContext(star), scope_prefix="internet-life")
        remaining = adapter.consume_energy("shelly", 0.15, "internet_life:browse")
        self.assertEqual(remaining, 0.35)
        self.assertEqual(
            star.consumed[0],
            (0.15, "internet_life:browse", "internet-life:shelly"),
        )

    def test_consume_energy_missing_method_returns_none(self):
        adapter = ESMAdapter(_FakeContext(_FakeStar()), scope_prefix="internet-life")
        self.assertIsNone(adapter.consume_energy("shelly", 0.1, "x"))

    def test_consume_energy_failure_returns_none(self):
        class _Broken(_FakeStar):
            def consume_energy(self, amount, reason, scope=None):
                raise RuntimeError("boom")

        adapter = ESMAdapter(_FakeContext(_Broken()), scope_prefix="internet-life")
        self.assertIsNone(adapter.consume_energy("shelly", 0.1, "x"))


if __name__ == "__main__":
    unittest.main()