"""Mod plugin package."""

from cazzubot import Plugin

from . import db
from .cog import on_modlog_due


class ModPlugin(Plugin):
    name = "mod"
    schema = db.SCHEMA
    extensions = ["plugins.mod.cog"]
    scheduled = {"modlog": on_modlog_due}


plugin = ModPlugin()
