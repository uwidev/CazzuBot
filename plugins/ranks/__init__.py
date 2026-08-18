"""Ranks plugin package."""

from cazzubot import Plugin

from . import db


class RanksPlugin(Plugin):
    """Ranks plugin — threshold roles, seasonal and lifetime."""

    name = "ranks"
    schema = db.SCHEMA
    extensions = ["plugins.ranks.extension"]
    # rank lookups (of_member) need seasonal exp from the experience tables
    depends_on = ("experience",)


plugin = RanksPlugin()
