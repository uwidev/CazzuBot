"""Levels plugin package."""

from cazzubot import Plugin

from .cog import LevelsCog


class LevelsPlugin(Plugin):
	name = "levels"
	cogs = [LevelsCog]


plugin = LevelsPlugin()
