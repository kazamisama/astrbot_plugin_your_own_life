"""Minimal astrbot stubs so main.py can be imported outside AstrBot."""
from __future__ import annotations

import logging
import sys
import types


def _module(name: str) -> types.ModuleType:
    mod = types.ModuleType(name)
    sys.modules.setdefault(name, mod)
    return mod


astrbot = _module("astrbot")
api = _module("astrbot.api")
api.logger = logging.getLogger("astrbot.api")
core = _module("astrbot.core")
cfg_pkg = _module("astrbot.core.config")
acfg = _module("astrbot.core.config.astrbot_config")


class AstrBotConfig(dict):
    pass


acfg.AstrBotConfig = AstrBotConfig

msg_pkg = _module("astrbot.core.message")
components = _module("astrbot.core.message.components")
result_mod = _module("astrbot.core.message.message_event_result")


class Plain:
    def __init__(self, text=""):
        self.text = text


class MessageChain(list):
    pass


components.Plain = Plain
result_mod.MessageChain = MessageChain

event_mod = _module("astrbot.api.event")
star_mod = _module("astrbot.api.star")


class AstrMessageEvent:
    def __init__(self, message_str="", sender_id="", self_id=""):
        self.message_str = message_str
        self._sender_id = sender_id
        self._self_id = self_id
        self._result = None

    def get_sender_id(self):
        return self._sender_id

    def get_self_id(self):
        return self._self_id

    def plain_result(self, text):
        return {"type": "plain", "text": text}

    def set_result(self, result):
        self._result = result


class PermissionType:
    ADMIN = "admin"


class _Filter:
    PermissionType = PermissionType

    def command(self, name):
        def deco(fn):
            fn._command = name
            return fn
        return deco

    def permission_type(self, perm):
        def deco(fn):
            fn._permission = perm
            return fn
        return deco

    def event_message_type(self, *args, **kwargs):
        return lambda fn: fn

    def on_llm_request(self, *args, **kwargs):
        return lambda fn: fn


event_mod.AstrMessageEvent = AstrMessageEvent
event_mod.filter = _Filter()


class Context:
    def __init__(self):
        self.persona_manager = None
        self.conversation_manager = None
        self.sent = []

    def get_registered_star(self, plugin_id):
        return None

    def get_provider_by_id(self, provider_id):
        return None

    def get_using_provider(self):
        return None

    async def send_message(self, session_id, chain):
        self.sent.append((session_id, chain))
        return True


class Star:
    def __init__(self, context):
        self.context = context


star_mod.Context = Context
star_mod.Star = Star