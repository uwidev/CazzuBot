"""Ranks plugin package."""

from cazzubot import Plugin

from . import db
from .cog import RanksCog


class RanksPlugin(Plugin):
	name = "ranks"
	schema = db.SCHEMA
	cogs = [RanksCog]


plugin = RanksPlugin()
