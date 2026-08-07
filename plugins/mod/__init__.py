"""Mod plugin package."""

from cazzubot import Plugin

from . import db
from .cog import ModCog, on_modlog_due


class ModPlugin(Plugin):
    name = "mod"
    schema = db.SCHEMA
    cogs = [ModCog]
    scheduled = {"modlog": on_modlog_due}


plugin = ModPlugin()
