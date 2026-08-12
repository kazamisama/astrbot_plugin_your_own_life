"""ESM adapter - the only place this plugin touches emotion_state_machine."""
from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger("your_own_life.esm")

ESM_PLUGIN_ID = "astrbot_plugin_emotion_state_machine"

_SIGNAL_CANDIDATES = ("curiosity", "arousal", "satisfied")


class ESMAdapter:
    """Capability-probing adapter. Scope is per persona: {prefix}:{persona_id}."""

    def __init__(self, context: Any, scope_prefix: str = "internet-life",
                 energy_gate: float = 0.3):
        self.context = context
        self.scope_prefix = scope_prefix or "internet-life"
        self.energy_gate = float(energy_gate)

    def scope_for(self, persona_id: str) -> str:
        return f"{self.scope_prefix}:{persona_id}"

    def _star(self) -> Any:
        getter = getattr(self.context, "get_registered_star", None)
        if getter is None:
            return None
        try:
            return getter(ESM_PLUGIN_ID)
        except Exception as exc:
            logger.debug("ESM lookup failed: %s", exc)
            return None

    def available(self) -> bool:
        return self._star() is not None

    def get_energy(self, persona_id: Optional[str] = None) -> Optional[float]:
        star = self._star()
        if star is None:
            return None
        fn = getattr(star, "get_bot_energy", None)
        if fn is None:
            return None
        try:
            scope = self.scope_for(persona_id) if persona_id else None
            return float(fn(scope))
        except Exception as exc:
            logger.debug("get_bot_energy failed: %s", exc)
            return None

    def consume_energy(self, persona_id: str, amount: float,
                       reason: str = "internet_life") -> Optional[float]:
        """Deduct energy on the persona scope; None when ESM cannot consume."""
        star = self._star()
        if star is None:
            return None
        fn = getattr(star, "consume_energy", None)
        if fn is None:
            return None
        try:
            return float(fn(float(amount), reason, scope=self.scope_for(persona_id)))
        except Exception as exc:
            logger.debug("consume_energy failed: %s", exc)
            return None

    def get_mood_context(self, persona_id: str) -> str:
        star = self._star()
        if star is None:
            return ""
        scope = self.scope_for(persona_id)
        builder = getattr(star, "build_prompt_block", None)
        if builder:
            try:
                value = builder(scope)
                return str(value or "")
            except Exception as exc:
                logger.debug("build_prompt_block failed: %s", exc)
        state_fn = getattr(star, "get_combined_state", None)
        if state_fn:
            try:
                view = state_fn(scope)
                label = getattr(view, "combined_label", "")
                if label:
                    return f"当前情绪标签：{label}"
            except Exception as exc:
                logger.debug("get_combined_state failed: %s", exc)
        return ""

    def gate_energy(self, persona_id: Optional[str] = None) -> tuple[bool, Optional[float], str]:
        """Return (blocked, energy, reason) for a scheduled browse session."""
        energy = self.get_energy(persona_id)
        if energy is None:
            return False, None, "esm_unavailable"
        if energy < self.energy_gate:
            return True, energy, "energy_gate"
        return False, energy, ""

    def apply_browse_signal(self, persona_id: str, mood: str = "curious",
                            intensity: float = 0.3) -> bool:
        return self._apply_signal(persona_id, _SIGNAL_CANDIDATES, intensity,
                                  reason="internet_life")

    def apply_self_reply_signal(self, persona_id: str, intensity: float = 0.08) -> bool:
        return self._apply_signal(persona_id, ("self_reply",), intensity,
                                  reason="internet_share")

    def _apply_signal(self, persona_id: str, candidates: tuple[str, ...],
                      intensity: float, reason: str) -> bool:
        star = self._star()
        if star is None:
            return False
        list_fn = getattr(star, "list_signals", None)
        valid: set[str] = set()
        if list_fn:
            try:
                valid = {str(s).lower() for s in list_fn()}
            except Exception as exc:
                logger.debug("list_signals failed: %s", exc)
        chosen = ""
        for signal in candidates:
            if not valid or signal in valid:
                chosen = signal
                break
        if not chosen:
            return False
        apply = getattr(star, "try_apply_signal", None) or getattr(star, "apply_signal", None)
        if apply is None:
            return False
        try:
            apply(self.scope_for(persona_id), "", chosen,
                  intensity=float(intensity), reason=reason)
            return True
        except Exception as exc:
            logger.debug("apply_signal(%s) failed: %s", chosen, exc)
            return False