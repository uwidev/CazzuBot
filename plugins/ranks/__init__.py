"""Ranks plugin package."""

from cazzubot import Plugin

from . import db


class RanksPlugin(Plugin):
    name = "ranks"
    schema = db.SCHEMA
    extensions = ["plugins.ranks.cog"]


plugin = RanksPlugin()
