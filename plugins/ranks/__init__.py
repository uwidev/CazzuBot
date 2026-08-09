"""Ranks plugin package."""

from cazzubot import Plugin

from . import db


class RanksPlugin(Plugin):
    name = "ranks"
    schema = db.SCHEMA
    extensions = ["plugins.ranks.cog"]
    # rank lookups (of_member) need seasonal exp from the experience tables
    depends_on = ("experience",)


plugin = RanksPlugin()
